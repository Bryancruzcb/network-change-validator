#!/usr/bin/env bash
# The SSH path run on the DevNet CML default-lab in one command. Prepared, not run yet.
# On 2026-11-21 scripts/lab/probe.sh found that neither management address answers on port 22,
# and both routers report SSH disabled with no host keys, so the session did not start it.
#
# Every capture so far reached the routers through the CML console server. This captures them
# twice in a row, once that way and once over SSH to their management addresses, and tests one
# claim: the access path does not change the evidence. It changes nothing in the lab except
# `labctl.py reset`, which returns a used reservation to the shipped configuration.
#
#   1. Check that testbeds/lab-ssh.yaml exists (copy testbeds/cml-ssh.yaml.example), ask for the
#      logins, including the routers' SSH login, unless the NCV_* variables already hold them.
#   2. Port check: both management addresses, 10.10.20.171 and .172, must accept TCP port 22.
#      If not, the script exits 4: the management addresses do not answer in this sandbox. That
#      is a result about the sandbox, not an error in the script; scripts/lab/probe.sh records
#      the reasons it can see.
#   3. labctl.py reset, through the console testbed, so the routers carry the configuration the
#      published intent describes.
#   4. Capture `console` through testbeds/lab.yaml, with routing and interface.
#   5. Delete output/lab/known_hosts (a new reservation gives the routers new host keys, and a
#      changed key makes ssh refuse), then capture `ssh` through testbeds/lab-ssh.yaml.
#   6. scripts/lab/compare_captures.py on the two: predicted exit 0, the same data.
#   7. ncv diff of the two against fixtures/lab-2026-09-12/intent-routes.yaml, the intent of the
#      shipped lab: predicted exit 0.
#   Then `finish`: where the captures and reports are, and the exit status below.
#
# It exits 0 only when both comparisons exit 0, 3 when it ran to the end but one did not, 4 when
# the management addresses do not answer, 1 when it stopped early, and 2 when it could not
# start. Captures go to captures/ssh-path-<stamp>/, reports and the log to output/lab/. Run it
# from WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"
lab_takes_no_arguments "$@"
ssh_testbed=testbeds/lab-ssh.yaml
if [ ! -f "$here/../../$ssh_testbed" ]; then
  echo "$ssh_testbed is missing: copy testbeds/cml-ssh.yaml.example to it, and run scripts/lab/probe.sh first." >&2
  exit 2
fi
export NCV_TESTBED=testbeds/lab.yaml  # the console path: the reset and the first capture use it
lab_init ssh-path
lab_ssh_login
features=routing,interface
intent=fixtures/lab-2026-09-12/intent-routes.yaml

step "1/7 the logins are set; the SSH capture will use $ssh_testbed"
step "2/7 port check: both management addresses must accept TCP port 22"
open22=0
for address in 10.10.20.171 10.10.20.172; do
  lab_tcp "$address" 22 && open22=$((open22 + 1))
done
if [ "$open22" -ne 2 ]; then
  lab_not_reachable "result: the management addresses do not answer in this sandbox, so the console server stays the only path. This is not an error in the script; run scripts/lab/probe.sh to record why."
fi
step "3/7 reset both routers to the shipped configuration, through $testbed"
lab_reset
step "4/7 capture console through $testbed"
snap console || { step "console capture failed"; exit 1; }
step "5/7 capture ssh through $ssh_testbed, with a fresh output/lab/known_hosts"
rm -f output/lab/known_hosts
testbed=$ssh_testbed
snap ssh || { step "SSH capture failed: the port answered, but the login, the enable password, or the capture did not work; read the lines above"; exit 1; }
step "6/7 compare_captures.py console ssh (expect exit 0, the same data)"
"$py" "$here/compare_captures.py" "$run/console" "$run/ssh" 2>&1 | tee -a "$log"
expect_exit same-data 0 "${PIPESTATUS[0]}"
step "7/7 ncv diff console ssh against $intent (expect exit 0)"
compare console ssh access-path; expect_exit access-path 0 "$?"
step "finish"
lab_finish
