#!/usr/bin/env bash
# The BGP VRF run on the DevNet CML default-lab in one command. Prepared, not run yet.
#
# Every BGP capture so far had one session, in the global table. This run keeps the hold-timer
# run's eBGP session there (R1 AS 65001, R2 AS 65002, a 9 s hold time, untagged on Ethernet0/1)
# and adds a second session to the same peer address inside vrf NCV, on the dot1Q subinterface
# Ethernet0/1.100, which reuses the link's own addresses. Then it breaks only that one. It is
# the live test of ncv keeping BGP neighbors by VRF: the same address in two VRFs must be
# captured as two neighbors, and a change to one must be reported for that one only.
#
# Returns both routers to the shipped configuration and waits for IOS to finish deleting any
# earlier vrf NCV, sets up the hold-timer run's session and then the VRF one, waits for both
# sessions in each table and checks the 9 s hold time on each, pre capture, no-change check,
# then the change: `shutdown` on R1 Ethernet0/1.100. The prediction is that R1 resets its VRF
# session at once (a directly connected eBGP neighbor whose interface went down) and loses the
# VRF's connected 1.1.1.0/24, while R2, whose subinterface stays up, keeps the session until its
# 9 s hold timer runs out and then loses the prefix it learned; both global sessions stay
# Established. Post capture and compare, `no shutdown`, wait for the VRF sessions, restored
# capture and compare. The predicted findings of the change comparison are in
# scripts/lab/expect-bgp-vrf.txt, and scripts/lab/README.md explains them; the script exits 0
# only when every comparison exits as predicted and the change comparison finds exactly those
# findings, 3 when it ran to the end but one did not, and 1 when it stopped early.
#
# Packet evidence: right before the change, scripts/lab/cml_capture.py starts a capture of
# `tcp port 179 or (vlan and tcp port 179)` on the R1-R2 link through the CML API, so both the
# untagged session and the tagged one are kept; at the end it saves
# captures/bgp-vrf-<stamp>/link.pcap and scripts/lab/link_pcap.py prints one timeline of the BGP
# segments in it, the VRF session's marked `vlan 100`. If the capture cannot start, the run goes
# on without one; if the run stops early, the capture is stopped and saved on the way out.
# NCV_PCAP=0 skips it.
#
# Asks for the logins once, unless the NCV_* variables already hold them, so the passwords stay
# in this terminal. Stops before touching the lab if the timers or the no-change check are
# wrong. Captures go to captures/bgp-vrf-<stamp>/, reports and the log to output/lab/. Run it
# from WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"
lab_takes_no_arguments "$@"
lab_init bgp-vrf
features=bgp,routing,interface
intent=scripts/lab/intent-bgp-vrf.yaml
undo_hint="run scripts/lab/change.sh vrf-undo, or let the next run's labctl.py reset remove it"

step "1/11 reset both routers to the shipped configuration (a router runs one BGP process, and a reused reservation may carry an earlier run), then wait for IOS to finish deleting any earlier vrf NCV"
lab_reset
ctl wait-vrf-gone 90 || { step "vrf NCV is still listed after 90 s; IOS refuses its route distinguisher until the deletion ends, so run this script again in a minute (it resets and waits again)"; exit 1; }
step "2/11 set up eBGP with a 3 s keepalive and a 9 s hold time, then the second session in vrf NCV on Ethernet0/1.100 (operator setup, outside ncv)"
ctl setup-bgp-fast || { step "BGP setup failed"; exit 1; }
ctl setup-vrf || { step "VRF setup failed"; exit 1; }
step "3/11 wait for both global sessions to reach Established, then for both vrf NCV sessions to learn a prefix"
ctl wait-bgp-up 180 || { step "global sessions never reached Established, stopping before any capture"; exit 1; }
ctl wait-vrf-bgp-up 180 || { step "vrf NCV sessions never learned a prefix, stopping before any capture"; exit 1; }
step "4/11 check both tables' sessions negotiated the 9 s hold time"
ctl check-hold-time || { step "global BGP timers not in effect, stopping before any capture"; exit 1; }
ctl check-vrf-hold-time || { step "vrf NCV BGP timers not in effect, stopping before any capture"; exit 1; }
step "5/11 pre capture"
if ! snap pre; then
  if grep -q "ambiguous BGP neighbor .*: multiple VRFs or instances" "$log"; then
    step "pre capture failed, nothing was changed: ncv in this clone predates BGP neighbors keyed by VRF: update the clone to this branch"
  else
    step "pre capture failed, nothing was changed"
  fi
  exit 1
fi
step "6/11 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
expect_exit baseline 0 "$rc"
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change"; exit 1; }
cap_start "tcp port 179 or (vlan and tcp port 179)"
step "7/11 change: shutdown on R1 Ethernet0/1.100 (the global session on Ethernet0/1 is not touched)"
ctl vrf-shut || { step "change failed; $undo_hint"; exit 1; }
step "8/11 wait for both vrf NCV sessions to leave Established (R1 at once, R2 on its 9 s hold time)"
ctl wait-vrf-bgp-down 60 || step "a vrf NCV session still shows Established, capturing anyway"
step "9/11 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; R1 Ethernet0/1.100 is still shut down, $undo_hint"; exit 1; }
compare pre post change; expect_exit change 1 "$?"
expect_findings change "$out-change" scripts/lab/expect-bgp-vrf.txt
step "10/11 undo: no shutdown on R1 Ethernet0/1.100, then wait for both vrf NCV sessions to learn a prefix again"
ctl vrf-noshut || { step "undo failed; $undo_hint"; exit 1; }
ctl wait-vrf-bgp-up 240 || step "vrf NCV sessions have not learned a prefix yet, capturing anyway"
step "11/11 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; expect_exit restored 0 "$?"
cap_stop
lab_finish
