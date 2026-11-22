"""scripts/lab/_lib.sh, the helpers the newer run scripts share, run under bash.

Each test sources _lib.sh in a fresh bash and sets by hand the variables lab_init would set
(py, here, run, out, log, unexpected, capturing), so no VPN, testbed, or lab is needed and
lab_init itself is never called. Commands that would reach the lab (`ctl`, `cap`) are replaced
by shell functions that log what they were asked. The last tests run run-second-platform.sh
itself up to lab_init, with `ip` replaced so the VPN check fails, to pin the checks it makes
before asking for any login. The very last ones run run-session.sh from a copy of scripts/lab
whose run scripts are stand-ins that log how they were called and exit as a test tells them,
with an interpreter stand-in for labctl.py and cml_lab.py (only `platform-os` reaches the real
cml_lab.py, which reads its platform table without a login or a call). The module is skipped
on Windows, which has no dependable bash on PATH; the Ubuntu CI jobs run it.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs bash; Windows has no dependable bash on PATH",
)

LOGINS = ("NCV_CML_USER", "NCV_CML_PASS", "NCV_LAB_PASS", "NCV_SSH_USER", "NCV_SSH_PASS")
PRELUDE = """\
source "$T_LIB"
py=$T_PY here=$T_HERE run=$T_RUN out=$T_OUT log=$T_LOG unexpected=0 capturing=0
"""


def _bash(root, tmp_path, script, env=None, stdin="", trace=False):
    """Run `script` after sourcing _lib.sh; returns the completed process (text mode). The
    login variables are cleared unless `env` sets them, so the caller's shell cannot leak in."""
    run = tmp_path / "captures" / "run"
    run.mkdir(parents=True, exist_ok=True)
    base = {key: value for key, value in os.environ.items() if key not in LOGINS}
    base.update(
        T_LIB=str(root / "scripts" / "lab" / "_lib.sh"),
        T_PY=sys.executable,
        T_HERE=str(root / "scripts" / "lab"),
        T_RUN=str(run),
        T_OUT=str(tmp_path / "out"),
        T_LOG=str(tmp_path / "run.log"),
    )
    base.update(env or {})
    command = ["bash", "-x", "-c", PRELUDE + script] if trace else ["bash", "-c", PRELUDE + script]
    return subprocess.run(command, input=stdin, capture_output=True, text=True, env=base, timeout=60)


def _log(tmp_path):
    path = tmp_path / "run.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_expect_exit_logs_each_exit_and_flags_only_an_unpredicted_one(root, tmp_path):
    result = _bash(
        root,
        tmp_path,
        'expect_exit baseline 0 0; echo "u=$unexpected"; expect_exit change 1 0; echo "u=$unexpected"',
    )
    logged = ["baseline exit=0", "change exit=0", "change: expected exit 1"]
    assert result.stdout.splitlines() == [logged[0], "u=0", *logged[1:], "u=1"]
    assert _log(tmp_path).splitlines() == logged


PREDICTED = [("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"), ("V_ADJ", "R2", "ospf.neighbors.1.1.1.1")]


def _report_dir(tmp_path, findings):
    report = tmp_path / "out-change"
    report.mkdir()
    rows = [{"policy_id": p, "device": d, "path": path} for p, d, path in findings]
    (report / "report.json").write_text(json.dumps({"findings": rows}), encoding="utf-8")
    expect = tmp_path / "expect.txt"
    lines = [f"{p} {d} {path}\n" for p, d, path in PREDICTED]
    expect.write_text("# predicted\n" + "".join(lines), encoding="utf-8")
    return {"T_REPORT": str(report), "T_EXPECT": str(expect)}


CHECK = 'expect_findings change "$T_REPORT" "$T_EXPECT"; echo "u=$unexpected"'


def test_expect_findings_passes_when_the_change_found_exactly_the_predicted_findings(root, tmp_path):
    result = _bash(root, tmp_path, CHECK, _report_dir(tmp_path, PREDICTED))
    assert result.stdout.splitlines()[-1] == "u=0"
    assert "2 findings, as " in _log(tmp_path)


def test_expect_findings_flags_a_change_that_exited_1_with_other_findings(root, tmp_path):
    found = [PREDICTED[0], ("V_DRIFT", "R1", "config.running.must_absent")]
    result = _bash(root, tmp_path, CHECK, _report_dir(tmp_path, found))
    assert result.stdout.splitlines()[-1] == "u=1"
    log = _log(tmp_path)
    assert "missing: V_ADJ R2 ospf.neighbors.1.1.1.1" in log
    assert "unexpected: V_DRIFT R1 config.running.must_absent" in log
    assert f"change: findings are not the ones {tmp_path / 'expect.txt'} predicts" in log


