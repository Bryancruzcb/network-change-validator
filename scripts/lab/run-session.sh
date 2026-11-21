#!/usr/bin/env bash
# A whole lab session with one login: the prepared runs in order, asking for the logins once.
#
# Usage: run-session.sh [name ...]
#
# On 2026-11-20 every script asked for the three logins again, and a password pasted into a
# hidden prompt in an embedded terminal did not arrive, so each run cost several attempts. This
# script checks the VPN, asks once for NCV_CML_USER, NCV_CML_PASS, and NCV_LAB_PASS (again until
# each is not empty), plus NCV_SSH_USER and NCV_SSH_PASS when ssh-path is named, checks the CML
# login once with `cml_lab.py check-login`, and runs each named run's script with bash. The
# scripts' own lab_init then finds the logins set and does not ask again. Every name is checked
# before any prompt, the platform of second-platform:<platform> included.
#
# Names, run in the order given:
#   probe                       probe.sh: read-only; run it first on a new reservation
#   ospf-deadtimer              run-ospf-deadtimer.sh
#   ibgp                        run-ibgp.sh
#   bgp-vrf                     run-bgp-vrf.sh
#   ssh-path                    run-ssh-path.sh: only once the probe says port 22 answers
#   second-platform:<platform>  run-second-platform.sh <platform>: only once the probe says R1
#                               Ethernet0/3 is free and the platform has an image
#   reset                       labctl.py reset on R1 and R2; R3 stays (cml_lab.py remove-r3)
# With no names it runs `probe ospf-deadtimer ibgp bgp-vrf reset`: the runs that need nothing
# beyond the three logins the earlier runs used. ssh-path and second-platform are named on
# purpose, because each needs something the probe has to confirm first.
#
# A run that fails does not stop the session: every run script starts with labctl.py reset, so
# the next one starts clean. Two things do stop it, because every later run would fail the same
# way: a run that could not start (exit 2: the VPN dropped, a testbed file or a login is
# missing) and a probe that failed (the CML login or a console connection). It then prints the
# names still to run as a ready command; Ctrl-C prints the table so far and the same command.
#
# Each run gets its own NCV_STAMP (<session stamp>-<n>), so its log is
# output/lab/<run>-<session stamp>-<n>.log. At the end a table goes to the screen and to
# output/lab/session-<stamp>.log: each name, its exit status and what it means, where it
# stopped when it stopped early, and where its log is. The passwords never reach a log line, and
# this script never traces itself. It exits 0 only when every named run exited 0, 3 when it ran
# every name but one did not exit 0, 1 when it stopped before the last name, 2 when it could not
# start, and 130 on Ctrl-C. Run it from the WSL clone with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"

usage() {
  cat >&2 <<'EOF'
usage: run-session.sh [name ...]
names: probe, ospf-deadtimer, ibgp, bgp-vrf, ssh-path, second-platform:<platform>, reset
  with no names: probe ospf-deadtimer ibgp bgp-vrf reset
  ssh-path needs the probe to say the management addresses answer on port 22, and
  testbeds/lab-ssh.yaml; second-platform:<platform> (nxosv9000, cat8000v, or iosv) needs the
  probe to say R1 Ethernet0/3 is free and the platform has an image, and testbeds/lab-r3.yaml.
  reset does not remove R3: scripts/lab/cml_lab.py remove-r3 does.
EOF
}

# The one place a session name meets its script: "<script> [argument]". A run script's log is
# output/lab/<name without the platform>-<stamp>.log, because that is the name it gives lab_init.
session_script() {
  case $1 in
    probe) echo "probe.sh" ;;
    ospf-deadtimer) echo "run-ospf-deadtimer.sh" ;;
    ibgp) echo "run-ibgp.sh" ;;
    bgp-vrf) echo "run-bgp-vrf.sh" ;;
    ssh-path) echo "run-ssh-path.sh" ;;
    second-platform:*) echo "run-second-platform.sh ${1#second-platform:}" ;;
    reset) echo "labctl.py reset" ;;
    *) return 1 ;;
  esac
}

# What an exit status means, in the session table. Only exit 0 of a run with a prediction says
# the prediction held, and even then the table never calls it a match.
meaning() {
  case $1:$2 in
    probe:0) echo "the probe finished: read its three answers in its log" ;;
    probe:1) echo "the CML login or a console connection failed: read its log" ;;
    reset:0) echo "labctl.py reset sent R1 and R2 what they needed to return to the shipped configuration" ;;
    reset:*) echo "labctl.py reset failed ($2): read the lines above in this log" ;;
    ssh-path:0) echo "both comparisons gave exit 0: the two paths gave the same data" ;;
    *:0) echo "every comparison gave the predicted exit and the change comparison gave exactly the predicted findings" ;;
    *:3) echo "ran to the end, but a comparison or the findings differed from the prediction: read the report" ;;
    *:1) echo "stopped early" ;;
    *:2) echo "could not start" ;;
    *:4) echo "the management addresses do not answer in this sandbox (a result)" ;;
    *:interrupted) echo "interrupted by Ctrl-C" ;;
    *) echo "unexpected ($2)" ;;
  esac
}

