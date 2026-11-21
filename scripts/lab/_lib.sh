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
#   cd to the repository root, refuse with exit 2 unless the sandbox VPN (tun0) is up and the
#   testbed file exists (naming the example to copy), then ask for each login that is unset or
#   empty: NCV_CML_USER (default developer), NCV_CML_PASS, and NCV_LAB_PASS, plus NCV_SSH_USER
#   (default cisco) and NCV_SSH_PASS when the testbed mentions NCV_SSH_PASS. So run-session.sh
#   can ask once and run several runs. Sets py (NCV_PYTHON or .venv/bin/python), testbed
#   (NCV_TESTBED or testbeds/lab.yaml, exported so labctl.py uses the same file), stamp
#   (NCV_STAMP, or the time to the minute), run=captures/<run-name>-<stamp>,
#   out=output/lab/<run-name>-<stamp>, log=$out.log, unexpected=0, and capturing=0, creates the
#   directories, and installs `trap lab_cleanup EXIT`.
#   These variables are globals on purpose: the helpers below read them, so lab_init assigns
#   them plainly and must never declare them `local`.
# lab_ask <variable> <prompt> [default]
#   Asks for one login until it is non-empty, unless it already is, and exports it. With a
#   default (the user names) the answer shows and an empty one takes the default; without one
#   (the passwords) nothing is echoed. It reads straight into the variable and tests it with
#   ${!name:+x}, so `bash -x` never prints a value. Closed input with nothing typed is exit 2,
#   not an endless prompt.
# lab_vpn_up                           refuse with exit 2 unless the sandbox VPN (tun0) is up
# lab_logins                           lab_ask for NCV_CML_USER, NCV_CML_PASS, and NCV_LAB_PASS
# lab_ssh_login                        lab_ask for NCV_SSH_USER (default cisco) and NCV_SSH_PASS
# lab_tcp <host> <port>
#   A TCP connect test with a 3 s timeout. Logs "<host> port <port>: open", "refused", or
#   "no answer in 3 s" and returns 0, 1, or 124. A refusal means the host answered; no answer
#   means the packets were filtered or not routed. Which of the two it is was the question the
#   2026-09-12 attempt to reach the management addresses left open.
# step <text>                          a timestamped line on the terminal and in the log
# ctl <args>                           labctl.py, logged, returning its exit code
# cap <args>                           cml_capture.py, logged, returning its exit code
# snap <name>                          ncv snapshot of $features into $run/<name>, logged
# compare <before> <after> <label>     ncv diff of two captures against $intent, report in $out-<label>
#   The calling script sets features and intent before it calls snap or compare; both refuse
#   to start without them.
# lab_reset
#   labctl.py reset; when it fails, says the lab may still hold an earlier run's configuration
#   and exits 1, before any setup meets what the earlier run left.
# cap_start <filter>
#   Starts a packet capture of the R1-R2 link with that filter and sets capturing=1. NCV_PCAP=0
#   skips it; when it cannot start, the run goes on without one.
# cap_stop
#   When a capture is running: saves it as $run/link.pcap, sets capturing=0, and prints
#   link_pcap.py's reading of it to $out-pcap.txt and the log.
# lab_cleanup
#   The EXIT trap: stops a capture that is still running, so a run that stops early never
#   leaves one running on the link for the next run to trip over.
# expect_exit <label> <wanted> <got>
#   Logs "<label> exit=<got>"; when it is not the predicted exit, logs that too and sets
#   unexpected=1. Call it after each comparison: baseline 0, change 1, restored 0.
# expect_findings <label> <report dir> <expected file>
#   Runs check_findings.py on <report dir>/report.json and the expected file, logs what it
#   prints, and sets unexpected=1 unless the findings are exactly the predicted ones. An exit
#   code alone cannot say that: a change comparison exits 1 whatever it found.
# lab_finish
#   Logs where the captures and reports are and warns, without printing it, when a password
#   value appears in the log. Then exits 0 when every expect_exit and expect_findings passed,
#   and 3 when one did not, so run-session.sh can tell a run whose exits and findings came out
#   as predicted from one that finished but did not. Exit 1 stays "stopped early" and exit 2 "could not
#   start", as in the existing scripts.
# lab_not_reachable <text>
#   Logs the text and exits 4: a run whose devices do not answer on the path it tests
#   (run-ssh-path.sh when the management addresses refuse or ignore port 22). That is a
#   result about the sandbox, recorded before anything is captured or changed, not a run that
#   stopped early, so a session table must not report it as exit 1 would be.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "scripts/lab/_lib.sh is sourced by the run scripts; it does nothing on its own." >&2
  exit 2
fi
set -uo pipefail

lab_ask() {
  local name=$1 prompt=$2 default=${3:-}
  while [ -z "${!name:+x}" ]; do
    if [ -n "$default" ]; then
      if ! read -rp "$prompt [$default]: " "$name" && [ -z "${!name:+x}" ]; then
        echo >&2; echo "no answer for $name: the input closed" >&2; exit 2
      fi
      [ -n "${!name:+x}" ] || printf -v "$name" '%s' "$default"
    else
      if ! read -rsp "$prompt: " "$name" && [ -z "${!name:+x}" ]; then
        echo >&2; echo "no answer for $name: the input closed" >&2; exit 2
      fi
      echo >&2
    fi
  done
  export "$name"
}

