"""scripts/lab/labctl.py's commands, run through main() against a fake lab.

The lab is reachable only during a reservation, so a typo in a command would otherwise be
found there. Each test replaces load_testbed with a fake testbed whose R1 and R2 record what
they were sent and answer show commands from a table the test gives; a show command the test
did not expect fails it. The clock is replaced too, so the waits never sleep.
"""

from __future__ import annotations

import re
import sys
from types import SimpleNamespace

import pytest
from test_lab_scripts import NEIGHBOR_FAST_TIMERS, NEIGHBOR_STALE_TIMERS, _load_script, _running


class FakeDevice:
    def __init__(self, name, answers, log, fail_on=None):
        self.name, self.answers, self.log, self.fail_on = name, answers, log, fail_on
        self.configured: list[list[str]] = []
        self.executed: list[str] = []

    def connect(self, **kwargs):
        self.log.append((self.name, "connect"))

    def disconnect(self):
        self.log.append((self.name, "disconnect"))

    def configure(self, lines):
        if self.fail_on == "configure":
            raise RuntimeError(f"{self.name} refused the configuration")
        self.configured.append(list(lines))

    def execute(self, command):
        if self.fail_on == "execute":
            raise RuntimeError(f"{self.name} dropped the connection")
        if command not in self.answers:
            pytest.fail(f"{self.name} was sent {command!r}, which this test has no answer for")
        self.executed.append(command)
        return self.answers[command]


