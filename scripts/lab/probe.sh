#!/usr/bin/env bash
# The lab probe: what the sandbox answers, asked without changing anything. Read-only.
#
# Two things decide what the next lab runs can do and are still unknown: whether the routers'
# management addresses (10.10.20.171 and .172, Ethernet0/2 in vrf Mgmt-intf) answer over the
# VPN, which they did not on 2026-09-12 for reasons nobody recorded, and which node images the
# CML controller has. This asks, in four steps:
#
#   1. from this machine: the VPN address and the route to 10.10.20.171, then for both
#      management addresses a TCP connect test to ports 22 and 23 (open, refused, or no answer
#      in 3 s) and a ping;
#   2. the CML controller: scripts/lab/cml_lab.py inspect, every call after the login (a POST
#      to /authenticate) a GET, saving each response under output/lab/probe-<stamp>-cml/;
#   3. the routers, through the console testbed: labctl.py probe, a fixed list of read-only show
#      and ping commands on R1 and R2;
#   4. three answers, each with the line it came from: do the management addresses answer on
#      port 22; is R1 Ethernet0/3 free; which second-platform images exist.
#
# It sends no configuration to any device and changes nothing in CML; `show running-config` is
# not among the router commands. Asks for the logins once, unless the NCV_* variables already
# hold them. Everything goes to the screen and to output/lab/probe-<stamp>.log. Exits 1 when the
# CML login or the console connection to a router fails (every run needs both), 0 otherwise, and
# 2 when it cannot start (no VPN, no testbed file, or no answer to a login prompt). Run it from
# WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"
lab_init probe
rmdir "$run" 2>/dev/null  # lab_init makes a capture directory; the probe captures nothing
failed=0
addresses="10.10.20.171 10.10.20.172"

step "1/4 the VPN side, from this machine"
ip -brief addr show tun0 2>&1 | tee -a "$log"
ip route get 10.10.20.171 2>&1 | tee -a "$log"
open22=0
for address in $addresses; do
  lab_tcp "$address" 22 && open22=$((open22 + 1))
  lab_tcp "$address" 23
  ping -c 2 -W 2 "$address" 2>&1 | tee -a "$log"
done

step "2/4 the CML controller: node definitions, images, and default-lab (read-only)"
"$py" "$here/cml_lab.py" inspect "$out-cml" 2>&1 | tee "$out-cml.txt" | tee -a "$log"
[ "${PIPESTATUS[0]}" -eq 0 ] || { failed=1; step "cml_lab.py could not log in or find the lab"; }

step "3/4 the routers, through $testbed: read-only commands on R1 and R2"
ctl probe || { failed=1; step "the probe could not connect to a router"; }

step "4/4 summary"
case $open22 in
  2) answer=yes ;;
  0) answer=no ;;
  *) answer="one of the two" ;;
esac
echo "answer: the management addresses answer on port 22: $answer" | tee -a "$log"
evidence=$(grep -F -e "10.10.20.171 port 22: " -e "10.10.20.172 port 22: " "$log")
echo "$evidence" | sed "s/^/  from: /" | tee -a "$log"
if ! grep '^answer: ' "$out-cml.txt" | tee -a "$log"; then
  echo "answer: R1 Ethernet0/3 free and second-platform images: unknown (cml_lab.py gave no answers; see step 2)" | tee -a "$log"
fi
step "done: the log is $log, the CML responses are in $out-cml/"
if lab_log_holds_a_password; then
  step "a password value appears in $log; do not publish it"
fi
exit "$failed"
