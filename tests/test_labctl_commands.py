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
from test_lab_scripts import (
    NEIGHBOR_FAST_TIMERS,
    NEIGHBOR_STALE_TIMERS,
    OSPF_INTERFACE_DEFAULT,
    OSPF_INTERFACE_FAST,
    OSPF_NOT_ENABLED,
    _load_script,
    _running,
)


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
OSPF = "show ip ospf neighbor"
SHOWS = {
    name: {INTERFACE_BRIEF: "Interface  IP-Address  Status", BGP_SUMMARY: "", OSPF: ""}
    for name in ("R1", "R2")
}

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
    "setup-ospf-fast": (
        lambda m: {
            "R1": [m.ospf_setup_lines("R1", m.OSPF_FAST_HELLO)],
            "R2": [m.ospf_setup_lines("R2", m.OSPF_FAST_HELLO)],
        },
        None,
    ),
    "ospf-block": (lambda m: {"R1": [m.ospf_block_lines()], "R2": []}, OSPF),
    "ospf-unblock": (lambda m: {"R1": [m.ospf_unblock_lines()], "R2": []}, OSPF),
    "setup-ibgp": (lambda m: {"R1": [m.ibgp_setup_lines("R1")], "R2": [m.ibgp_setup_lines("R2")]}, None),
}


@pytest.mark.parametrize("command", CONFIGURE_COMMANDS)
def test_each_change_command_sends_its_lines_to_its_router(labctl, monkeypatch, command):
    expected, show = CONFIGURE_COMMANDS[command]
    code, devices = _run(labctl, monkeypatch, [command], SHOWS)
    assert code == 0
    assert {name: dev.configured for name, dev in devices.items()} == expected(labctl)
    shown = {name: dev.executed for name, dev in devices.items()}
    assert shown == {"R1": [show] if show else [], "R2": []}


OSPF_HEADER = "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
OSPF_FULL = {
    "R1": OSPF_HEADER + "2.2.2.2           1   FULL/DR         00:00:35    1.1.1.2         Ethernet0/1\n",
    "R2": OSPF_HEADER + "1.1.1.1           1   FULL/BDR        00:00:33    1.1.1.1         Ethernet0/1\n",
}
OSPF_GONE = {"R1": OSPF_HEADER, "R2": OSPF_HEADER}
# What the dead-timer run predicts once R1's ACL drops OSPF from R2: R1 has deleted 2.2.2.2,
# and R2, which still hears R1's hellos without itself in them, holds 1.1.1.1 in INIT.
OSPF_LOST = {
    "R1": OSPF_HEADER,
    "R2": OSPF_HEADER + "1.1.1.1           1   INIT/DROTHER    00:00:03    1.1.1.1         Ethernet0/1\n",
}
BGP_HEADER = "Neighbor     V    AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down  State/PfxRcd\n"
BGP_UP = {
    "R1": BGP_HEADER + "1.1.1.2      4 65002      15      15      3   0    0 00:10:12        1\n",
    "R2": BGP_HEADER + "1.1.1.1      4 65001      15      15      3   0    0 00:10:12        1\n",
}
BGP_DOWN = {
    "R1": BGP_HEADER + "1.1.1.2      4 65002       0       0      1   0    0 never    Idle (Admin)\n",
    "R2": BGP_HEADER + "1.1.1.1      4 65001       0       0      1   0    0 00:00:03 Active\n",
}

# The iBGP run's sessions, between the loopbacks: up with the peer's prefix learned, up with
# nothing learned yet, and down (Idle while there is no route to the peer, Active once there is).
IBGP_UP = {
    "R1": BGP_HEADER + "10.255.255.2 4 65010      12      12      3   0    0 00:00:30        1\n",
    "R2": BGP_HEADER + "10.255.255.1 4 65010      12      12      3   0    0 00:00:30        1\n",
}
IBGP_NOTHING_LEARNED = {
    name: output.replace("        1\n", "        0\n") for name, output in IBGP_UP.items()
}
IBGP_DOWN = {
    "R1": BGP_HEADER + "10.255.255.2 4 65010       0       0      1   0    0 00:00:05 Idle\n",
    "R2": BGP_HEADER + "10.255.255.1 4 65010       0       0      1   0    0 00:00:02 Active\n",
}

