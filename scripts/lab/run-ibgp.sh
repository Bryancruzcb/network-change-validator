#!/usr/bin/env bash
# The iBGP run on the DevNet CML default-lab in one command. Prepared, not run yet.
#
# Every earlier BGP run was eBGP between directly connected addresses. This one is iBGP as it is
# usually built: the session runs between the routers' Loopback0 addresses, and those are
# reachable only through OSPF, so BGP depends on OSPF. Returns both routers to the shipped
# configuration (a router runs one BGP process, so the eBGP setup cannot stay), then sets up two
# loopbacks per router, OSPF with a 1 s hello and Loopback0 in area 0, and iBGP in AS 65010 from
# Loopback0 to the peer's Loopback0 with a 9 s hold time, each router originating its Loopback1
# subnet. Waits for FULL and checks the 4 s dead interval, waits for both sessions to learn a
# prefix and checks the 9 s hold time, pre capture, no-change check, then the change: the
# dead-timer run's inbound ACL on R1 Ethernet0/1 that drops OSPF from R2. Nothing about BGP is
# touched. The prediction is that one cause shows in three layers: the OSPF adjacencies, the
# routes to the peer loopbacks, and, seconds later, the iBGP sessions and the prefixes learned
# over them. Post capture and compare, remove the ACL, wait for FULL and for the sessions,
# restored capture and compare. scripts/lab/README.md has the predicted findings; the script
# exits 0 only when every comparison exits as predicted, 3 when it ran to the end but one did
# not, and 1 when it stopped early.
#
# Packet evidence: right before the change, scripts/lab/cml_capture.py starts a capture of
# `ip proto 89 or tcp port 179` (OSPF and BGP) on the R1-R2 link through the CML API, with the
# CML login given below; at the end it saves captures/ibgp-<stamp>/link.pcap and
# scripts/lab/link_pcap.py prints one timeline of the OSPF packets and BGP segments in it. If the
# capture cannot start, the run goes on without one. NCV_PCAP=0 skips it.
#
# Asks for the logins once, unless the NCV_* variables already hold them, so the passwords stay
# in this terminal. Stops before touching the lab if the timers or the no-change check are
# wrong. Captures go to captures/ibgp-<stamp>/, reports and the log to output/lab/. Run it from
# WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"
lab_init ibgp
features=ospf,bgp,routing,interface
intent=scripts/lab/intent-ibgp.yaml

step "1/11 reset both routers to the shipped configuration (a router runs one BGP process, and a reused reservation may carry an earlier run)"
ctl reset || { step "reset failed: the lab may still hold an earlier run's configuration; read the lines above, then run labctl.py reset again"; exit 1; }
step "2/11 set up the loopbacks, OSPF with a 1 s hello, and iBGP in AS 65010 between the loopbacks (operator setup, outside ncv)"
ctl setup-ibgp || { step "iBGP setup failed"; exit 1; }
step "3/11 wait for both OSPF neighbors to reach FULL, then check Hello 1, Dead 4 on Ethernet0/1"
ctl wait-full 180 || { step "neighbors never reached FULL, stopping before any capture"; exit 1; }
ctl check-dead-time || { step "OSPF timers not in effect, stopping before any capture"; exit 1; }
step "4/11 wait for both iBGP sessions to learn a prefix, then check the 9 s hold time"
ctl wait-ibgp-up 180 || { step "sessions never learned a prefix, stopping before any capture"; exit 1; }
ctl check-ibgp-hold-time || { step "BGP timers not in effect, stopping before any capture"; exit 1; }
step "5/11 pre capture"
snap pre || { step "pre capture failed, nothing was changed"; exit 1; }
step "6/11 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
expect_exit baseline 0 "$rc"
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change"; exit 1; }
capturing=0
if [ "${NCV_PCAP:-1}" != 0 ]; then
  step "packet capture: start capturing ip proto 89 or tcp port 179 on the R1-R2 link through the CML API"
  if cap start --filter "ip proto 89 or tcp port 179"; then capturing=1; else step "no packet capture; the run goes on without one"; fi
fi
step "7/11 change: inbound ACL NCV-BLOCK-OSPF on R1 Ethernet0/1 drops OSPF from R2 (nothing about BGP is touched)"
ctl ospf-block || { step "change failed; run scripts/lab/change.sh deadtimer-undo, or let the next run's labctl.py reset remove it"; exit 1; }
step "8/11 wait for both routers to leave FULL (about 4 s), then for both iBGP sessions to drop (the 9 s hold time)"
ctl wait-ospf-lost 60 || step "an OSPF neighbor still shows FULL, going on"
ctl wait-ibgp-down 60 || step "an iBGP session still shows Established, capturing anyway"
step "9/11 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; the ACL is still on R1, run scripts/lab/change.sh deadtimer-undo, or let the next run's labctl.py reset remove it"; exit 1; }
compare pre post change; expect_exit change 1 "$?"
step "10/11 undo: remove the ACL, wait for FULL, then for both iBGP sessions to learn a prefix again"
ctl ospf-unblock || { step "undo failed; run scripts/lab/change.sh deadtimer-undo, or let the next run's labctl.py reset remove it"; exit 1; }
ctl wait-full 180 || step "neighbors not FULL yet, going on"
ctl wait-ibgp-up 240 || step "sessions have not learned a prefix yet, capturing anyway"
step "11/11 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; expect_exit restored 0 "$?"
if [ "$capturing" -eq 1 ]; then
  step "packet capture: stop and save $run/link.pcap"
  cap stop "$run/link.pcap" || step "could not save the packet capture"
fi
if [ -f "$run/link.pcap" ]; then
  step "packet timeline of $run/link.pcap"
  "$py" "$here/link_pcap.py" "$run/link.pcap" 2>&1 | tee "$out-pcap.txt" | tee -a "$log"
fi
lab_finish
