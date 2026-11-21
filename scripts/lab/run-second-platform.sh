#!/usr/bin/env bash
# The second-platform run on the DevNet CML default-lab in one command. Prepared, not run yet.
#
# Usage: run-second-platform.sh nxosv9000|cat8000v|iosv
#
# Every capture so far came from one image, IOS XE on IOL. This run adds a third router, R3, on
# another platform, links it to R1's spare port Ethernet0/3, and breaks the link from R1's end:
# an adjacency lost and seen from both ends, one end on each platform. It is the first test of
# ncv's adapter on a platform whose Genie data is shaped differently.
#
# scripts/lab/cml_lab.py add-r3 <platform> adds R3 through the CML API with a day-0
# configuration (OSPF on the link with a 1 s hello, eBGP AS 65003 to R1 with the hold-timer
# run's timers, and an admin login whose password is NCV_LAB_PASS), links it, and boots it; it
# refuses, changing nothing, when the platform has no image, when R1 Ethernet0/3 is in use, or
# when memory is plainly short. labctl.py configures R1's side only; R3 is never configured
# after its first boot. The run leaves R3 in the lab: scripts/lab/cml_lab.py remove-r3 takes it
# out.
#
# Checks the platform against cml_lab.py's table and that the testbed (NCV_TESTBED, default
# testbeds/lab-r3.yaml, copied from testbeds/cml-console-r3.yaml.example) gives R3 that
# platform's pyATS os, both before asking for any login. Then: returns R1 and R2 to the shipped
# configuration, adds R3, sets up OSPF and eBGP between R1 and R2 and R1's side of the R3 link,
# waits until R1 sees R3 as its OSPF neighbor FULL and its BGP peer with a prefix learned, pre
# capture of all three routers, no-change check against the platform's draft intent
# (scripts/lab/intent-second-platform-<platform>.yaml), then the change: `shutdown` on R1
# Ethernet0/3. R1 drops OSPF and BGP at once; R3, judged from R1 only, is given its 4 s dead
# interval and 9 s hold time as a fixed 15 s wait. Post capture and compare, `no shutdown`, wait
# for R3 again, restored capture and compare. The predicted findings of the change comparison
# are in scripts/lab/expect-second-platform-<platform>.txt, and scripts/lab/README.md explains
# them and lists every assumption the first session must check. The script exits 0 only when
# every comparison exits as predicted and the change comparison finds exactly those findings, 3
# when it ran to the end but one did not, 1 when it stopped early, and 2 when it could not start.
# There is no packet capture: cml_capture.py captures the R1-R2 link only.
#
# Asks for the logins once, unless the NCV_* variables already hold them, so the passwords stay
# in this terminal. Captures go to captures/second-platform-<stamp>/, reports and the log to
# output/lab/. Run it from WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
usage="usage: run-second-platform.sh nxosv9000|cat8000v|iosv"
platform=${1:-}
cd "$here/../.." || exit 2

# Refuse a platform cml_lab.py's table does not have, and a testbed whose R3 would be reached as
# another os, before any login is asked for or anything is reset.
r3_os=$("${NCV_PYTHON:-.venv/bin/python}" "$here/cml_lab.py" platform-os "$platform")
rc=$?
if [ "$rc" -eq 2 ]; then echo "$usage" >&2; exit 2; fi
[ "$rc" -eq 0 ] || { echo "could not run scripts/lab/cml_lab.py; is the .venv set up?" >&2; exit 2; }
export NCV_TESTBED="${NCV_TESTBED:-testbeds/lab-r3.yaml}"
if [ ! -f "$NCV_TESTBED" ]; then
  echo "$NCV_TESTBED is missing: copy testbeds/cml-console-r3.yaml.example to it, with R3's entry for $platform." >&2
  exit 2
fi
testbed_os=$(awk '/^  R3:/ { r3 = 1; next } r3 && /^  [^ ]/ { exit } r3 && /^    os:/ { print $2; exit }' "$NCV_TESTBED")
if [ "$testbed_os" != "$r3_os" ]; then
  echo "$NCV_TESTBED gives R3 os ${testbed_os:-none}, but $platform needs os $r3_os: use R3's entry for it from testbeds/cml-console-r3.yaml.example." >&2
  exit 2
fi

. "$here/_lib.sh"
lab_init second-platform
features=ospf,bgp,routing,interface
intent=scripts/lab/intent-second-platform-$platform.yaml
undo_hint="run scripts/lab/change.sh r3-undo, or let the next run's labctl.py reset remove it"
cml() { "$py" "$here/cml_lab.py" "$@" 2>&1 | tee -a "$log"; return "${PIPESTATUS[0]}"; }

step "1/11 reset R1 and R2 to the shipped configuration (a reused reservation may carry an earlier run)"
lab_reset
step "2/11 add R3 ($platform) to the lab, link it to R1 Ethernet0/3, and boot it (cml_lab.py add-r3, outside ncv)"
cml add-r3 "$platform" || { step "cml_lab.py add-r3 stopped; its last line says why and whether R3 was created"; exit 1; }
step "3/11 set up OSPF and eBGP between R1 and R2, then R1's side of the link to R3 (operator setup, outside ncv)"
ctl setup-ospf || { step "OSPF setup failed"; exit 1; }
ctl setup-bgp || { step "BGP setup failed"; exit 1; }
ctl setup-r3-link || { step "R1's side of the R3 link failed"; exit 1; }
step "4/11 wait until R1 sees R3 as its OSPF neighbor FULL and its BGP peer with a prefix learned"
ctl wait-r3-up 600 || { step "R3 never came up as R1 sees it, stopping before any capture; R1's line protocol and CDP above tell the link from R3's configuration"; exit 1; }
step "5/11 pre capture of R1, R2, and R3"
snap pre || { step "pre capture failed, nothing was changed; if R3 failed, check its console path and login, or which learn failed, against the README's assumptions"; exit 1; }
step "6/11 no-change check (must exit 0)"
compare pre pre baseline; rc=$?
expect_exit baseline 0 "$rc"
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change: the draft intent's strings probably differ from what $platform reports; correct $intent from $run/pre and rerun"; exit 1; }
step "7/11 change: shutdown on R1 Ethernet0/3, the link to R3"
ctl r3-shut || { step "change failed; $undo_hint"; exit 1; }
step "8/11 wait until R1 has neither OSPF nor BGP with R3, then 15 s for R3's own 4 s dead interval and 9 s hold time (R3 is judged from R1 only)"
ctl wait-r3-down 60 || step "R1 still shows R3 FULL or Established, capturing anyway"
sleep 15
step "9/11 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; R1 Ethernet0/3 is still shut down, $undo_hint"; exit 1; }
compare pre post change; expect_exit change 1 "$?"
expect_findings change "$out-change" "scripts/lab/expect-second-platform-$platform.txt"
step "10/11 undo: no shutdown on R1 Ethernet0/3, then wait for R3 again"
ctl r3-noshut || { step "undo failed; $undo_hint"; exit 1; }
ctl wait-r3-up 300 || step "R3 is not back as R1 sees it, capturing anyway"
step "11/11 restored capture and compare (expect exit 0); R3 stays in the lab, cml_lab.py remove-r3 takes it out"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; expect_exit restored 0 "$?"
lab_finish
