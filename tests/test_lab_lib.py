"""scripts/lab/_lib.sh, the helpers the prepared run scripts share, run under bash.

Each test sources _lib.sh in a fresh bash and sets by hand the variables lab_init would set
(py, here, run, out, log, unexpected, capturing), so no VPN, testbed, or lab is needed and
lab_init itself is never called. Commands that would reach the lab (`ctl`, `cap`) are replaced
by shell functions that log what they were asked. The last tests run run-second-platform.sh
itself up to lab_init, with `ip` replaced so the VPN check fails, to pin the checks it makes
before asking for any login. The module is skipped on Windows, which has
no dependable bash on PATH; the Ubuntu CI jobs run it.
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


NO_CAPTURE = FAKE_CAP + 'cap_start "tcp port 179"; echo "c=$capturing"; exit 1'


def test_ncv_pcap_0_skips_the_capture(root, tmp_path):
    result = _bash(root, tmp_path, NO_CAPTURE, _pcap_env(root, NCV_PCAP="0"))
    assert (result.returncode, result.stdout.splitlines()[-1]) == (1, "c=0")
    assert _log(tmp_path) == ""


def test_a_capture_that_cannot_start_lets_the_run_go_on_with_nothing_to_stop(root, tmp_path):
    result = _bash(root, tmp_path, NO_CAPTURE, _pcap_env(root, T_CAP_FAILS="1"))
    assert (result.returncode, result.stdout.splitlines()[-1]) == (1, "c=0")
    log = _log(tmp_path)
    assert "cap start --filter tcp port 179" in log
    assert "no packet capture; the run goes on without one" in log
    assert "cap stop" not in log


def test_lab_reset_stops_the_run_when_reset_fails(root, tmp_path):
    fake = 'ctl() { echo "ctl $*" >> "$log"; return "$T_CTL"; }\n'
    failed = _bash(root, tmp_path, fake + "lab_reset; echo setup", {"T_CTL": "1"})
    assert failed.returncode == 1
    assert "setup" not in failed.stdout
    assert "reset failed: the lab may still hold an earlier run's configuration" in _log(tmp_path)
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


def test_lab_tcp_tells_open_refused_and_no_answer_apart(root, tmp_path):
    with socket.socket() as listening, socket.socket() as unused:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        unused.bind(("127.0.0.1", 0))  # bound, never listening: a connect is refused
        opened, refused = listening.getsockname()[1], unused.getsockname()[1]
        script = (
            f'lab_tcp 127.0.0.1 {opened}; echo "rc=$?"; lab_tcp 127.0.0.1 {refused}; echo "rc=$?"; '
            # what timeout gives when the connect hangs: a filtered or unrouted address
            'timeout() { return 124; }; lab_tcp 192.0.2.1 22; echo "rc=$?"'
        )
        result = _bash(root, tmp_path, script)
    logged = [
        f"127.0.0.1 port {opened}: open",
        f"127.0.0.1 port {refused}: refused",
        "192.0.2.1 port 22: no answer in 3 s",
    ]
    assert result.stdout.splitlines() == [logged[0], "rc=0", logged[1], "rc=1", logged[2], "rc=124"]
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
