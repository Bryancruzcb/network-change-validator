#!/usr/bin/env bash
# The second-platform run on the DevNet CML default-lab in one command. With iosv, this is the
# run recorded in fixtures/lab-2026-11-21/second-platform-iosv. An nxosv9000 attempt the same day
# stopped before any capture (fixtures/lab-2026-11-21/SOURCE.md describes it), and cat8000v has
# not run.
#
# Usage: run-second-platform.sh nxosv9000|cat8000v|iosv
#
# Until the iosv run, every capture came from one image, IOS XE on IOL. This run adds a third
# router, R3, on another platform, links it to R1's spare port Ethernet0/3, and breaks the link
# from R1's end: an adjacency lost and seen from both ends, one end on each platform. It tests
# ncv's adapter on a second platform's Genie data.
#
# scripts/lab/cml_lab.py add-r3 <platform> adds R3 through the CML API with a day-0
# configuration (OSPF on the link with a 1 s hello, eBGP AS 65003 to R1 with the hold-timer
# run's timers, and an admin login whose password is NCV_LAB_PASS), links it, and boots it; it
# refuses, changing nothing, when the platform has no image, when R1 Ethernet0/3 is in use, or
# when memory is plainly short. labctl.py configures R1's side only; R3 is never configured
# after its first boot. The run leaves R3 in the lab: scripts/lab/cml_lab.py remove-r3 takes it
# out, and `bash scripts/lab/run-session.sh remove-r3` runs it with the CML login asked for.
#
# Checks the platform against cml_lab.py's table and that the testbed (NCV_TESTBED, default
# testbeds/lab-r3.yaml, copied from testbeds/cml-console-r3.yaml.example) gives R3 that
# platform's pyATS os, both before asking for any login. Then: returns R1 and R2 to the shipped
# configuration, adds R3, sets up OSPF and eBGP between R1 and R2 and R1's side of the R3 link,
# waits until R1 sees R3 as its OSPF neighbor FULL and its BGP peer with a prefix learned, pre
# capture of all three routers, no-change check against the platform's intent
# (intent-second-platform-<platform>.yaml), then the change: `shutdown` on R1 Ethernet0/3. R1
# drops OSPF and BGP at once; R3, judged from R1 only, is given its 4 s dead interval and 9 s
# hold time as a fixed 15 s wait. Post capture and compare, `no shutdown`, wait for R3 again,
# restored capture and compare. The predicted findings of the change comparison are in
# expect-second-platform-<platform>.txt, beside the intent: in fixtures/lab-2026-11-21 for iosv,
# whose run is recorded, and in scripts/lab for nxosv9000 and cat8000v. scripts/lab/README.md
# explains them and lists the assumptions the attempts had to check, with what 2026-11-21 showed
# of each. The script exits 0 only when every comparison exits as predicted and the change
# comparison finds exactly those findings, 3 when it ran to the end but one did not, 1 when it
# stopped early, and 2 when it could not start.
# There is no packet capture: cml_capture.py captures the R1-R2 link only.
#
# Asks for the logins once, unless the NCV_* variables already hold them, so the passwords stay
# in this terminal. Captures go to captures/second-platform-<stamp>/, reports and the log to
# output/lab/. Run it from WSL or Linux with the sandbox VPN up.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/_lib.sh"
case ${1:-} in -h | --help) lab_print_header; exit 0 ;; esac
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
lab_r3_testbed_fits "$platform" "$r3_os" || exit 2

# A platform's intent and predicted findings sit next to its evidence once its run is recorded,
# and here in scripts/lab until then.
case $platform in
  iosv) files_dir=fixtures/lab-2026-11-21 ;;
  nxosv9000 | cat8000v) files_dir=scripts/lab ;;
  *) echo "$usage" >&2; exit 2 ;;
esac

lab_init second-platform
features=ospf,bgp,routing,interface
intent=$files_dir/intent-second-platform-$platform.yaml
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
[ "$rc" -eq 0 ] || { step "no-change check exited $rc, stopping before any change: the intent's strings probably differ from what $platform reports; compare $intent with $run/pre, then correct a draft intent and rerun (for iosv it is the recorded run's evidence: leave it as it is)"; exit 1; }
step "7/11 change: shutdown on R1 Ethernet0/3, the link to R3"
ctl r3-shut || { step "change failed; $undo_hint"; exit 1; }
step "8/11 wait until R1 has neither OSPF nor BGP with R3, then 15 s for R3's own 4 s dead interval and 9 s hold time (R3 is judged from R1 only)"
ctl wait-r3-down 60 || step "R1 still shows R3 FULL or Established, capturing anyway"
sleep 15
step "9/11 post capture and compare (expect exit 1)"
snap post || { step "post capture failed; R1 Ethernet0/3 is still shut down, $undo_hint"; exit 1; }
compare pre post change; expect_exit change 1 "$?"
expect_findings change "$out-change" "$files_dir/expect-second-platform-$platform.txt"
step "10/11 undo: no shutdown on R1 Ethernet0/3, then wait for R3 again"
ctl r3-noshut || { step "undo failed; $undo_hint"; exit 1; }
ctl wait-r3-up 300 || step "R3 is not back as R1 sees it, capturing anyway"
step "11/11 restored capture and compare (expect exit 0); R3 stays in the lab: bash scripts/lab/run-session.sh remove-r3 takes it out (it runs cml_lab.py remove-r3)"
snap restored || { step "restored capture failed"; exit 1; }
compare pre restored restored; expect_exit restored 0 "$?"
lab_finish