def test_expect_findings_flags_a_report_that_was_never_written(root, tmp_path):
    env = _report_dir(tmp_path, PREDICTED)
    (tmp_path / "out-change" / "report.json").unlink()
    result = _bash(root, tmp_path, CHECK, env)
    assert result.stdout.splitlines()[-1] == "u=1"


@pytest.mark.parametrize(
    ("checks", "code"),
    [
        ("expect_exit baseline 0 0; expect_exit change 1 1; expect_exit restored 0 0", 0),
        ("expect_exit baseline 0 0; expect_exit change 1 0; expect_exit restored 0 0", 3),
        ('expect_exit change 1 1; expect_findings change "$T_REPORT" "$T_EXPECT"', 3),
    ],
)
def test_lab_finish_exits_0_only_when_every_check_passed_and_3_otherwise(root, tmp_path, checks, code):
    env = _report_dir(tmp_path, PREDICTED[:1])
    result = _bash(root, tmp_path, f"{checks}; lab_finish; echo not-reached", env)
    assert result.returncode == code
    assert "not-reached" not in result.stdout
    assert ("did not give the predicted exit or findings" in result.stdout) is (code == 3)


def test_lab_finish_warns_when_a_password_appears_in_the_log_and_never_prints_it(root, tmp_path):
    secret = "s3cr*t[x]?"  # glob characters must match only themselves
    (tmp_path / "run.log").write_text(f"login as developer with {secret}\n", encoding="utf-8")
    env = {"NCV_CML_PASS": secret, "NCV_LAB_PASS": ""}  # an empty password matches nothing
    result = _bash(root, tmp_path, "lab_finish", env, trace=True)
    assert result.returncode == 0
    assert f"a password value appears in {tmp_path / 'run.log'}; do not publish it" in result.stdout
    assert secret not in result.stdout + result.stderr


def test_lab_finish_says_nothing_about_passwords_the_log_does_not_hold(root, tmp_path):
    (tmp_path / "run.log").write_text("s3cr\nt\n", encoding="utf-8")
    env = {"NCV_CML_PASS": "s3cret", "NCV_LAB_PASS": "", "NCV_SSH_PASS": "s3cr*t"}
    result = _bash(root, tmp_path, "lab_finish", env)
    assert result.returncode == 0
    assert "password" not in result.stdout


def test_lab_ask_asks_again_until_a_password_is_given_exports_it_and_never_traces_it(root, tmp_path):
    script = 'lab_ask NCV_CML_PASS "CML password"; set +x; printenv NCV_CML_PASS'
    result = _bash(root, tmp_path, script, stdin="\n\nhunter2\n", trace=True)
    assert result.returncode == 0
    assert result.stdout == "hunter2\n"
    assert "hunter2" not in result.stderr


@pytest.mark.parametrize(("typed", "value"), [("\n", "developer"), ("alice\n", "alice")])
def test_lab_ask_takes_the_default_user_name_on_an_empty_answer(root, tmp_path, typed, value):
    script = 'lab_ask NCV_CML_USER "CML username" developer; printenv NCV_CML_USER'
    assert _bash(root, tmp_path, script, stdin=typed).stdout == f"{value}\n"


def test_lab_ask_does_not_ask_for_a_login_already_set_and_still_exports_it(root, tmp_path):
    script = 'NCV_LAB_PASS=kept; lab_ask NCV_LAB_PASS "Router enable password"; printenv NCV_LAB_PASS'
    result = _bash(root, tmp_path, script, stdin="")
    assert (result.returncode, result.stdout) == (0, "kept\n")


def test_lab_ask_stops_with_exit_2_when_the_input_closes_before_an_answer(root, tmp_path):
    result = _bash(root, tmp_path, 'lab_ask NCV_CML_PASS "CML password"; echo not-reached', stdin="\n")
    assert result.returncode == 2
    assert "no answer for NCV_CML_PASS: the input closed" in result.stderr
    assert "not-reached" not in result.stdout


def test_lab_ask_accepts_a_last_answer_with_no_trailing_newline(root, tmp_path):
    # read returns 1 at the end of input even when it read a value, as `printf secret |` gives.
    result = _bash(
        root, tmp_path, 'lab_ask NCV_CML_PASS "CML password"; printenv NCV_CML_PASS', stdin="secret"
    )
    assert (result.returncode, result.stdout) == (0, "secret\n")


def test_lab_ask_reads_a_password_without_echoing_it(root):
    # A pipe cannot show whether -s keeps the typed password off the screen, so read the text.
    text = (root / "scripts" / "lab" / "_lib.sh").read_text(encoding="utf-8")
    body = text[text.index("lab_ask() {") : text.index("\n}\n", text.index("lab_ask() {"))]
    no_default = body[body.index("    else\n") :]
    assert 'read -rsp "$prompt: " "$name"' in no_default


