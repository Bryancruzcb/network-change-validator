#!/usr/bin/env bash
# The OSPF dead-timer run on the DevNet CML default-lab in one command. Prepared, not run yet.
#
# The OSPF twin of run-bgp-holdtimer.sh. Returns both routers to the shipped configuration, sets
# up OSPF area 0 on the R1-R2 link with a 1 s hello on Ethernet0/1 of both routers (IOS derives
# a 4 s dead interval from it), waits for FULL, checks both routers report Hello 1, Dead 4, pre
# capture, no-change check, then the change: an inbound ACL on R1 Ethernet0/1 that drops OSPF
# from R2. Nothing is shut down, so the adjacency dies the way it does when a path stops
# carrying OSPF: R1 stops hearing R2 and its dead timer runs out, while R2 still hears R1 and is
# predicted to hold R1 in INIT. Post capture and compare, remove the ACL, wait for FULL,
# restored capture and compare. The predicted findings of the change comparison are in
# scripts/lab/expect-ospf-deadtimer.txt, and scripts/lab/README.md explains them; the script
# exits 0 only when every comparison exits as predicted and the change comparison finds exactly
# those findings, 3 when it ran to the end but one did not, and 1 when it stopped early.
#
# Packet evidence: right before the change, scripts/lab/cml_capture.py starts a capture of
# `ip proto 89` (OSPF) on the R1-R2 link through the CML API, with the CML login given below; at
# the end it saves captures/ospf-deadtimer-<stamp>/link.pcap and scripts/lab/link_pcap.py lists
# the OSPF packets in it. If the capture cannot start, the run goes on without one; if the run
# stops early, the capture is stopped and saved on the way out. NCV_PCAP=0 skips it.
#
# Asks for the logins once, unless the NCV_* variables already hold them, so the passwords stay
# in this terminal. Stops before touching the lab if the timers or the no-change check are
# wrong. Captures go to captures/ospf-deadtimer-<stamp>/, reports and the log to output/lab/.
# Run it from WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"
lab_takes_no_arguments "$@"
lab_init ospf-deadtimer
features=ospf,routing,interface
intent=scripts/lab/intent-ospf-deadtimer.yaml
undo_hint="run scripts/lab/change.sh deadtimer-undo, or let the next run's labctl.py reset remove it"

step "1/11 reset both routers to the shipped configuration (a reused reservation may carry an earlier run)"
lab_reset
step "2/11 set up OSPF area 0 with a 1 s hello on the R1-R2 link (operator setup, outside ncv)"
ctl setup-ospf-fast || { step "OSPF setup failed"; exit 1; }
step "3/11 wait for both neighbors to reach FULL"
ctl wait-full 180 || { step "neighbors never reached FULL, stopping before any capture"; exit 1; }
step "4/11 check both routers run Hello 1, Dead 4 on Ethernet0/1"
ctl check-dead-time || { step "timers not in effect, stopping before any capture"; exit 1; }
step "5/11 pre capture"
snap pre || { step "pre capture failed, nothing was changed"; exit 1; }
step "6/11 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
expect_exit baseline 0 "$rc"
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change"; exit 1; }
cap_start "ip proto 89"
step "7/11 change: inbound ACL NCV-BLOCK-OSPF on R1 Ethernet0/1 drops OSPF from R2"
ctl ospf-block || { step "change failed; $undo_hint"; exit 1; }
step "8/11 wait for both routers to leave FULL (R1's dead interval is 4 s; R2 is predicted to stay in INIT)"
ctl wait-ospf-lost 60 || step "a neighbor still shows FULL, capturing anyway"
step "9/11 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; the ACL is still on R1, $undo_hint"; exit 1; }
compare pre post change; expect_exit change 1 "$?"
expect_findings change "$out-change" scripts/lab/expect-ospf-deadtimer.txt
step "10/11 undo: remove the ACL and wait for FULL again"
ctl ospf-unblock || { step "undo failed; $undo_hint"; exit 1; }
ctl wait-full 180 || step "neighbors not FULL yet, capturing anyway"
step "11/11 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; expect_exit restored 0 "$?"
cap_stop
lab_finish