names=("$@")
[ ${#names[@]} -gt 0 ] || names=(probe ospf-deadtimer ibgp bgp-vrf reset)
cd "$here/../.." || exit 2
py="${NCV_PYTHON:-.venv/bin/python}"

for name in "${names[@]}"; do
  if [ "$name" = -h ] || [ "$name" = --help ]; then usage; exit 0; fi
  if ! session_script "$name" >/dev/null; then
    echo "run-session.sh: unknown name: $name" >&2; usage; exit 2
  fi
  case $name in
    second-platform:*)
      "$py" "$here/cml_lab.py" platform-os "${name#second-platform:}" >/dev/null 2>&1
      case $? in
        0) ;;
        2) echo "run-session.sh: unknown platform in $name" >&2; usage; exit 2 ;;
        *) echo "run-session.sh: could not run scripts/lab/cml_lab.py; is the .venv set up?" >&2; exit 2 ;;
      esac
      ;;
  esac
done

lab_vpn_up
lab_logins
ssh_named=0
for name in "${names[@]}"; do [ "$name" != ssh-path ] || ssh_named=1; done
[ "$ssh_named" -eq 0 ] || lab_ssh_login

stamp="${NCV_STAMP:-$(date +%Y%m%d-%H%M)}"
log="output/lab/session-$stamp.log"
mkdir -p output/lab
step "session: ${names[*]}"
step "checking the CML login once (it is also the console server's login, so a wrong one fails every run)"
"$py" "$here/cml_lab.py" check-login 2>&1 | tee -a "$log"
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
  step "the CML login did not work (see the line above); nothing ran"
  exit 2
fi

rows=()  # one "<name>|<exit>|<log>" per run that finished

row_log() {  # <name> <n>: the run's own log, or this session's log for reset
  if [ "$1" = reset ]; then echo "$log"; else echo "output/lab/${1%%:*}-$stamp-$2.log"; fi
}

print_table() {
  local row name status runlog last
  echo "session $stamp: ${#rows[@]} of ${#names[@]} named runs ran"
  printf '%-27s %-5s %s\n' name exit meaning
  for row in "${rows[@]}"; do
    IFS='|' read -r name status runlog <<<"$row"
    printf '%-27s %-5s %s\n' "$name" "$status" "$(meaning "$name" "$status")"
    if [ "$status" = 1 ] && [ -f "$runlog" ] && [ "$name" != reset ]; then
      last=$(grep '^== ' "$runlog" | tail -n 1)
      printf '%-33s where it stopped: %s\n' "" "${last#== }"
    fi
    if [ -f "$runlog" ]; then
      printf '%-33s log: %s\n' "" "$runlog"
    else
      printf '%-33s log: none (%s stopped before writing one)\n' "" "$name"
    fi
  done
}

go_on_hint() {  # <index of the first name still to run>
  echo "to go on once the cause is fixed: bash scripts/lab/run-session.sh ${names[*]:$1}"
  echo "the next run's labctl.py reset clears whatever the stopped run left."
}

finish() {  # <session exit> [<index of the first name still to run>]
  print_table | tee -a "$log"
  [ $# -lt 2 ] || go_on_hint "$2" | tee -a "$log"
  if lab_log_holds_a_password; then
    step "a password value appears in $log; do not publish it"
  fi
  exit "$1"
}

on_interrupt() {
  rows+=("${names[current]}|interrupted|$(row_log "${names[current]}" "$((current + 1))")")
  step "interrupted during ${names[current]}"
  finish 130 "$current"
}

trap on_interrupt INT
failed=0
for current in "${!names[@]}"; do
  name=${names[current]}
  n=$((current + 1))
  read -r script argument <<<"$(session_script "$name")"
  step "$n/${#names[@]} $name: $script${argument:+ $argument}"
  if [ "$name" = reset ]; then
    "$py" "$here/$script" "$argument" 2>&1 | tee -a "$log"
    status=${PIPESTATUS[0]}
  else
    NCV_STAMP="$stamp-$n" bash "$here/$script" ${argument:+"$argument"}
    status=$?
  fi
  rows+=("$name|$status|$(row_log "$name" "$n")")
  [ "$status" -eq 0 ] || failed=1
  if [ "$status" -eq 2 ]; then
    step "$name could not start; every later run would fail the same way, so the session stops"
    finish 1 "$current"
  fi
  if [ "$name" = probe ] && [ "$status" -ne 0 ]; then
    step "the probe failed: the runs need the same CML login and console connection, so the session stops"
    finish 1 "$current"
  fi
done
trap - INT
step "session finished"
[ "$failed" -eq 0 ] && finish 0
finish 3