class FakeClock:
    """Stands in for the time module inside labctl: sleeping moves the clock, not the test."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def strftime(self, fmt):
        return "00:00:00"


@pytest.fixture
def labctl(root, monkeypatch):
    module = _load_script(root, "labctl.py")
    monkeypatch.setattr(module, "time", FakeClock())
    monkeypatch.delenv("NCV_TESTBED", raising=False)
    return module


def _run(labctl, monkeypatch, argv, answers=None, fail_on=None):
    """main(argv) on a fake R1 and R2; checks every device connected was disconnected."""
    answers = answers or {}
    log: list[tuple[str, str]] = []
    devices = {
        name: FakeDevice(name, answers.get(name, {}), log, fail_on.get(name) if fail_on else None)
        for name in ("R1", "R2")
    }
    loaded = []

    def load_testbed(path):
        loaded.append(path)
        return SimpleNamespace(devices=devices)

    monkeypatch.setattr(labctl, "load_testbed", load_testbed)
    try:
        code = labctl.main(["labctl.py", *argv])
    finally:
        for name in devices:
            assert log.count((name, "connect")) == log.count((name, "disconnect")), log
    assert loaded == [labctl.testbed_path({})]
    return code, devices


INTERFACE_BRIEF = "show ip interface brief"
BGP_SUMMARY = "show bgp ipv4 unicast summary"
SHOWS = {name: {INTERFACE_BRIEF: "Interface  IP-Address  Status", BGP_SUMMARY: ""} for name in ("R1", "R2")}

# command -> (the configure calls each router gets, built from labctl, and the show it prints after)
CONFIGURE_COMMANDS = {
    "setup-ospf": (lambda m: {"R1": [m.ospf_setup_lines("R1")], "R2": [m.ospf_setup_lines("R2")]}, None),
    "shut": (lambda m: {"R1": [["interface Ethernet0/1", "shutdown"]], "R2": []}, INTERFACE_BRIEF),
    "noshut": (lambda m: {"R1": [["interface Ethernet0/1", "no shutdown"]], "R2": []}, INTERFACE_BRIEF),
    "setup-bgp": (lambda m: {"R1": [m.bgp_setup_lines("R1")], "R2": [m.bgp_setup_lines("R2")]}, None),
    "bgp-shut": (
        lambda m: {"R1": [["router bgp 65001", "neighbor 1.1.1.2 shutdown"]], "R2": []},
        BGP_SUMMARY,
    ),
    "bgp-noshut": (
        lambda m: {"R1": [["router bgp 65001", "no neighbor 1.1.1.2 shutdown"]], "R2": []},
        BGP_SUMMARY,
    ),
    "setup-bgp-fast": (
        lambda m: {
            "R1": [m.bgp_setup_lines("R1", m.FAST_TIMERS)],
            "R2": [m.bgp_setup_lines("R2", m.FAST_TIMERS)],
        },
        None,
    ),
    "bgp-block": (lambda m: {"R1": [m.bgp_block_lines()], "R2": []}, BGP_SUMMARY),
    "bgp-unblock": (lambda m: {"R1": [m.bgp_unblock_lines()], "R2": []}, BGP_SUMMARY),
}


@pytest.mark.parametrize("command", CONFIGURE_COMMANDS)
def test_each_change_command_sends_its_lines_to_its_router(labctl, monkeypatch, command):
    expected, show = CONFIGURE_COMMANDS[command]
    code, devices = _run(labctl, monkeypatch, [command], SHOWS)
    assert code == 0
    assert {name: dev.configured for name, dev in devices.items()} == expected(labctl)
    shown = {name: dev.executed for name, dev in devices.items()}
    assert shown == {"R1": [show] if show else [], "R2": []}


OSPF = "show ip ospf neighbor"
OSPF_HEADER = "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
OSPF_FULL = {
    "R1": OSPF_HEADER + "2.2.2.2           1   FULL/DR         00:00:35    1.1.1.2         Ethernet0/1\n",
    "R2": OSPF_HEADER + "1.1.1.1           1   FULL/BDR        00:00:33    1.1.1.1         Ethernet0/1\n",
}
OSPF_GONE = {"R1": OSPF_HEADER, "R2": OSPF_HEADER}
BGP_HEADER = "Neighbor     V    AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down  State/PfxRcd\n"
BGP_UP = {
    "R1": BGP_HEADER + "1.1.1.2      4 65002      15      15      3   0    0 00:10:12        1\n",
    "R2": BGP_HEADER + "1.1.1.1      4 65001      15      15      3   0    0 00:10:12        1\n",
}
BGP_DOWN = {
    "R1": BGP_HEADER + "1.1.1.2      4 65002       0       0      1   0    0 never    Idle (Admin)\n",
    "R2": BGP_HEADER + "1.1.1.1      4 65001       0       0      1   0    0 00:00:03 Active\n",
}

# command -> (the show it polls, output that satisfies it, output that never does)
WAIT_COMMANDS = {
    "wait-full": (OSPF, OSPF_FULL, OSPF_GONE),
    "wait-gone": (OSPF, OSPF_GONE, OSPF_FULL),
    "wait-bgp-up": (BGP_SUMMARY, BGP_UP, BGP_DOWN),
    "wait-bgp-down": (BGP_SUMMARY, BGP_DOWN, BGP_UP),
}


def _answers(show, outputs):
    return {name: {show: output} for name, output in outputs.items()}


@pytest.mark.parametrize("command", WAIT_COMMANDS)
def test_a_wait_that_is_already_satisfied_returns_on_the_first_poll(labctl, monkeypatch, command):
    show, satisfied, _ = WAIT_COMMANDS[command]
    code, devices = _run(labctl, monkeypatch, [command], _answers(show, satisfied))
    assert code == 0
    assert {name: dev.executed for name, dev in devices.items()} == {"R1": [show], "R2": [show]}
    assert labctl.time.sleeps == []
    assert all(dev.configured == [] for dev in devices.values())


@pytest.mark.parametrize("command", WAIT_COMMANDS)
def test_a_wait_that_never_comes_true_times_out_with_exit_1(labctl, monkeypatch, capsys, command):
    show, _, never = WAIT_COMMANDS[command]
    code, devices = _run(labctl, monkeypatch, [command, "0"], _answers(show, never))
    assert code == 1
    assert "timed out waiting for" in capsys.readouterr().out
    assert labctl.time.sleeps == [5]
    assert all(dev.configured == [] for dev in devices.values())


def _neighbors(r1_output, r2_output):
    return {
        "R1": {"show bgp ipv4 unicast neighbors 1.1.1.2": r1_output},
        "R2": {"show bgp ipv4 unicast neighbors 1.1.1.1": r2_output},
    }


def test_check_hold_time_passes_only_when_both_sessions_run_the_fast_timers(labctl, monkeypatch):
    fast = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_FAST_TIMERS)
    assert _run(labctl, monkeypatch, ["check-hold-time"], fast)[0] == 0
    stale = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_STALE_TIMERS)
    assert _run(labctl, monkeypatch, ["check-hold-time"], stale)[0] == 1


def test_reset_configures_only_the_router_that_needs_it(root, labctl, monkeypatch, capsys):
    dirty = _running(root, "lab-2026-11-20/bgp-holdtimer/post", "R1")
    clean = _running(root, "lab-2026-09-12/routes/pre", "R2")
    answers = {"R1": {"show running-config": dirty}, "R2": {"show running-config": clean}}
    code, devices = _run(labctl, monkeypatch, ["reset"], answers)
    assert code == 0
    assert devices["R1"].configured == [labctl.reset_lines(dirty)]
    assert devices["R1"].configured[0][-1] == "no router bgp 65001"
    assert devices["R2"].configured == []
    assert "R2: nothing to reset" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv, answers, fail_on",
    [
        (["shut"], SHOWS, {"R1": "configure"}),
        (["setup-bgp"], {}, {"R2": "configure"}),
        (["wait-bgp-up"], {}, {"R1": "execute"}),
        (["check-hold-time"], _neighbors(NEIGHBOR_FAST_TIMERS, ""), {"R2": "execute"}),
        (["reset"], {"R1": {"show running-config": ""}}, {"R2": "execute"}),
    ],
)
def test_a_command_that_raises_still_disconnects_every_router_it_reached(
    labctl, monkeypatch, argv, answers, fail_on
):
    # _run asserts every connect was matched by a disconnect, even as the error propagates.
    with pytest.raises(RuntimeError):
        _run(labctl, monkeypatch, argv, answers, fail_on)


def test_every_command_in_the_table_is_exercised_here(labctl):
    covered = set(CONFIGURE_COMMANDS) | set(WAIT_COMMANDS) | {"check-hold-time", "reset"}
    assert covered == set(labctl.COMMANDS)


def test_usage_is_the_old_text_with_reset_added(labctl):
    assert labctl.USAGE == (
        "usage: labctl.py setup-ospf | shut | noshut | wait-full [seconds] | wait-gone [seconds]"
        " | setup-bgp | bgp-shut | bgp-noshut | wait-bgp-up [seconds] | wait-bgp-down [seconds]"
        " | setup-bgp-fast | check-hold-time | bgp-block | bgp-unblock | reset"
    )


@pytest.mark.parametrize("argv", [[], ["frobnicate"], ["wait-full", "soon"]])
def test_bad_usage_prints_usage_and_exits_2_before_touching_the_lab(labctl, monkeypatch, capsys, argv):
    monkeypatch.setattr(labctl, "load_testbed", lambda path: pytest.fail("the testbed was loaded"))
    assert labctl.main(["labctl.py", *argv]) == 2
    assert capsys.readouterr().out == labctl.USAGE + "\n"


def test_main_reads_sys_argv_when_given_no_arguments(labctl, monkeypatch, capsys):
    monkeypatch.setattr(labctl, "load_testbed", lambda path: pytest.fail("the testbed was loaded"))
    monkeypatch.setattr(sys, "argv", ["labctl.py"])
    assert labctl.main() == 2
    assert capsys.readouterr().out == labctl.USAGE + "\n"


def _documented_in_docstring(doc):
    names = set()
    for line in doc.splitlines():
        if line.startswith("  labctl.py "):
            usage = re.split(r"\s{2,}", line.strip())[0].removeprefix("labctl.py ")
            names |= {word for word in re.split(r"[\s|]+", usage) if word and word != "[seconds]"}
    return names


def test_the_docstring_and_the_readme_list_every_command(root, labctl):
    assert _documented_in_docstring(labctl.__doc__) == set(labctl.COMMANDS)
    readme = (root / "scripts" / "lab" / "README.md").read_text(encoding="utf-8")
    (row,) = [line for line in readme.splitlines() if line.startswith("| `labctl.py` |")]
    assert set(re.findall(r"`([^`]+)`", row)) - {"labctl.py"} == set(labctl.COMMANDS)


def test_testbed_path_defaults_to_the_repository_lab_file_and_honours_ncv_testbed(root, labctl, tmp_path):
    default = root / "testbeds" / "lab.yaml"
    assert labctl.testbed_path({}) == default
    assert labctl.testbed_path({"NCV_TESTBED": ""}) == default
    assert labctl.testbed_path({"NCV_TESTBED": "testbeds/other.yaml"}) == root / "testbeds" / "other.yaml"
    absolute = tmp_path / "elsewhere.yaml"
    assert labctl.testbed_path({"NCV_TESTBED": str(absolute)}) == absolute


def test_main_loads_the_testbed_ncv_testbed_names(labctl, monkeypatch, tmp_path):
    chosen = tmp_path / "second-reservation.yaml"
    monkeypatch.setenv("NCV_TESTBED", str(chosen))
    loaded = []
    monkeypatch.setattr(
        labctl, "load_testbed", lambda path: loaded.append(path) or SimpleNamespace(devices={})
    )
    with pytest.raises(KeyError):  # an empty testbed has no R1; the path is what this checks
        labctl.main(["labctl.py", "shut"])
    assert loaded == [chosen]
