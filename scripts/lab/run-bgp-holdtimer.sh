#!/usr/bin/env bash
# The BGP hold-timer run on the DevNet CML default-lab in one command. This is the run recorded
# in fixtures/lab-2026-11-20/bgp-holdtimer.
#
# Sets up eBGP between R1 (AS 65001) and R2 (AS 65002) over the 1.1.1.0/24 link with a 3 s
# keepalive and a 9 s hold time, checks both sessions negotiated those timers, pre capture,
# no-change check, then the change: an inbound ACL on R1 Ethernet0/1 that drops BGP from R2.
# Nothing is shut down and no BGP command changes, so the session dies the way it does when a
# path stops carrying BGP: R1 stops hearing R2's keepalives and its hold timer expires. Post
# capture and compare, remove the ACL, wait for Established, restored capture and compare.
# scripts/lab/README.md has the predicted findings.
#
# Optional packet evidence: the script pauses before the change so you can start a packet
# capture on the R1-R2 link in the CML UI, and again at the end so you can save it as
# captures/bgp-holdtimer-<stamp>/link.pcap. If that file exists, scripts/lab/bgp_pcap.py
# lists the BGP messages in it. Press Enter at either pause to skip.
#
# Asks for the logins once, so the passwords stay in this terminal. Stops before touching
# the lab if the timers or the no-change check are wrong. Captures go to
# captures/bgp-holdtimer-<stamp>/, reports and the log to output/lab/. Run it from WSL or Linux
# with the sandbox VPN up, on a fresh reservation.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../.." || exit 2
ip -brief addr show tun0 >/dev/null 2>&1 || { echo "The sandbox VPN is not connected. Start openconnect first."; exit 2; }
read -rp "CML username [developer]: " u; export NCV_CML_USER="${u:-developer}"
read -rsp "CML password (the developer one): " p; echo; export NCV_CML_PASS="$p"
read -rsp "Router enable password (the cisco one): " rp; echo; export NCV_LAB_PASS="$rp"

py="${NCV_PYTHON:-.venv/bin/python}"
stamp=$(date +%Y%m%d-%H%M)
run="captures/bgp-holdtimer-$stamp"
out="output/lab/bgp-holdtimer-$stamp"
log="$out.log"
intent=fixtures/lab-2026-11-20/intent-bgp-holdtimer.yaml
mkdir -p "$run" output/lab

step() { echo "== $(date +%T) $*" | tee -a "$log"; }
ctl() { "$py" "$here/labctl.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
snap() {
  "$py" -m ncv snapshot --testbed testbeds/lab.yaml --output "$run/$1" \
    --features bgp,routing,interface --i-am-in-a-lab 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
compare() {
  "$py" -m ncv diff "$run/$1" "$run/$2" --intent "$intent" --report "$out-$3" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}

step "1/10 set up eBGP with a 3 s keepalive and a 9 s hold time (operator setup, outside ncv)"
ctl setup-bgp-fast || { step "BGP setup failed"; exit 1; }
step "2/10 wait for both sessions to reach Established"
ctl wait-bgp-up 180 || { step "sessions never reached Established, stopping before any capture"; exit 1; }
step "3/10 check both sessions negotiated the 9 s hold time"
ctl check-hold-time || { step "timers not in effect, stopping before any capture"; exit 1; }
step "4/10 pre capture"
snap pre || { step "pre capture failed, nothing was changed"; exit 1; }
step "5/10 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change"; exit 1; }
read -rp "Optional: start a packet capture on the R1-R2 link in the CML UI now, then press Enter. " _
step "6/10 change: inbound ACL NCV-BLOCK-BGP on R1 Ethernet0/1 drops BGP from R2"
ctl bgp-block || { step "change failed; run scripts/lab/change.sh holdtimer-undo"; exit 1; }
step "7/10 wait for both sessions to leave Established (the hold time is 9 s)"
ctl wait-bgp-down 60 || step "a session still shows Established, capturing anyway"
step "8/10 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; the ACL is still on R1, run scripts/lab/change.sh holdtimer-undo"; exit 1; }
compare pre post change; echo "change compare exit=$?" | tee -a "$log"
step "9/10 undo: remove the ACL and wait for Established again"
ctl bgp-unblock || { step "undo failed; run scripts/lab/change.sh holdtimer-undo"; exit 1; }
ctl wait-bgp-up 240 || step "sessions not Established yet, capturing anyway"
step "10/10 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; echo "restored compare exit=$?" | tee -a "$log"
read -rp "Optional: stop the packet capture and save it as $run/link.pcap, then press Enter. " _
if [ -f "$run/link.pcap" ]; then
  step "packet summary of $run/link.pcap"
  "$py" "$here/bgp_pcap.py" "$run/link.pcap" 2>&1 | tee "$out-pcap.txt" | tee -a "$log"
fi
step "done: captures in $run, reports and log in output/lab/"
