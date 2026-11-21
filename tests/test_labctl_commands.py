"""scripts/lab/labctl.py's commands, run through main() against a fake lab.

The lab is reachable only during a reservation, so a typo in a command would otherwise be
found there. Each test replaces load_testbed with a fake testbed whose R1 and R2 append every
connect, configure, show, and disconnect to one shared log, as (device, operation, payload),
and answer show commands from a table the test gives; a show command the test did not expect
fails it. Each command's test compares the whole log, so it also catches a command that
touches the other router, a show sent before the configure it should follow, or a router left
connected. The line builders the log is compared against are pinned literally in
tests/test_lab_scripts.py. The clock is replaced too, so the waits never sleep.
"""

from __future__ import annotations

import re
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from test_lab_scripts import (
    NEIGHBOR_FAST_TIMERS,
    NEIGHBOR_STALE_TIMERS,
    OSPF_INTERFACE_DEFAULT,
    OSPF_INTERFACE_FAST,
    OSPF_NOT_ENABLED,
    SHOW_VRF,
    VRF_NEIGHBOR,
    _load_script,
    _running,
)


class FakeDevice:
    """One router of the fake lab. What it is sent goes onto the log it shares with the other."""

    def __init__(self, name, answers, log, fail_on=None):
        self.name, self.answers, self.log, self.fail_on = name, answers, log, fail_on

    def connect(self, **kwargs):
        self.log.append((self.name, "connect", None))

    def disconnect(self):
        self.log.append((self.name, "disconnect", None))

    def configure(self, lines):
        if self.fail_on == "configure":
            raise RuntimeError(f"{self.name} refused the configuration")
        self.log.append((self.name, "configure", list(lines)))

    def execute(self, command):
        if self.fail_on == "execute":
            raise RuntimeError(f"{self.name} dropped the connection")
        if command not in self.answers:
            pytest.fail(f"{self.name} was sent {command!r}, which this test has no answer for")
        self.log.append((self.name, "execute", command))
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
    """main(argv) on a fake R1 and R2: the exit code and the shared log. Checks every device
    connected was disconnected, even when the command raised."""
    answers = answers or {}
    log: list[tuple[str, str, Any]] = []
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
            assert log.count((name, "connect", None)) == log.count((name, "disconnect", None)), log
    assert loaded == [labctl.testbed_path({})]
    return code, log


def _session(name, *operations):
    """What one connection to a router logs: connect, each (operation, payload), disconnect."""
    return [
        (name, "connect", None),
        *((name, op, payload) for op, payload in operations),
        (name, "disconnect", None),
    ]


def _polls(show, polls):
    """What a wait logs: it connects to both routers, reads `show` on each `polls` times, then
    disconnects them, without configuring anything."""
    names = ("R1", "R2")
    return (
        [(name, "connect", None) for name in names]
        + [(name, "execute", show) for _ in range(polls) for name in names]
        + [(name, "disconnect", None) for name in names]
    )


def _shows(command_for):
    """What a check logs: one connection per router in turn, each sending one show command."""
    return [entry for name in ("R1", "R2") for entry in _session(name, ("execute", command_for[name]))]


def _echoed(name, command, output, reading):
    """A check's printout for one router: its prompt and command, the raw output, then the
    reading parsed from it."""
    newline = "" if output.endswith("\n") else "\n"
    return f"{name}# {command}\n{output}{newline}{reading}\n"


INTERFACE_BRIEF = "show ip interface brief"
BGP_SUMMARY = "show bgp ipv4 unicast summary"
VRF_SUMMARY = "show bgp vpnv4 unicast vrf NCV summary"
OSPF = "show ip ospf neighbor"
SHOWS = {
    name: {INTERFACE_BRIEF: "Interface  IP-Address  Status", BGP_SUMMARY: "", VRF_SUMMARY: "", OSPF: ""}
    for name in ("R1", "R2")
}


def _on_both(build):
    """The log of a setup: R1 is configured with build(labctl, "R1") and let go, then R2 with
    its own lines, and nothing is shown."""
    return lambda m: [
        entry for name in ("R1", "R2") for entry in _session(name, ("configure", build(m, name)))
    ]