def test_lab_ssh_login_asks_for_the_ssh_user_with_cisco_as_default_and_the_password(root, tmp_path):
    script = "lab_ssh_login; printenv NCV_SSH_USER NCV_SSH_PASS"
    assert _bash(root, tmp_path, script, stdin="\nsecret\n").stdout == "cisco\nsecret\n"


# A stand-in for cml_capture.py: logs what it is asked, and on `stop` saves the published
# hold-timer capture as if CML had returned it.
FAKE_CAP = """\
cap() {
  echo "cap $*" >> "$log"
  [ "$1" != stop ] || cp "$T_PCAP" "$2"
  [ "${T_CAP_FAILS:-0}" != 1 ]
}
trap lab_cleanup EXIT
"""


def _pcap_env(root, **extra):
    return {"T_PCAP": str(root / "fixtures" / "lab-2026-11-20" / "bgp-holdtimer-pcap" / "link.pcap"), **extra}


def test_a_run_that_stops_early_stops_its_capture_on_the_way_out_and_keeps_its_exit(root, tmp_path):
    result = _bash(root, tmp_path, FAKE_CAP + 'cap_start "ip proto 89"; exit 1', _pcap_env(root))
    assert result.returncode == 1
    log = _log(tmp_path)
    assert "cap start --filter ip proto 89" in log
    assert "the run stopped with a packet capture running; stopping it" in log
    assert log.count(f"cap stop {tmp_path / 'captures' / 'run' / 'link.pcap'}") == 1
    summary = root / "fixtures" / "lab-2026-11-20" / "bgp-holdtimer-pcap" / "summary.txt"
    pcap_text = (tmp_path / "out-pcap.txt").read_text(encoding="utf-8")
    assert pcap_text.splitlines() == summary.read_text(encoding="utf-8").splitlines()


def test_a_capture_stopped_at_the_end_is_not_stopped_again_on_exit(root, tmp_path):
    result = _bash(root, tmp_path, FAKE_CAP + 'cap_start "ip proto 89"; cap_stop; exit 0', _pcap_env(root))
    assert result.returncode == 0
    log = _log(tmp_path)
    assert log.count("cap stop ") == 1
    assert "stopping it" not in log


# Each run script ends with cap_stop whether or not a capture started, so with none running it
# must do nothing: no call to cml_capture.py and no packet timeline.
NO_CAPTURE = FAKE_CAP + 'cap_start "tcp port 179"; echo "c=$capturing"; cap_stop; exit 1'


def test_ncv_pcap_0_skips_the_capture(root, tmp_path):
    result = _bash(root, tmp_path, NO_CAPTURE, _pcap_env(root, NCV_PCAP="0"))
    assert (result.returncode, result.stdout.splitlines()[-1]) == (1, "c=0")
    assert _log(tmp_path) == ""
    assert not (tmp_path / "out-pcap.txt").exists()


def test_a_capture_that_cannot_start_lets_the_run_go_on_with_nothing_to_stop(root, tmp_path):
    result = _bash(root, tmp_path, NO_CAPTURE, _pcap_env(root, T_CAP_FAILS="1"))
    assert (result.returncode, result.stdout.splitlines()[-1]) == (1, "c=0")
    log = _log(tmp_path)
    assert "cap start --filter tcp port 179" in log
    assert "no packet capture; the run goes on without one" in log
    assert "cap stop" not in log
    assert "packet capture: stop" not in log
    assert not (tmp_path / "out-pcap.txt").exists()


def test_lab_reset_stops_the_run_when_reset_fails(root, tmp_path):
    fake = 'ctl() { echo "ctl $*" >> "$log"; return "$T_CTL"; }\n'
    failed = _bash(root, tmp_path, fake + "lab_reset; echo setup", {"T_CTL": "1"})
    assert failed.returncode == 1
    assert "setup" not in failed.stdout
    assert "reset failed: the lab may still hold an earlier run's configuration" in _log(tmp_path)
    # labctl.py alone asks for no login, so the hint names the command that does
    assert _log(tmp_path).rstrip().endswith("then run bash scripts/lab/run-session.sh reset")
    passed = _bash(root, tmp_path, fake + "lab_reset; echo setup", {"T_CTL": "0"})
    assert (passed.returncode, passed.stdout.splitlines()[-1]) == (0, "setup")


@pytest.mark.parametrize(
    ("script", "message"),
    [
        ("intent=x; snap pre", "set features before snap"),
        ("features=bgp; snap pre", "set intent before compare"),
        ("features=bgp; compare pre post change", "set intent before compare"),
    ],
)
def test_snap_and_compare_refuse_to_start_without_features_and_intent(root, tmp_path, script, message):
    result = _bash(root, tmp_path, f"{script}; echo not-reached")
    assert result.returncode != 0
    assert message in result.stderr
    assert "not-reached" not in result.stdout


