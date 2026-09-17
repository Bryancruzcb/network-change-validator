#!/usr/bin/env bash
# One live capture of R1 and R2 in the DevNet CML sandbox, for a run driven by hand.
# Prompts for the logins, so the passwords stay in this terminal.
# Usage: capture.sh pre|post|restored [features]    (features default to routing,interface)
set -uo pipefail
step="${1:?usage: capture.sh pre|post|restored [features]}"
features="${2:-routing,interface}"
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../.." || exit 2
ip -brief addr show tun0 >/dev/null 2>&1 || { echo "The sandbox VPN is not connected. Start openconnect first."; exit 2; }
read -rp "CML username [developer]: " u; export NCV_CML_USER="${u:-developer}"
read -rsp "CML password (the developer one): " p; echo; export NCV_CML_PASS="$p"
read -rsp "Router enable password (the cisco one): " rp; echo; export NCV_LAB_PASS="$rp"

py="${NCV_PYTHON:-.venv/bin/python}"
mkdir -p captures output/lab
log=output/lab/last-capture.log
out="captures/$step"; n=2
while [ -e "$out" ]; do out="captures/$step-$n"; n=$((n+1)); done
echo "Capturing R1 and R2 ($features) into $out from the isolated DevNet sandbox lab..." | tee "$log"
"$py" -m ncv snapshot --testbed testbeds/lab.yaml --output "$out" --features "$features" --i-am-in-a-lab 2>&1 | tee -a "$log"
rc=${PIPESTATUS[0]}
echo "snapshot exit=$rc output=$out" | tee -a "$log"
exit "$rc"
