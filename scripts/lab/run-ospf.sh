#!/usr/bin/env bash
# The OSPF run on the DevNet CML default-lab in one command: set up OSPF area 0 between R1
# and R2, wait for FULL, pre capture, no-change check, shutdown on R1 Ethernet0/1, wait for
# both neighbor entries to clear, post capture and compare, no shutdown, wait for FULL,
# restored capture and compare. This is the run recorded in fixtures/lab-2026-09-12/ospf.
#
# Asks for the logins once, so the passwords stay in this terminal. Stops before touching
# the lab if the no-change check fails. Captures go to captures/ospf-<stamp>/, reports and
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
run="captures/ospf-$stamp"
out="output/lab/ospf-$stamp"
log="$out.log"
intent=fixtures/lab-2026-09-12/intent-ospf.yaml
mkdir -p "$run" output/lab

step() { echo "== $(date +%T) $*" | tee -a "$log"; }
ctl() { "$py" "$here/labctl.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
snap() {
  "$py" -m ncv snapshot --testbed testbeds/lab.yaml --output "$run/$1" \
    --features ospf,routing,interface --i-am-in-a-lab 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
compare() {
  "$py" -m ncv diff "$run/$1" "$run/$2" --intent "$intent" --report "$out-$3" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}

step "1/9 set up OSPF area 0 on the R1-R2 link (operator setup, outside ncv)"
ctl setup-ospf || { step "OSPF setup failed"; exit 1; }
step "2/9 wait for both neighbors to reach FULL"
ctl wait-full 180 || { step "neighbors never reached FULL, stopping before any capture"; exit 1; }
step "3/9 pre capture"
snap pre || { step "pre capture failed, nothing was changed"; exit 1; }
step "4/9 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change"; exit 1; }
step "5/9 change: shutdown R1 Ethernet0/1"
ctl shut || { step "change failed"; exit 1; }
step "6/9 wait for both neighbor entries to clear (R2 waits out its dead timer)"
ctl wait-gone 90 || step "neighbor entries did not both clear in time, capturing anyway"
step "7/9 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; R1 Ethernet0/1 is still shut, run scripts/lab/change.sh undo"; exit 1; }
compare pre post change; echo "change compare exit=$?" | tee -a "$log"
step "8/9 undo and wait for FULL again"
ctl noshut || { step "undo failed; run scripts/lab/change.sh undo"; exit 1; }
ctl wait-full 180 || step "neighbors not FULL yet, capturing anyway"
step "9/9 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; echo "restored compare exit=$?" | tee -a "$log"
step "done: captures in $run, reports and log in output/lab/"