def _on_r1(build, show):
    """The log of a change: R1 alone is configured with build(labctl), then shows `show`."""
    return lambda m: _session("R1", ("configure", build(m)), ("execute", show))


# command -> the whole log it should leave, built from labctl's line builders
CONFIGURE_COMMANDS = {
    "setup-ospf": _on_both(lambda m, name: m.ospf_setup_lines(name)),
    "shut": _on_r1(lambda m: ["interface Ethernet0/1", "shutdown"], INTERFACE_BRIEF),
    "noshut": _on_r1(lambda m: ["interface Ethernet0/1", "no shutdown"], INTERFACE_BRIEF),
    "setup-bgp": _on_both(lambda m, name: m.bgp_setup_lines(name)),
    "bgp-shut": _on_r1(lambda m: ["router bgp 65001", "neighbor 1.1.1.2 shutdown"], BGP_SUMMARY),
    "bgp-noshut": _on_r1(lambda m: ["router bgp 65001", "no neighbor 1.1.1.2 shutdown"], BGP_SUMMARY),
    "setup-bgp-fast": _on_both(lambda m, name: m.bgp_setup_lines(name, m.FAST_TIMERS)),
    "bgp-block": _on_r1(lambda m: m.bgp_block_lines(), BGP_SUMMARY),
    "bgp-unblock": _on_r1(lambda m: m.bgp_unblock_lines(), BGP_SUMMARY),
    "setup-ospf-fast": _on_both(lambda m, name: m.ospf_setup_lines(name, m.OSPF_FAST_HELLO)),
    "ospf-block": _on_r1(lambda m: m.ospf_block_lines(), OSPF),
    "ospf-unblock": _on_r1(lambda m: m.ospf_unblock_lines(), OSPF),
    "setup-ibgp": _on_both(lambda m, name: m.ibgp_setup_lines(name)),
    "setup-vrf": _on_both(lambda m, name: m.vrf_setup_lines(name)),
    "vrf-shut": _on_r1(lambda m: ["interface Ethernet0/1.100", "shutdown"], VRF_SUMMARY),
    "vrf-noshut": _on_r1(lambda m: ["interface Ethernet0/1.100", "no shutdown"], VRF_SUMMARY),
}


@pytest.mark.parametrize("command", CONFIGURE_COMMANDS)
def test_each_change_command_sends_its_lines_to_its_router(labctl, monkeypatch, command):
    code, log = _run(labctl, monkeypatch, [command], SHOWS)
    assert code == 0
    assert log == CONFIGURE_COMMANDS[command](labctl)


def test_the_log_shows_the_order_across_both_routers(labctl, monkeypatch):
    """A literal log, so the shape every comparison above relies on is pinned once by hand: a
    change reaches R1 only and shows after it configures; a setup lets R1 go before R2."""
    _, change = _run(labctl, monkeypatch, ["shut"], SHOWS)
    assert change == [
        ("R1", "connect", None),
        ("R1", "configure", ["interface Ethernet0/1", "shutdown"]),
        ("R1", "execute", "show ip interface brief"),
        ("R1", "disconnect", None),
    ]
    _, setup = _run(labctl, monkeypatch, ["setup-ospf"], SHOWS)
    assert setup == [
        ("R1", "connect", None),
        ("R1", "configure", ["router ospf 1", "router-id 1.1.1.1", "network 1.1.1.0 0.0.0.255 area 0"]),
        ("R1", "disconnect", None),
        ("R2", "connect", None),
        ("R2", "configure", ["router ospf 1", "router-id 2.2.2.2", "network 1.1.1.0 0.0.0.255 area 0"]),
        ("R2", "disconnect", None),
    ]


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