# What bash prints when connect() fails at once without a reset: no route on this machine, or an
# ICMP unreachable from a router on the way. Neither means the host answered.
UNREACHABLE = """\
timeout() {
  echo "bash: connect: $T_REASON" >&2
  echo "bash: line 1: /dev/tcp/192.0.2.1/22: $T_REASON" >&2
  return 1
}
"""


def test_lab_tcp_tells_open_refused_unreachable_and_no_answer_apart(root, tmp_path):
    with socket.socket() as listening, socket.socket() as unused:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        unused.bind(("127.0.0.1", 0))  # bound, never listening: a connect is refused
        opened, refused = listening.getsockname()[1], unused.getsockname()[1]
        script = (
            f'lab_tcp 127.0.0.1 {opened}; echo "rc=$?"; lab_tcp 127.0.0.1 {refused}; echo "rc=$?"; '
            + UNREACHABLE
            + 'lab_tcp 192.0.2.1 22; echo "rc=$?"; '
            + 'T_REASON="No route to host" lab_tcp 192.0.2.1 22; echo "rc=$?"; '
            # what timeout gives when the connect hangs: a filtered or unrouted address
            'timeout() { return 124; }; lab_tcp 192.0.2.1 22; echo "rc=$?"'
        )
        result = _bash(root, tmp_path, script, {"T_REASON": "Network is unreachable"})
    logged = [
        f"127.0.0.1 port {opened}: open",
        f"127.0.0.1 port {refused}: refused",
        "192.0.2.1 port 22: unreachable (Network is unreachable)",
        "192.0.2.1 port 22: unreachable (No route to host)",
        "192.0.2.1 port 22: no answer in 3 s",
    ]
    codes = ["rc=0", "rc=1", "rc=1", "rc=1", "rc=124"]
    assert result.stdout.splitlines() == [line for pair in zip(logged, codes, strict=True) for line in pair]
    assert _log(tmp_path).splitlines() == logged


def test_lab_not_reachable_logs_the_result_and_exits_4(root, tmp_path):
    result = _bash(
        root, tmp_path, 'lab_not_reachable "the management addresses do not answer"; echo not-reached'
    )
    assert result.returncode == 4
    assert "not-reached" not in result.stdout
    assert "the management addresses do not answer" in _log(tmp_path)


def _second_platform(root, tmp_path, platform, testbed):
    """run-second-platform.sh up to lab_init, with `ip` replaced by one that fails, so lab_init
    stops at its VPN check (exit 2) before it asks for anything or writes a file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_ip = bin_dir / "ip"
    fake_ip.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_ip.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key not in LOGINS}
    env.update(
        NCV_PYTHON=sys.executable, NCV_TESTBED=str(testbed), PATH=f"{bin_dir}{os.pathsep}{env['PATH']}"
    )
    script = root / "scripts" / "lab" / "run-second-platform.sh"
    command = ["bash", str(script), *([platform] if platform else [])]
    return subprocess.run(
        command, capture_output=True, text=True, env=env, timeout=60, stdin=subprocess.DEVNULL
    )


def _r3_testbed(root, tmp_path, r3_os=None):
    """The R3 testbed example, with R3's os changed when `r3_os` is given."""
    text = (root / "testbeds" / "cml-console-r3.yaml.example").read_text(encoding="utf-8")
    if r3_os:
        text = text.replace("  R3:\n    os: nxos\n", f"  R3:\n    os: {r3_os}\n")
    path = tmp_path / "lab-r3.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("platform", ["", "csr1000v"])
def test_the_second_platform_run_refuses_an_unknown_platform_before_anything_else(root, tmp_path, platform):
    result = _second_platform(root, tmp_path, platform, tmp_path / "absent.yaml")
    assert result.returncode == 2
    assert result.stderr == "usage: run-second-platform.sh nxosv9000|cat8000v|iosv\n"
    assert "VPN" not in result.stdout


def test_the_second_platform_run_refuses_a_missing_testbed_naming_the_example(root, tmp_path):
    result = _second_platform(root, tmp_path, "iosv", tmp_path / "absent.yaml")
    assert result.returncode == 2
    assert "absent.yaml is missing: copy testbeds/cml-console-r3.yaml.example to it" in result.stderr


@pytest.mark.parametrize(("platform", "r3_os"), [("iosv", None), ("nxosv9000", "iosxe"), ("cat8000v", "ios")])
def test_the_second_platform_run_refuses_a_testbed_whose_r3_has_another_os(root, tmp_path, platform, r3_os):
    result = _second_platform(root, tmp_path, platform, _r3_testbed(root, tmp_path, r3_os))
    assert result.returncode == 2
    assert f"gives R3 os {r3_os or 'nxos'}, but {platform} needs os " in result.stderr
    assert "VPN" not in result.stdout


