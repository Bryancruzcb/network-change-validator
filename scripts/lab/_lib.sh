#!/usr/bin/env bash
# What the lab run scripts share. Sourced, not run: a new run script starts with
#
#   here=$(cd "$(dirname "$0")" && pwd)
#   . "$here/_lib.sh"
#   lab_init <run-name>
#   features=bgp,routing,interface
#   intent=scripts/lab/intent-<run>.yaml
#
# and ends with lab_finish. The four published runs (run-lab.sh, run-ospf.sh, run-bgp.sh,
# run-bgp-holdtimer.sh) keep their own copy of these lines: they reproduce recorded runs.
#
# lab_init <run-name>
#   cd to the repository root, refuse unless the sandbox VPN (tun0) is up, and prompt for
#   NCV_CML_USER (default developer), NCV_CML_PASS, and NCV_LAB_PASS only when the variable is
#   unset or empty, so a session script can ask once and run several runs. Sets py (NCV_PYTHON
#   or .venv/bin/python), testbed (NCV_TESTBED or testbeds/lab.yaml, exported so labctl.py
#   uses the same file), stamp, run=captures/<run-name>-<stamp>, out=output/lab/<run-name>-<stamp>,
#   log=$out.log, and unexpected=0, and creates the directories.
# step <text>                          a timestamped line on the terminal and in the log
# ctl <args>                           labctl.py, logged, returning its exit code
# cap <args>                           cml_capture.py, logged, returning its exit code
# snap <name>                          ncv snapshot of $features into $run/<name>, logged
# compare <before> <after> <label>     ncv diff of two captures against $intent, report in $out-<label>
#   The calling script sets features and intent before it calls snap or compare.
# expect_exit <label> <wanted> <got>
#   Logs "<label> exit=<got>"; when it is not the predicted exit, logs that too and sets
#   unexpected=1. Call it after each comparison: baseline 0, change 1, restored 0.
# lab_finish
#   Logs where the captures and reports are, then exits 0 when every comparison exited as
#   predicted and 3 when one did not, so a session script can tell a run that matched its
#   prediction from one that finished but did not. Exit 1 stays "stopped early" and exit 2
#   "could not start", as in the existing scripts.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "scripts/lab/_lib.sh is sourced by the run scripts; it does nothing on its own." >&2
  exit 2
fi
set -uo pipefail

lab_init() {
  local name=${1:?lab_init needs a run name} u p rp
  here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  cd "$here/../.." || exit 2
  ip -brief addr show tun0 >/dev/null 2>&1 || { echo "The sandbox VPN is not connected. Start openconnect first."; exit 2; }
  if [ -z "${NCV_CML_USER:-}" ]; then
    read -rp "CML username [developer]: " u; NCV_CML_USER="${u:-developer}"
  fi
  if [ -z "${NCV_CML_PASS:-}" ]; then
    read -rsp "CML password (the developer one): " p; echo; NCV_CML_PASS="$p"
  fi
  if [ -z "${NCV_LAB_PASS:-}" ]; then
    read -rsp "Router enable password (the cisco one): " rp; echo; NCV_LAB_PASS="$rp"
  fi
  export NCV_CML_USER NCV_CML_PASS NCV_LAB_PASS

  py="${NCV_PYTHON:-.venv/bin/python}"
  testbed="${NCV_TESTBED:-testbeds/lab.yaml}"
  export NCV_TESTBED="$testbed"
  stamp=$(date +%Y%m%d-%H%M)
  run="captures/$name-$stamp"
  out="output/lab/$name-$stamp"
  log="$out.log"
  unexpected=0
  mkdir -p "$run" output/lab
}

step() { echo "== $(date +%T) $*" | tee -a "$log"; }
ctl() { "$py" "$here/labctl.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
cap() { "$py" "$here/cml_capture.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
snap() {
  "$py" -m ncv snapshot --testbed "$testbed" --output "$run/$1" \
    --features "$features" --i-am-in-a-lab 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
compare() {
  "$py" -m ncv diff "$run/$1" "$run/$2" --intent "$intent" --report "$out-$3" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}

expect_exit() {
  local label=$1 wanted=$2 got=$3
  echo "$label exit=$got" | tee -a "$log"
  if [ "$got" != "$wanted" ]; then
    echo "$label: expected exit $wanted" | tee -a "$log"
    unexpected=1
  fi
}

lab_finish() {
  step "done: captures in $run, reports and log in output/lab/"
  if [ "$unexpected" -ne 0 ]; then
    step "the run finished, but a comparison did not exit as predicted"
    exit 3
  fi
  exit 0
}
