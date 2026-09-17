#!/usr/bin/env bash
# The static-route run on the DevNet CML default-lab in one command: pre capture, no-change
# check, one change (shutdown on R1 Ethernet0/1), post capture and compare, undo, restored
# capture and compare. This is the run recorded in fixtures/lab-2026-09-12/routes.
#
# Asks for the logins once, so the passwords stay in this terminal. Stops before touching
# the lab if the no-change check fails. Captures go to captures/run-<stamp>/, reports and
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
run="captures/run-$stamp"
out="output/lab/run-$stamp"
log="$out.log"
intent=fixtures/lab-2026-09-12/intent-routes.yaml
mkdir -p "$run" output/lab

step() { echo "== $(date +%T) $*" | tee -a "$log"; }
ctl() { "$py" "$here/labctl.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
snap() {
  "$py" -m ncv snapshot --testbed testbeds/lab.yaml --output "$run/$1" \
    --features routing,interface --i-am-in-a-lab 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
compare() {
  "$py" -m ncv diff "$run/$1" "$run/$2" --intent "$intent" --report "$out-$3" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}

step "1/7 pre capture"
snap pre || { step "pre capture failed, nothing was changed"; exit 1; }
step "2/7 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
[ "$rc" -eq 0 ] || { step "no-change check exited $rc: the intent does not match this lab, stopping before any change"; exit 1; }
step "3/7 change: shutdown R1 Ethernet0/1"
ctl shut || { step "change failed; check R1 in the CML UI"; exit 1; }
sleep 15
step "4/7 post capture"
snap post || { step "post capture failed; R1 Ethernet0/1 is still shut, run scripts/lab/change.sh undo"; exit 1; }
step "5/7 compare pre vs post (expect exit 1, findings name the change)"
compare pre post change; echo "change compare exit=$?" | tee -a "$log"
step "6/7 undo: no shutdown R1 Ethernet0/1"
ctl noshut || { step "undo failed; run scripts/lab/change.sh undo"; exit 1; }
sleep 20
step "7/7 restored capture and compare (expect exit 0)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; echo "restored compare exit=$?" | tee -a "$log"
step "done: captures in $run, reports and log in output/lab/"