# The BGP VRF run's sessions, in vrf NCV's own summary: up with the peer's Loopback100 network
# learned, up with nothing learned yet, and down (R1 Idle with its subinterface shut, R2 Active).
VRF_UP = {
    "R1": BGP_HEADER + "1.1.1.2      4 65002      12      12      3   0    0 00:00:31        1\n",
    "R2": BGP_HEADER + "1.1.1.1      4 65001      12      12      3   0    0 00:00:31        1\n",
}
VRF_NOTHING_LEARNED = {name: output.replace("        1\n", "        0\n") for name, output in VRF_UP.items()}
VRF_DOWN = {
    "R1": BGP_HEADER + "1.1.1.2      4 65002       0       0      1   0    0 00:00:04 Idle\n",
    "R2": BGP_HEADER + "1.1.1.1      4 65001       0       0      1   0    0 00:00:02 Active\n",
}
# `show vrf` with vrf NCV still there (as while IOS deletes it after reset) and without it.
VRF_LISTED = {"R1": SHOW_VRF, "R2": SHOW_VRF.replace("65001:", "65002:")}
VRF_GONE = {
    name: "\n".join(line for line in output.splitlines() if not line.strip().startswith(("NCV ", "Lo100")))
    for name, output in VRF_LISTED.items()
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
    "wait-vrf-gone": ("show vrf", VRF_GONE, VRF_LISTED),
    "wait-vrf-bgp-up": (VRF_SUMMARY, VRF_UP, VRF_DOWN),
    "wait-vrf-bgp-down": (VRF_SUMMARY, VRF_DOWN, VRF_UP),
}


def _answers(show, outputs):
    return {name: {show: output} for name, output in outputs.items()}


@pytest.mark.parametrize("command", WAIT_COMMANDS)
def test_a_wait_that_is_already_satisfied_returns_on_the_first_poll(labctl, monkeypatch, command):
    show, satisfied, _ = WAIT_COMMANDS[command]
    code, log = _run(labctl, monkeypatch, [command], _answers(show, satisfied))
    assert code == 0
    assert log == _polls(show, 1)
    assert labctl.time.sleeps == []


@pytest.mark.parametrize("command", WAIT_COMMANDS)
def test_a_wait_that_never_comes_true_times_out_with_exit_1(labctl, monkeypatch, capsys, command):
    show, _, never = WAIT_COMMANDS[command]
    code, log = _run(labctl, monkeypatch, [command, "0"], _answers(show, never))
    assert code == 1
    assert "timed out waiting for" in capsys.readouterr().out
    # with 0 seconds: one poll, one 5 s sleep that passes the deadline, a last poll, and out
    assert log == _polls(show, 2)
    assert labctl.time.sleeps == [5]


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


def test_wait_vrf_bgp_up_waits_for_a_learned_prefix_in_the_vrf_table(labctl, monkeypatch, capsys):
    """The VRF waits read vrf NCV's summary only: the global sessions being up says nothing about
    the VRF ones, and an Established VRF session that has learned nothing is not up yet."""
    nothing_learned = _answers(VRF_SUMMARY, VRF_NOTHING_LEARNED)
    assert _run(labctl, monkeypatch, ["wait-vrf-bgp-up", "0"], nothing_learned)[0] == 1
    assert "{'R1': 0, 'R2': 0}" in capsys.readouterr().out
    assert _run(labctl, monkeypatch, ["wait-vrf-bgp-down", "0"], nothing_learned)[0] == 1
    # wait-bgp-up asks only for the global summary; a VRF answer there would not count.
    code, log = _run(labctl, monkeypatch, ["wait-bgp-up"], _answers(BGP_SUMMARY, BGP_UP))
    assert code == 0 and log == _polls(BGP_SUMMARY, 1)


BGP_NEIGHBORS = "show bgp ipv4 unicast neighbors"


def _neighbors(r1_output, r2_output, peers=None, command=BGP_NEIGHBORS):
    peers = peers or {"R1": "1.1.1.2", "R2": "1.1.1.1"}
    return {
        "R1": {f"{command} {peers['R1']}": r1_output},
        "R2": {f"{command} {peers['R2']}": r2_output},
    }


GLOBAL_NEIGHBORS = {"R1": f"{BGP_NEIGHBORS} 1.1.1.2", "R2": f"{BGP_NEIGHBORS} 1.1.1.1"}