@pytest.mark.parametrize(("platform", "r3_os"), [("nxosv9000", None), ("cat8000v", "iosxe"), ("iosv", "ios")])
def test_the_second_platform_run_goes_on_to_lab_init_when_the_testbed_fits(root, tmp_path, platform, r3_os):
    result = _second_platform(root, tmp_path, platform, _r3_testbed(root, tmp_path, r3_os))
    assert result.returncode == 2
    assert result.stderr == ""
    assert result.stdout == "The sandbox VPN is not connected. Start openconnect first.\n"


def test_lab_testbed_os_reads_one_devices_os_and_nothing_for_a_device_it_lacks(root, tmp_path):
    testbed = tmp_path / "tb.yaml"
    testbed.write_text(
        "devices:\n  R1:\n    type: router\n    os: iosxe\n  R3:\n    connections: {}\n  R4:\n    os: nxos\n",
        encoding="utf-8",
    )
    script = 'for d in R1 R3 R4 R9; do echo "$d=$(lab_testbed_os "$T_TB" "$d")"; done'
    result = _bash(root, tmp_path, script, {"T_TB": str(testbed)})
    assert result.stdout.splitlines() == ["R1=iosxe", "R3=", "R4=nxos", "R9="]


# Every script answers -h with its header and starts nothing: `ip` fails here, so a script that
# went on would print the VPN message, and stdin is closed, so one that prompted would show it.
NO_ARGUMENT_SCRIPTS = (
    "probe.sh",
    "run-ospf-deadtimer.sh",
    "run-ibgp.sh",
    "run-bgp-vrf.sh",
    "run-ssh-path.sh",
)


def _run_script(root, tmp_path, script, *arguments, relative=False):
    """Run a script from scripts/lab; `relative` runs it as `bash <script>` from that directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "ip").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bin_dir / "ip").chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key not in (*LOGINS, "NCV_TESTBED")}
    env.update(NCV_PYTHON=sys.executable, PATH=f"{bin_dir}{os.pathsep}{env['PATH']}")
    lab = root / "scripts" / "lab"
    command = ["bash", script if relative else str(lab / script), *arguments]
    return subprocess.run(
        command, capture_output=True, text=True, env=env, timeout=60, stdin=subprocess.DEVNULL, cwd=lab
    )


@pytest.mark.parametrize("script", [*NO_ARGUMENT_SCRIPTS, "run-second-platform.sh", "run-session.sh"])
@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_every_script_answers_h_with_its_header_and_starts_nothing(root, tmp_path, script, flag):
    result = _run_script(root, tmp_path, script, flag)
    header = (root / "scripts" / "lab" / script).read_text(encoding="utf-8").splitlines()[1]
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.splitlines()[0] == header.removeprefix("# ")
    assert "The sandbox VPN is not connected" not in result.stdout
    assert not any(line.startswith("#") for line in result.stdout.splitlines())
    assert "set -uo pipefail" not in result.stdout  # the header ends at the first line of code


@pytest.mark.parametrize("script", [*NO_ARGUMENT_SCRIPTS, "run-second-platform.sh", "run-session.sh"])
def test_h_finds_the_header_when_the_script_was_named_by_a_relative_path(root, tmp_path, script):
    # run-session.sh has changed to the repository root before it reads -h
    result = _run_script(root, tmp_path, script, "-h", relative=True)
    header = (root / "scripts" / "lab" / script).read_text(encoding="utf-8").splitlines()[1]
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.splitlines()[0] == header.removeprefix("# ")


@pytest.mark.parametrize("script", NO_ARGUMENT_SCRIPTS)
def test_a_script_that_takes_no_arguments_refuses_one_before_anything_else(root, tmp_path, script):
    result = _run_script(root, tmp_path, script, "ibgp")
    assert result.returncode == 2
    assert result.stderr == f"usage: {script} takes no arguments; -h prints what it does\n"
    assert result.stdout == ""


# run-session.sh: one login for a whole session. Each stand-in run script logs one line to
# $T_CALLS (its name, its arguments, its NCV_STAMP, and which logins it found set), writes two
# step lines to the log lab_init would give it, and exits with the code in $T_CODES/<name>. A
# stand-in told to fail first writes the steps lab_cleanup adds after the failing step when a
# packet capture was running, as a real run that stops early after cap_start does.
SESSION_RUNS = {
    "probe.sh": "probe",
    "run-ospf-deadtimer.sh": "ospf-deadtimer",
    "run-ibgp.sh": "ibgp",
    "run-bgp-vrf.sh": "bgp-vrf",
    "run-ssh-path.sh": "ssh-path",
    "run-second-platform.sh": "second-platform",
}
STAND_IN_RUN = """#!/usr/bin/env bash
set_logins="$NCV_CML_USER/${{NCV_CML_PASS:+set}}/${{NCV_LAB_PASS:+set}}/${{NCV_SSH_PASS:+set}}"
echo "{run} $* stamp=$NCV_STAMP logins=$set_logins" >> "$T_CALLS"
mkdir -p output/lab
log="output/lab/{run}-$NCV_STAMP.log"
printf '== 12:00:00 1/2 setup\\n== 12:00:01 2/2 the step it stopped at\\n' >> "$log"
[ ! -f "$T_CODES/{run}-interrupt" ] || kill -INT "$PPID"
if [ -f "$T_CODES/{run}" ]; then
  pcap="captures/{run}-$NCV_STAMP/link.pcap"
  printf '== 12:00:02 the run stopped with a packet capture running; stopping it\\n' >> "$log"
  printf '== 12:00:03 packet capture: stop and save %s\\n' "$pcap" >> "$log"
  printf '== 12:00:04 packet timeline of %s\\n' "$pcap" >> "$log"
  exit "$(cat "$T_CODES/{run}")"
