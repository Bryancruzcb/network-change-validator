#!/usr/bin/env bash
# The BGP run on the DevNet CML default-lab in one command: set up eBGP between R1 (AS 65001)
# and R2 (AS 65002) over the 1.1.1.0/24 link, wait for Established, pre capture, no-change check,
# `neighbor 1.1.1.2 shutdown` on R1, wait for both sessions to leave Established, post capture and
# compare, `no neighbor 1.1.1.2 shutdown`, wait for Established, restored capture and compare.
# This is the run recorded in fixtures/lab-2026-09-18/bgp. The planned change is an administrative
# peer shutdown rather than a link shutdown, so both routers drop the session at once and the
# routes and interfaces stay compliant.
#
# Asks for the logins once, so the passwords stay in this terminal. Stops before touching
# the lab if the no-change check fails. Captures go to captures/bgp-<stamp>/, reports and
# the log to output/lab/. Run it from WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../.." || exit 2
ip -brief addr show tun0 >/dev/null 2>&1 || { echo "The sandbox VPN is not connected. Start openconnect first."; exit 2; }
read -rp "CML username [developer]: " u; export NCV_CML_USER="${u:-developer}"
read -rsp "CML password (the developer one): " p; echo; export NCV_CML_PASS="$p"
read -rsp "Router enable password (the cisco one): " rp; echo; export NCV_LAB_PASS="$rp"

py="${NCV_PYTHON:-.venv/bin/python}"
stamp=$(date +%Y%m%d-%H%M)
run="captures/bgp-$stamp"
out="output/lab/bgp-$stamp"
log="$out.log"
intent=fixtures/lab-2026-09-18/intent-bgp.yaml
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

step "1/9 set up eBGP between R1 and R2 (operator setup, outside ncv)"
ctl setup-bgp || { step "BGP setup failed"; exit 1; }
step "2/9 wait for both sessions to reach Established"
ctl wait-bgp-up 180 || { step "sessions never reached Established, stopping before any capture"; exit 1; }
step "3/9 pre capture"
snap pre || { step "pre capture failed, nothing was changed"; exit 1; }
step "4/9 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change"; exit 1; }
step "5/9 change: neighbor 1.1.1.2 shutdown on R1"
ctl bgp-shut || { step "change failed"; exit 1; }
step "6/9 wait for both sessions to leave Established"
ctl wait-bgp-down 60 || step "a session still shows Established, capturing anyway"
step "7/9 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; the R1 peer is still shut down, run scripts/lab/change.sh bgp-undo"; exit 1; }
compare pre post change; echo "change compare exit=$?" | tee -a "$log"
step "8/9 undo and wait for Established again"
ctl bgp-noshut || { step "undo failed; run scripts/lab/change.sh bgp-undo"; exit 1; }
ctl wait-bgp-up 180 || step "sessions not Established yet, capturing anyway"
step "9/9 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; echo "restored compare exit=$?" | tee -a "$log"
step "done: captures in $run, reports and log in output/lab/"