def test_check_hold_time_passes_only_when_both_sessions_run_the_fast_timers(labctl, monkeypatch, capsys):
    fast = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_FAST_TIMERS)
    code, log = _run(labctl, monkeypatch, ["check-hold-time"], fast)
    assert code == 0
    assert log == _shows(GLOBAL_NEIGHBORS)
    out = capsys.readouterr().out
    for name in ("R1", "R2"):
        reading = f"{name}: negotiated (hold, keepalive) = (9, 3)"
        assert _echoed(name, GLOBAL_NEIGHBORS[name], NEIGHBOR_FAST_TIMERS, reading) in out
    stale = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_STALE_TIMERS)
    assert _run(labctl, monkeypatch, ["check-hold-time"], stale)[0] == 1
    reading = "R2: negotiated (hold, keepalive) = (180, 60)"
    assert _echoed("R2", GLOBAL_NEIGHBORS["R2"], NEIGHBOR_STALE_TIMERS, reading) in capsys.readouterr().out


IBGP_PEERS = {"R1": "10.255.255.2", "R2": "10.255.255.1"}


def test_check_ibgp_hold_time_reads_the_loopback_peers(labctl, monkeypatch, capsys):
    fast = _neighbors(NEIGHBOR_FAST_TIMERS, NEIGHBOR_FAST_TIMERS, IBGP_PEERS)
    code, log = _run(labctl, monkeypatch, ["check-ibgp-hold-time"], fast)
    assert code == 0
    commands = {"R1": f"{BGP_NEIGHBORS} 10.255.255.2", "R2": f"{BGP_NEIGHBORS} 10.255.255.1"}
    assert log == _shows(commands)
    out = capsys.readouterr().out
    for name in ("R1", "R2"):
        reading = f"{name}: negotiated (hold, keepalive) = (9, 3)"
        assert _echoed(name, commands[name], NEIGHBOR_FAST_TIMERS, reading) in out
    stale = _neighbors(NEIGHBOR_STALE_TIMERS, NEIGHBOR_FAST_TIMERS, IBGP_PEERS)
    assert _run(labctl, monkeypatch, ["check-ibgp-hold-time"], stale)[0] == 1
    assert "`clear ip bgp 10.255.255.2` on R1" in capsys.readouterr().out


VRF_NEIGHBORS = "show bgp vpnv4 unicast vrf NCV neighbors"


def test_check_vrf_hold_time_reads_the_vrf_neighbors_and_names_the_vrf_clear(labctl, monkeypatch, capsys):
    fast = _neighbors(VRF_NEIGHBOR, VRF_NEIGHBOR, command=VRF_NEIGHBORS)
    code, log = _run(labctl, monkeypatch, ["check-vrf-hold-time"], fast)
    assert code == 0
    commands = {"R1": f"{VRF_NEIGHBORS} 1.1.1.2", "R2": f"{VRF_NEIGHBORS} 1.1.1.1"}
    assert log == _shows(commands)
    out = capsys.readouterr().out
    for name in ("R1", "R2"):
        reading = f"{name}: negotiated (hold, keepalive) = (9, 3)"
        assert _echoed(name, commands[name], VRF_NEIGHBOR, reading) in out
    stale = _neighbors(VRF_NEIGHBOR, NEIGHBOR_STALE_TIMERS, command=VRF_NEIGHBORS)
    assert _run(labctl, monkeypatch, ["check-vrf-hold-time"], stale)[0] == 1
    assert "`clear ip bgp vrf NCV 1.1.1.2` on R1" in capsys.readouterr().out
    # The global check is unchanged: same command, same advice.
    stale = _neighbors(NEIGHBOR_STALE_TIMERS, NEIGHBOR_FAST_TIMERS)
    assert _run(labctl, monkeypatch, ["check-hold-time"], stale)[0] == 1
    assert "`clear ip bgp 1.1.1.2` on R1" in capsys.readouterr().out


OSPF_INTERFACE = "show ip ospf interface Ethernet0/1"


def _interface(r1_output, r2_output):
    return {"R1": {OSPF_INTERFACE: r1_output}, "R2": {OSPF_INTERFACE: r2_output}}