fi
exit 0
"""
STAND_IN_PYTHON = """#!/usr/bin/env bash
script=$(basename "$1"); shift
echo "py $script $*" >> "$T_CALLS"
code() { if [ -f "$T_CODES/$1" ]; then exit "$(cat "$T_CODES/$1")"; fi; exit 0; }
case "$script $1" in
  "cml_lab.py platform-os") exec "$T_REAL_PY" "$T_REAL_LAB/cml_lab.py" "$@" ;;
  "cml_lab.py check-login") echo "the CML login was accepted"; code check-login ;;
  "labctl.py reset") echo "R1: nothing to reset"; code reset ;;
  "cml_lab.py remove-r3") echo "R3 is not in default-lab; nothing to remove"; code remove-r3 ;;
esac
exit 99
"""
TYPED = "\n\nfirst-secret\nenable-secret\n"  # the default CML user, an empty password, then both
SECRETS = ("first-secret", "enable-secret", "ssh-secret")
PREDICTED_EXITS_AND_FINDINGS = (
    "every comparison gave the predicted exit and the change comparison gave exactly the predicted findings"
)


def _session(root, tmp_path, names, codes=None, stdin=TYPED, trace=False, vpn=True, testbeds=None):
    """Run a copy of run-session.sh with stand-ins; returns (process, calls, session log).
    `testbeds` maps a file name to the text to put in the copy's testbeds/."""
    lab = tmp_path / "scripts" / "lab"
    lab.mkdir(parents=True)
    (tmp_path / "testbeds").mkdir()
    for name, text in (testbeds or {}).items():
        (tmp_path / "testbeds" / name).write_text(text, encoding="utf-8")
    for name in ("run-session.sh", "_lib.sh"):
        shutil.copy(root / "scripts" / "lab" / name, lab / name)
    for script, run in SESSION_RUNS.items():
        (lab / script).write_text(STAND_IN_RUN.format(run=run), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("ip", f"#!/bin/sh\nexit {0 if vpn else 1}\n"), ("python", STAND_IN_PYTHON)):
        (bin_dir / name).write_text(text, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    code_dir = tmp_path / "codes"
    code_dir.mkdir()
    for name, code in (codes or {}).items():
        (code_dir / name).write_text(str(code), encoding="utf-8")
    calls = tmp_path / "calls.txt"
    env = {key: value for key, value in os.environ.items() if key not in (*LOGINS, "NCV_TESTBED")}
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        NCV_PYTHON=str(bin_dir / "python"),
        NCV_STAMP="t",
        T_CALLS=str(calls),
        T_CODES=str(code_dir),
        T_REAL_PY=sys.executable,
        T_REAL_LAB=str(root / "scripts" / "lab"),
    )
    command = ["bash", *(["-x"] if trace else []), str(lab / "run-session.sh"), *names]
    result = subprocess.run(command, input=stdin, capture_output=True, text=True, env=env, timeout=60)
    session_log = tmp_path / "output" / "lab" / "session-t.log"
    logged = session_log.read_text(encoding="utf-8") if session_log.exists() else ""
    called = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, [line for line in called if "platform-os" not in line], logged


def _row(text, name, code):
    """The table line for one run: its name, its exit, and the meaning that follows them."""
    return next(line for line in text.splitlines() if line.split()[:2] == [name, str(code)])