lab_vpn_up() {
  ip -brief addr show tun0 >/dev/null 2>&1 || { echo "The sandbox VPN is not connected. Start openconnect first."; exit 2; }
}

lab_logins() {
  lab_ask NCV_CML_USER "CML username" developer
  lab_ask NCV_CML_PASS "CML password (the developer one)"
  lab_ask NCV_LAB_PASS "Router enable password (the cisco one)"
}

lab_ssh_login() {
  lab_ask NCV_SSH_USER "Router SSH username" cisco
  lab_ask NCV_SSH_PASS "Router SSH password"
}

lab_init() {
  local name=${1:?lab_init needs a run name}
  here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  cd "$here/../.." || exit 2
  lab_vpn_up
  testbed="${NCV_TESTBED:-testbeds/lab.yaml}"
  if [ ! -f "$testbed" ]; then
    if [ "$testbed" = testbeds/lab.yaml ]; then
      echo "testbeds/lab.yaml is missing: copy testbeds/cml-console.yaml.example to it and adjust it if the lab differs." >&2
    else
      echo "$testbed, which NCV_TESTBED names, is missing." >&2
    fi
    exit 2
  fi
  export NCV_TESTBED="$testbed"
  lab_logins
  if grep -q NCV_SSH_PASS "$testbed"; then lab_ssh_login; fi

  py="${NCV_PYTHON:-.venv/bin/python}"
  stamp="${NCV_STAMP:-$(date +%Y%m%d-%H%M)}"
  run="captures/$name-$stamp"
  out="output/lab/$name-$stamp"
  log="$out.log"
  unexpected=0
  capturing=0
  mkdir -p "$run" output/lab
  trap lab_cleanup EXIT
}

step() { echo "== $(date +%T) $*" | tee -a "$log"; }
ctl() { "$py" "$here/labctl.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
cap() { "$py" "$here/cml_capture.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }
snap() {
  : "${features:?set features before snap}" "${intent:?set intent before compare}"
  "$py" -m ncv snapshot --testbed "$testbed" --output "$run/$1" \
    --features "$features" --i-am-in-a-lab 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
compare() {
  : "${features:?set features before snap}" "${intent:?set intent before compare}"
  "$py" -m ncv diff "$run/$1" "$run/$2" --intent "$intent" --report "$out-$3" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}

lab_tcp() {
  local host=$1 port=$2 rc outcome
  timeout 3 bash -c "</dev/tcp/$host/$port" 2>/dev/null
  rc=$?
  case $rc in
    0) outcome=open ;;
    124) outcome="no answer in 3 s" ;;
    *) outcome=refused; rc=1 ;;
  esac
  echo "$host port $port: $outcome" | tee -a "$log"
  return "$rc"
}

lab_not_reachable() {
  step "$*"
  exit 4
}

lab_reset() {
  ctl reset && return 0
  step "reset failed: the lab may still hold an earlier run's configuration; read the lines above, then run labctl.py reset again"
  exit 1
}

cap_start() {
  local filter=${1:?cap_start needs a capture filter}
  [ "${NCV_PCAP:-1}" != 0 ] || return 0
  step "packet capture: start capturing $filter on the R1-R2 link through the CML API"
  if cap start --filter "$filter"; then
    capturing=1
  else
    step "no packet capture; the run goes on without one"
  fi
}

cap_stop() {
  [ "$capturing" -eq 1 ] || return 0
  capturing=0
  step "packet capture: stop and save $run/link.pcap"
  cap stop "$run/link.pcap" || step "could not save the packet capture"
  if [ -f "$run/link.pcap" ]; then
    step "packet timeline of $run/link.pcap"
    "$py" "$here/link_pcap.py" "$run/link.pcap" 2>&1 | tee "$out-pcap.txt" | tee -a "$log"
  fi
}

lab_cleanup() {
  if [ "${capturing:-0}" -eq 1 ]; then
    step "the run stopped with a packet capture running; stopping it"
    cap_stop
  fi
}

expect_exit() {
  local label=$1 wanted=$2 got=$3
  echo "$label exit=$got" | tee -a "$log"
  if [ "$got" != "$wanted" ]; then
    echo "$label: expected exit $wanted" | tee -a "$log"
    unexpected=1
  fi
}

expect_findings() {
  local label=$1 report=$2 expected=$3 rc
  "$py" "$here/check_findings.py" "$report/report.json" "$expected" 2>&1 | tee -a "$log"
  rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    echo "$label: findings are not the ones $expected predicts" | tee -a "$log"
    unexpected=1
  fi
}

# True when the value of a non-empty password variable appears in the log. Shell builtins
# only, so no external command carries a password in its arguments, and with tracing off, so
# `bash -x` does not print the value either.
lab_log_holds_a_password() {
  local - name text
  set +x
  [ -f "$log" ] || return 1
  text=$(<"$log")
  for name in NCV_CML_PASS NCV_LAB_PASS NCV_SSH_PASS; do
    [ -n "${!name:+x}" ] || continue
    case $text in *"${!name}"*) return 0 ;; esac
  done
  return 1
}

lab_finish() {
  step "done: captures in $run, reports and log in output/lab/"
  if lab_log_holds_a_password; then
    step "a password value appears in $log; do not publish it"
  fi
  if [ "$unexpected" -ne 0 ]; then
    step "the run finished, but a comparison did not give the predicted exit or findings"
    exit 3
  fi
  exit 0
}