# command -> (the show it polls, output that satisfies it, output that never does)
WAIT_COMMANDS = {
    "wait-full": (OSPF, OSPF_FULL, OSPF_GONE),
    "wait-gone": (OSPF, OSPF_GONE, OSPF_FULL),
    "wait-bgp-up": (BGP_SUMMARY, BGP_UP, BGP_DOWN),
    "wait-bgp-down": (BGP_SUMMARY, BGP_DOWN, BGP_UP),
    "wait-ospf-lost": (OSPF, OSPF_LOST, OSPF_FULL),
    "wait-ibgp-up": (BGP_SUMMARY, IBGP_UP, IBGP_DOWN),
    "wait-ibgp-down": (BGP_SUMMARY, IBGP_DOWN, IBGP_UP),
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


def test_after_the_dead_timer_change_only_wait_ospf_lost_finishes(labctl, monkeypatch):
    """R2 keeps an entry for R1, so the wait-gone the 2026-09-12 run used would time out."""
    lost = _answers(OSPF, OSPF_LOST)
    assert _run(labctl, monkeypatch, ["wait-gone", "0"], lost)[0] == 1
    assert _run(labctl, monkeypatch, ["wait-ospf-lost", "0"], lost)[0] == 0


def test_wait_ibgp_up_waits_for_a_learned_prefix_not_just_established(labctl, monkeypatch, capsys):
    """A session that has just come up shows a prefix count of 0, which bgp_session_state reads
    as Established; the iBGP captures need the learned route, so wait-ibgp-up keeps waiting."""
    nothing_learned = _answers(BGP_SUMMARY, IBGP_NOTHING_LEARNED)
    assert _run(labctl, monkeypatch, ["wait-ibgp-up", "0"], nothing_learned)[0] == 1
    assert "{'R1': 0, 'R2': 0}" in capsys.readouterr().out
    assert _run(labctl, monkeypatch, ["wait-ibgp-down", "0"], nothing_learned)[0] == 1


def test_the_ebgp_wait_still_counts_an_established_session_with_nothing_learned_as_up(labctl, monkeypatch):
    nothing_learned = {name: output.replace("        1\n", "        0\n") for name, output in BGP_UP.items()}
    assert _run(labctl, monkeypatch, ["wait-bgp-up", "0"], _answers(BGP_SUMMARY, nothing_learned))[0] == 0


def test_the_ibgp_waits_ignore_the_ebgp_peers(labctl, monkeypatch):
    """Each wait reads only its own peers: the eBGP sessions being up says nothing about iBGP."""
    assert _run(labctl, monkeypatch, ["wait-ibgp-up", "0"], _answers(BGP_SUMMARY, BGP_UP))[0] == 1
    assert _run(labctl, monkeypatch, ["wait-bgp-up", "0"], _answers(BGP_SUMMARY, IBGP_UP))[0] == 1


def _neighbors(r1_output, r2_output, peers=None):
    peers = peers or {"R1": "1.1.1.2", "R2": "1.1.1.1"}
    return {
        "R1": {f"show bgp ipv4 unicast neighbors {peers['R1']}": r1_output},
        "R2": {f"show bgp ipv4 unicast neighbors {peers['R2']}": r2_output},
    }


def test_check_hold_time_passes_only_when_both_sessions_run_the_fast_timers(labctl, monkeypatch):
    fast = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_FAST_TIMERS)
    assert _run(labctl, monkeypatch, ["check-hold-time"], fast)[0] == 0
    stale = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_STALE_TIMERS)
    assert _run(labctl, monkeypatch, ["check-hold-time"], stale)[0] == 1


