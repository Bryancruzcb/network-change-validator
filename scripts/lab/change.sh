#!/usr/bin/env bash
# The one planned lab change, applied by hand outside ncv. Prompts for the logins, so the
# passwords stay in this terminal, then hands the work to labctl.py.
# Usage: change.sh apply|undo          shut / no shut R1 Ethernet0/1 (the R1-R2 link)
#        change.sh bgp-apply|bgp-undo  neighbor 1.1.1.2 shutdown / no shutdown on R1
set -uo pipefail
action="${1:?usage: change.sh apply|undo|bgp-apply|bgp-undo}"
case "$action" in
  apply) cmd=shut ;;
  undo) cmd=noshut ;;
  bgp-apply) cmd=bgp-shut ;;
  bgp-undo) cmd=bgp-noshut ;;
  *) echo "usage: change.sh apply|undo|bgp-apply|bgp-undo"; exit 2 ;;
esac
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../.." || exit 2
ip -brief addr show tun0 >/dev/null 2>&1 || { echo "The sandbox VPN is not connected. Start openconnect first."; exit 2; }
read -rp "CML username [developer]: " u; export NCV_CML_USER="${u:-developer}"
read -rsp "CML password (the developer one): " p; echo; export NCV_CML_PASS="$p"
read -rsp "Router enable password (the cisco one): " rp; echo; export NCV_LAB_PASS="$rp"

py="${NCV_PYTHON:-.venv/bin/python}"
mkdir -p output/lab
log=output/lab/last-change.log
echo "$(date +%T) change.sh $action: labctl.py $cmd" | tee "$log"
"$py" "$here/labctl.py" "$cmd" 2>&1 | tee -a "$log"
rc=${PIPESTATUS[0]}
echo "change exit=$rc" | tee -a "$log"
exit "$rc"