@pytest.mark.parametrize(
    "names",
    [["frobnicate"], ["probe", "second-platform:csr1000v"], ["second-platform"], ["second-platform:"]],
)
def test_the_session_refuses_an_unknown_name_or_platform_before_any_prompt(root, tmp_path, names):
    result, calls, logged = _session(root, tmp_path, names)
    assert result.returncode == 2
    assert "usage: run-session.sh [name ...]" in result.stderr
    assert "password" not in result.stderr.lower()
    assert (calls, logged) == ([], "")


def test_the_session_asks_once_asks_again_for_an_empty_password_and_runs_the_default_order(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, [])
    assert result.returncode == 0
    # read shows no prompt when the input is not a terminal, but each hidden answer ends with a
    # newline on stderr: two for the CML password (the empty one, then the real one), one for
    # the enable password, and none for an SSH password nobody named a run for.
    assert result.stderr == "\n" * 3
    logins = "logins=developer/set/set/"
    assert calls == [
        "py cml_lab.py check-login",
        f"probe  stamp=t-1 {logins}",
        f"ospf-deadtimer  stamp=t-2 {logins}",
        f"ibgp  stamp=t-3 {logins}",
        f"bgp-vrf  stamp=t-4 {logins}",
        "py labctl.py reset",
    ]
    assert "the probe finished: read its three answers in its log" in _row(logged, "probe", 0)
    for name in ("ospf-deadtimer", "ibgp", "bgp-vrf"):
        assert _row(logged, name, 0).endswith(PREDICTED_EXITS_AND_FINDINGS)
    assert "log: output/lab/ibgp-t-3.log" in logged
    assert "log: output/lab/session-t.log" in logged  # reset's output is in the session log
    assert "R1: nothing to reset" in logged
    assert "matched" not in logged
    assert logged.split("session finished")[1] in result.stdout  # the table is on the screen too
    for secret in SECRETS:
        assert secret not in result.stdout + result.stderr + logged


def test_a_refused_cml_login_stops_the_session_before_any_run(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, [], {"check-login": 1})
    assert result.returncode == 2
    assert calls == ["py cml_lab.py check-login"]
    assert "the CML login did not work (see the line above); nothing ran" in logged


def test_the_session_refuses_to_start_without_the_vpn_before_any_prompt(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, [], vpn=False)
    assert (result.returncode, calls, logged) == (2, [], "")
    assert result.stdout == "The sandbox VPN is not connected. Start openconnect first.\n"
    assert "password" not in result.stderr.lower()


def _after(text, row):
    """The line under a table row."""
    lines = text.splitlines()
    return lines[lines.index(row) + 1].strip()


def test_a_run_that_stops_early_shows_where_and_the_session_goes_on(root, tmp_path):
    codes = {"ospf-deadtimer": 127, "ibgp": 1, "bgp-vrf": 3}
    result, calls, logged = _session(root, tmp_path, [], codes)
    assert result.returncode == 3
    assert [line.split()[0] for line in calls] == ["py", "probe", "ospf-deadtimer", "ibgp", "bgp-vrf", "py"]
    assert _row(logged, "ospf-deadtimer", 127).endswith("unexpected (127)")
    assert _row(logged, "ibgp", 1).endswith("stopped early")
    # the failed step, not the capture cleanup the stand-in wrote after it
    assert _after(logged, _row(logged, "ibgp", 1)) == "where it stopped: 12:00:01 2/2 the step it stopped at"
    assert _row(logged, "bgp-vrf", 3).endswith(
        "ran to the end, but a comparison or the findings differed from the prediction: read the report"
    )
    assert "to go on" not in logged


def test_the_session_stops_at_the_first_exit_2_and_prints_the_rest_as_a_command(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, [], {"ospf-deadtimer": 2})
    assert result.returncode == 1
    assert [line.split()[0] for line in calls] == ["py", "probe", "ospf-deadtimer"]
    assert _row(logged, "ospf-deadtimer", 2).endswith("could not start")
    command = "bash scripts/lab/run-session.sh ospf-deadtimer ibgp bgp-vrf reset"
    hint = f"to go on once the cause is fixed: {command}"
    for text in (result.stdout, logged):
        assert hint in text
        assert "the next run's labctl.py reset clears whatever the stopped run left." in text


def test_a_failed_probe_stops_the_session(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, [], {"probe": 1})
    assert result.returncode == 1
    assert [line.split()[0] for line in calls] == ["py", "probe"]
    assert _row(logged, "probe", 1).endswith("the CML login or a console connection failed: read its log")
    # the probe ran to its end, so it has no step it stopped at
    assert _after(logged, _row(logged, "probe", 1)) == "log: output/lab/probe-t-1.log"
    assert "where it stopped" not in logged
    assert "bash scripts/lab/run-session.sh probe ospf-deadtimer ibgp bgp-vrf reset" in logged