IBGP_PEERS = {"R1": "10.255.255.2", "R2": "10.255.255.1"}


def test_check_ibgp_hold_time_reads_the_loopback_peers(labctl, monkeypatch, capsys):
    fast = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_FAST_TIMERS, IBGP_PEERS)
    code, devices = _run(labctl, monkeypatch, ["check-ibgp-hold-time"], fast)
    assert code == 0
    assert devices["R1"].executed == ["show bgp ipv4 unicast neighbors 10.255.255.2"]
    assert devices["R2"].executed == ["show bgp ipv4 unicast neighbors 10.255.255.1"]
    assert "R2: negotiated (hold, keepalive) = (9, 3)" in capsys.readouterr().out
    stale = _neighbors(NEIGHBOR_STALE_TIMERS, NEIGHBOR_FAST_TIMERS, IBGP_PEERS)
    assert _run(labctl, monkeypatch, ["check-ibgp-hold-time"], stale)[0] == 1
    assert "`clear ip bgp 10.255.255.2` on R1" in capsys.readouterr().out


OSPF_INTERFACE = "show ip ospf interface Ethernet0/1"


def _interface(r1_output, r2_output):
    return {"R1": {OSPF_INTERFACE: r1_output}, "R2": {OSPF_INTERFACE: r2_output}}


def test_check_dead_time_passes_only_when_both_routers_run_the_fast_timers(labctl, monkeypatch, capsys):
    fast = _interface(OSPF_INTERFACE_FAST, OSPF_INTERFACE_FAST)
    assert _run(labctl, monkeypatch, ["check-dead-time"], fast)[0] == 0
    out = capsys.readouterr().out
    assert "R1: Ethernet0/1 (hello, dead) = (1, 4)" in out
    assert "R2: Ethernet0/1 (hello, dead) = (1, 4)" in out
    for r2 in (OSPF_INTERFACE_DEFAULT, OSPF_NOT_ENABLED):
        assert _run(labctl, monkeypatch, ["check-dead-time"], _interface(OSPF_INTERFACE_FAST, r2))[0] == 1
        out = capsys.readouterr().out
        assert "expected Hello 1 s and Dead 4 s" in out
        assert "`labctl.py reset` followed by `labctl.py setup-ospf-fast`" in out


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
        (["check-dead-time"], _interface(OSPF_INTERFACE_FAST, ""), {"R2": "execute"}),
        (["ospf-block"], SHOWS, {"R1": "configure"}),
        (["setup-ibgp"], {}, {"R2": "configure"}),
        (["wait-ibgp-up"], _answers(BGP_SUMMARY, IBGP_UP), {"R2": "execute"}),
        (["check-ibgp-hold-time"], _neighbors(NEIGHBOR_FAST_TIMERS, "", IBGP_PEERS), {"R2": "execute"}),
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
    checks = {"check-hold-time", "check-dead-time", "check-ibgp-hold-time", "reset"}
    assert set(CONFIGURE_COMMANDS) | set(WAIT_COMMANDS) | checks == set(labctl.COMMANDS)


def test_usage_is_the_old_text_with_the_dead_timer_and_ibgp_commands_and_reset_added(labctl):
    assert labctl.USAGE == (
        "usage: labctl.py setup-ospf | shut | noshut | wait-full [seconds] | wait-gone [seconds]"
        " | setup-bgp | bgp-shut | bgp-noshut | wait-bgp-up [seconds] | wait-bgp-down [seconds]"
        " | setup-bgp-fast | check-hold-time | bgp-block | bgp-unblock"
        " | setup-ospf-fast | check-dead-time | ospf-block | ospf-unblock | wait-ospf-lost [seconds]"
        " | setup-ibgp | wait-ibgp-up [seconds] | wait-ibgp-down [seconds] | check-ibgp-hold-time"
        " | reset"
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