def test_check_dead_time_passes_only_when_both_routers_run_the_fast_timers(labctl, monkeypatch, capsys):
    fast = _interface(OSPF_INTERFACE_FAST, OSPF_INTERFACE_FAST)
    code, log = _run(labctl, monkeypatch, ["check-dead-time"], fast)
    assert code == 0
    assert log == _shows({"R1": OSPF_INTERFACE, "R2": OSPF_INTERFACE})
    out = capsys.readouterr().out
    for name in ("R1", "R2"):
        reading = f"{name}: Ethernet0/1 (hello, dead) = (1, 4)"
        assert _echoed(name, OSPF_INTERFACE, OSPF_INTERFACE_FAST, reading) in out
    for r2, reading in (
        (OSPF_INTERFACE_DEFAULT, "R2: Ethernet0/1 (hello, dead) = (10, 40)"),
        (OSPF_NOT_ENABLED, "R2: Ethernet0/1 (hello, dead) = None"),
    ):
        assert _run(labctl, monkeypatch, ["check-dead-time"], _interface(OSPF_INTERFACE_FAST, r2))[0] == 1
        out = capsys.readouterr().out
        assert _echoed("R2", OSPF_INTERFACE, r2, reading) in out
        assert "expected Hello 1 s and Dead 4 s" in out
        assert "`labctl.py reset` followed by `labctl.py setup-ospf-fast`" in out


def test_a_check_prints_output_without_a_final_newline_and_empty_output_as_they_came(labctl):
    assert labctl.echoed("R1", "show x", "line") == "R1# show x\nline\n"
    assert labctl.echoed("R1", "show x", "line\n") == "R1# show x\nline\n"
    assert labctl.echoed("R2", "show x", "") == "R2# show x\n\n"


def test_reset_configures_only_the_router_that_needs_it(root, labctl, monkeypatch, capsys):
    dirty = _running(root, "lab-2026-11-20/bgp-holdtimer/post", "R1")
    clean = _running(root, "lab-2026-09-12/routes/pre", "R2")
    answers = {"R1": {"show running-config": dirty}, "R2": {"show running-config": clean}}
    code, log = _run(labctl, monkeypatch, ["reset"], answers)
    assert code == 0
    lines = labctl.reset_lines(dirty)
    assert lines[-1] == "no router bgp 65001"
    assert log == _session("R1", ("execute", "show running-config"), ("configure", lines)) + _session(
        "R2", ("execute", "show running-config")
    )
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
        (["wait-vrf-gone"], _answers("show vrf", VRF_GONE), {"R2": "execute"}),
        (["setup-vrf"], {}, {"R2": "configure"}),
        (["wait-vrf-bgp-up"], _answers(VRF_SUMMARY, VRF_UP), {"R2": "execute"}),
        (
            ["check-vrf-hold-time"],
            _neighbors(VRF_NEIGHBOR, "", command=VRF_NEIGHBORS),
            {"R2": "execute"},
        ),
        (["vrf-shut"], SHOWS, {"R1": "configure"}),
    ],
)
def test_a_command_that_raises_still_disconnects_every_router_it_reached(
    labctl, monkeypatch, argv, answers, fail_on
):
    # _run asserts every connect was matched by a disconnect, even as the error propagates.
    with pytest.raises(RuntimeError):
        _run(labctl, monkeypatch, argv, answers, fail_on)


def test_every_command_in_the_table_is_exercised_here(labctl):
    checks = {"check-hold-time", "check-dead-time", "check-ibgp-hold-time", "check-vrf-hold-time", "reset"}
    assert set(CONFIGURE_COMMANDS) | set(WAIT_COMMANDS) | checks == set(labctl.COMMANDS)


def test_usage_is_the_old_text_with_the_dead_timer_ibgp_and_vrf_commands_and_reset_added(labctl):
    assert labctl.USAGE == (
        "usage: labctl.py setup-ospf | shut | noshut | wait-full [seconds] | wait-gone [seconds]"
        " | setup-bgp | bgp-shut | bgp-noshut | wait-bgp-up [seconds] | wait-bgp-down [seconds]"
        " | setup-bgp-fast | check-hold-time | bgp-block | bgp-unblock"
        " | setup-ospf-fast | check-dead-time | ospf-block | ospf-unblock | wait-ospf-lost [seconds]"
        " | setup-ibgp | wait-ibgp-up [seconds] | wait-ibgp-down [seconds] | check-ibgp-hold-time"
        " | wait-vrf-gone [seconds] | setup-vrf | wait-vrf-bgp-up [seconds] | wait-vrf-bgp-down [seconds]"
        " | check-vrf-hold-time | vrf-shut | vrf-noshut"
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