def _testbeds(root, r3_os="ios"):
    """The SSH testbed and the R3 testbed with R3's os set, as the session copy's testbeds/."""
    r3 = (root / "testbeds" / "cml-console-r3.yaml.example").read_text(encoding="utf-8")
    return {
        "lab-ssh.yaml": (root / "testbeds" / "cml-ssh.yaml.example").read_text(encoding="utf-8"),
        "lab-r3.yaml": r3.replace("  R3:\n    os: nxos\n", f"  R3:\n    os: {r3_os}\n"),
    }


def test_ssh_path_and_second_platform_get_what_they_need_and_exit_4_is_a_result(root, tmp_path):
    typed = "\nfirst-secret\nenable-secret\n\nssh-secret\n"  # the SSH user defaults to cisco
    names = ["ssh-path", "second-platform:iosv"]
    result, calls, logged = _session(
        root, tmp_path, names, {"ssh-path": 4}, stdin=typed, trace=True, testbeds=_testbeds(root)
    )
    assert result.returncode == 3
    assert calls[1:] == [
        "ssh-path  stamp=t-1 logins=developer/set/set/set",
        "second-platform iosv stamp=t-2 logins=developer/set/set/set",
    ]
    assert _row(logged, "ssh-path", 4).endswith(
        "the management addresses do not answer in this sandbox (a result)"
    )
    assert "log: output/lab/second-platform-t-2.log" in logged
    for secret in SECRETS:  # bash -x traced the whole session script
        assert secret not in result.stdout + result.stderr + logged


def test_ctrl_c_prints_the_table_so_far_and_the_command_to_go_on(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, [], {"ibgp-interrupt": 1})
    assert result.returncode == 130
    assert [line.split()[0] for line in calls] == ["py", "probe", "ospf-deadtimer", "ibgp"]
    assert _row(logged, "ospf-deadtimer", 0)
    assert _row(logged, "ibgp", "interrupted").endswith("interrupted by Ctrl-C")
    assert "bash scripts/lab/run-session.sh ibgp bgp-vrf reset" in result.stdout


@pytest.mark.parametrize(
    ("names", "missing", "message"),
    [
        (
            ["ospf-deadtimer", "ssh-path", "reset"],
            "lab-ssh.yaml",
            "testbeds/lab-ssh.yaml is missing: copy testbeds/cml-ssh.yaml.example to it",
        ),
        (
            ["ospf-deadtimer", "second-platform:iosv", "reset"],
            "lab-r3.yaml",
            "testbeds/lab-r3.yaml is missing: copy testbeds/cml-console-r3.yaml.example to it, "
            "with R3's entry for iosv.",
        ),
    ],
)
def test_the_session_refuses_a_missing_testbed_before_any_prompt(root, tmp_path, names, missing, message):
    testbeds = {name: text for name, text in _testbeds(root).items() if name != missing}
    result, calls, logged = _session(root, tmp_path, names, testbeds=testbeds)
    assert result.returncode == 2
    assert message in result.stderr
    assert (calls, logged) == ([], "")  # not even the runs named before it


def test_the_session_refuses_an_r3_testbed_of_another_platform_before_any_prompt(root, tmp_path):
    # the example ships R3 as nxos, while the README says to try iosv first
    names = ["second-platform:iosv", "reset"]
    result, calls, logged = _session(root, tmp_path, names, testbeds=_testbeds(root, r3_os="nxos"))
    assert result.returncode == 2
    assert "testbeds/lab-r3.yaml gives R3 os nxos, but iosv needs os ios: use R3's entry" in result.stderr
    assert (calls, logged) == ([], "")


def test_remove_r3_runs_cml_lab_py_into_the_session_log(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, ["remove-r3"])
    assert result.returncode == 0
    assert calls == ["py cml_lab.py check-login", "py cml_lab.py remove-r3"]
    assert _row(logged, "remove-r3", 0).endswith("R3 and its link are out of the lab, or were not there")
    assert "R3 is not in default-lab; nothing to remove" in logged
    assert _after(logged, _row(logged, "remove-r3", 0)) == "log: output/lab/session-t.log"


def test_a_failed_tool_says_which_tool_failed_and_has_no_step_it_stopped_at(root, tmp_path):
    result, calls, logged = _session(root, tmp_path, ["reset", "remove-r3"], {"reset": 1, "remove-r3": 1})
    assert result.returncode == 3  # a tool that fails does not stop the session
    assert calls[1:] == ["py labctl.py reset", "py cml_lab.py remove-r3"]
    assert _row(logged, "reset", 1).endswith("labctl.py reset failed (1): read the lines above in this log")
    failed = "cml_lab.py remove-r3 failed (1): read the lines above in this log"
    assert _row(logged, "remove-r3", 1).endswith(failed)
    assert "where it stopped" not in logged
