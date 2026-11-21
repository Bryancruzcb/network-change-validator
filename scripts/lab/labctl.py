"""Operator-side actions on the DevNet CML default-lab, deliberately outside ncv.

ncv never pushes configuration. These are the hands that make the one planned change in
the lab, so the captures around it have something to catch. Isolated lab only.

Usage, with the logins in the NCV_* environment (the run-*.sh scripts prompt for them):
  labctl.py setup-ospf                router ospf 1 on R1 and R2, area 0 on the R1-R2 link
  labctl.py shut | noshut             shutdown / no shutdown on R1 Ethernet0/1
  labctl.py wait-full [seconds]       poll until both OSPF neighbors are FULL (default 120)
  labctl.py wait-gone [seconds]       poll until both OSPF neighbor entries are gone
  labctl.py setup-bgp                 eBGP R1 (AS 65001) to R2 (AS 65002) over the 1.1.1.0/24 link
  labctl.py bgp-shut | bgp-noshut     neighbor 1.1.1.2 shutdown / no shutdown on R1
  labctl.py wait-bgp-up [seconds]     poll until both BGP sessions are Established
  labctl.py wait-bgp-down [seconds]   poll until neither BGP session is Established
  labctl.py setup-bgp-fast            setup-bgp with a 3 s keepalive and a 9 s hold time on both peers
  labctl.py check-hold-time           exit 1 unless both sessions negotiated the 9 s hold time
  labctl.py bgp-block | bgp-unblock   add / remove an inbound ACL on R1 Ethernet0/1 that drops BGP from R2
  labctl.py reset                     remove what these scripts add from R1 and R2, back to what ships

The testbed is testbeds/lab.yaml under the repository root, wherever this is run from, or the
file NCV_TESTBED names (a relative path is read from the repository root). Genie is imported
only when a command runs, so the show-output parsers, the planned configuration lines, and the
command table here can be tested without the lab extra installed.
"""

import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
ROUTER_IDS = {"R1": "1.1.1.1", "R2": "2.2.2.2"}
OSPF_PEERS = {"R1": "2.2.2.2", "R2": "1.1.1.1"}
# eBGP over the direct link, each router advertising its own LAN. The static routes the lab
# ships with outrank the learned prefixes, so the routing table does not change with the session.
BGP = {
    "R1": {"asn": 65001, "peer": "1.1.1.2", "peer_asn": 65002, "network": "10.10.10.0"},
    "R2": {"asn": 65002, "peer": "1.1.1.1", "peer_asn": 65001, "network": "20.20.20.0"},
}
# The hold-timer run: keepalive and hold time in seconds. 9 s instead of IOS's default 180 s, so
# the session drops seconds after BGP stops arriving rather than three minutes later.
FAST_TIMERS = (3, 9)
# The hold-timer run's change: an inbound ACL on R1's side of the link that drops TCP port 179
# from R2 in both directions of the session, whichever router opened the TCP connection, and
# passes everything else. Inbound interface ACLs also filter traffic addressed to the router.
BLOCK_ACL = "NCV-BLOCK-BGP"
BLOCK_INTERFACE = "Ethernet0/1"
# What the sandbox ships in Ethernet0/3, the one spare port. reset puts it back when a run has
# used it; the order IOS lists the two lines in does not matter.
SHIPPED_ETHERNET0_3 = ("no ip address", "shutdown")


def testbed_path(environ) -> Path:
    """The testbed file: NCV_TESTBED when it is set and not empty, else testbeds/lab.yaml.
    A relative NCV_TESTBED is read from the repository root, like the run scripts, which cd
    there first; an absolute one is used as it is."""
    value = environ.get("NCV_TESTBED", "")
    if not value:
        return REPO / "testbeds" / "lab.yaml"
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def ospf_neighbor_state(output: str, peer: str):
    """From `show ip ospf neighbor`: True if the peer is FULL, False if listed but not FULL,
    None if not listed."""
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == peer:
            return "FULL" in line
    return None


def bgp_session_state(output: str, peer: str):
    """From `show bgp ipv4 unicast summary`: True if the session is Established (the last
    column is then a prefix count), False if listed in any other state such as Idle, Active,
    or Idle (Admin), None if not listed."""
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == peer:
            return fields[-1].isdigit()
    return None


_NEGOTIATED_TIMERS = re.compile(r"hold time is (\d+), keepalive interval is (\d+) seconds")


def bgp_negotiated_timers(output: str):
    """From `show bgp ipv4 unicast neighbors <peer>`: the (hold time, keepalive) the session
    negotiated, read from the line that starts `Last read`, or None if the output has no such
    line. The `Configured hold time is ...` line IOS adds when the timers differ from the
    defaults is skipped: it says what was asked for, not what the session runs with."""
    for line in output.splitlines():
        if line.strip().startswith("Last read"):
            match = _NEGOTIATED_TIMERS.search(line)
            if match:
                return int(match.group(1)), int(match.group(2))
    return None


def ospf_setup_lines(name: str) -> list[str]:
    """The configuration setup-ospf sends to one router: OSPF area 0 on the R1-R2 link."""
    return ["router ospf 1", f"router-id {ROUTER_IDS[name]}", "network 1.1.1.0 0.0.0.255 area 0"]


def bgp_setup_lines(name: str, timers=None) -> list[str]:
    """The configuration setup-bgp sends to one router; with `timers` (keepalive, hold time),
    also the per-neighbor timers line setup-bgp-fast adds."""
    cfg = BGP[name]
    peer = cfg["peer"]
    lines = [
        f"router bgp {cfg['asn']}",
        f"bgp router-id {ROUTER_IDS[name]}",
        "bgp log-neighbor-changes",
        f"neighbor {peer} remote-as {cfg['peer_asn']}",
    ]
    if timers:
        lines.append(f"neighbor {peer} timers {timers[0]} {timers[1]}")
    return lines + [
        "address-family ipv4",
        f"network {cfg['network']} mask 255.255.255.0",
        f"neighbor {peer} activate",
        # lets Genie's learn read received-routes instead of an error line
        f"neighbor {peer} soft-reconfiguration inbound",
        "exit-address-family",
    ]


def bgp_block_lines() -> list[str]:
    """The hold-timer run's change on R1: the ACL, then its inbound binding on the link."""
    local, remote = BGP["R2"]["peer"], BGP["R1"]["peer"]
    return [
        f"ip access-list extended {BLOCK_ACL}",
        f"deny tcp host {remote} host {local} eq bgp",
        f"deny tcp host {remote} eq bgp host {local}",
        "permit ip any any",
        "exit",
        f"interface {BLOCK_INTERFACE}",
        f"ip access-group {BLOCK_ACL} in",
    ]


def bgp_unblock_lines() -> list[str]:
    """The undo for bgp_block_lines: unbind the ACL first, then delete it."""
    return [
        f"interface {BLOCK_INTERFACE}",
        f"no ip access-group {BLOCK_ACL} in",
        "exit",
        f"no ip access-list extended {BLOCK_ACL}",
    ]


def config_blocks(running_config: str) -> list[tuple[str, tuple[str, ...]]]:
    """A running config as (top-level line, its indented lines stripped), in config order.
    Blank lines are dropped; nested lines (an address family inside router bgp) count as the
    top-level block's own, which is all reset needs."""
    blocks: list[tuple[str, list[str]]] = []
    for line in running_config.splitlines():
        if not line.strip():
            continue
        if line[0].isspace():
            if blocks:
                blocks[-1][1].append(line.strip())
        else:
            blocks.append((line.rstrip(), []))
    return [(head, tuple(body)) for head, body in blocks]


_ACCESS_GROUP = re.compile(r"ip access-group (NCV-\S+) (in|out)")
_ACCESS_LIST = re.compile(r"ip access-list extended (NCV-\S+)")
_ROUTER_BGP = re.compile(r"router bgp (\S+)")
_ADDED_INTERFACE = re.compile(r"interface (Loopback\d+|Ethernet0/1\.\d+)")
_LINK_RESETS = (
    ("shutdown", "no shutdown"),
    ("ip ospf hello-interval", "no ip ospf hello-interval"),
    ("ip ospf dead-interval", "no ip ospf dead-interval"),
)


def reset_lines(running_config: str) -> list[str]:
    """The configuration that undoes the lab scripts' work on one router, read from its
    running config. A line is emitted only for something present, unbinding before deleting,
    so a config the sandbox shipped gives []. Mgmt-intf, Ethernet0/0 and 0/2, the static
    routes, users, and lines are never touched: they are how the scripts reach the routers."""
    blocks = config_blocks(running_config)
    body = dict(blocks)
    lines: list[str] = []
    for head, children in blocks:
        if head.startswith("interface "):
            bound = [m for m in map(_ACCESS_GROUP.fullmatch, children) if m]
            if bound:
                lines += [head, *(f"no ip access-group {m.group(1)} {m.group(2)}" for m in bound)]
    lines += [f"no {head}" for head, _ in blocks if _ACCESS_LIST.fullmatch(head)]
    lines += [f"no {head}" for head, _ in blocks if _ROUTER_BGP.fullmatch(head)]
    if "router ospf 1" in body:
        lines.append("no router ospf 1")
    link = body.get("interface Ethernet0/1", ())
    undo = [no for prefix, no in _LINK_RESETS if any(c.startswith(prefix) for c in link)]
    if undo:
        lines += ["interface Ethernet0/1", *undo]
    lines += [f"no {head}" for head, _ in blocks if _ADDED_INTERFACE.fullmatch(head)]
    spare = body.get("interface Ethernet0/3")
    if spare is not None and sorted(c for c in spare if c != "!") != sorted(SHIPPED_ETHERNET0_3):
        lines += ["default interface Ethernet0/3", "interface Ethernet0/3", "shutdown"]
    if "vrf definition NCV" in body:
        lines.append("no vrf definition NCV")
    return lines


def ospf_check(dev, name):
    return ospf_neighbor_state(dev.execute("show ip ospf neighbor"), OSPF_PEERS[name])


def bgp_check(dev, name):
    return bgp_session_state(dev.execute("show bgp ipv4 unicast summary"), BGP[name]["peer"])


def connect(tb, name):
    dev = tb.devices[name]
    dev.connect(log_stdout=False, init_exec_commands=[], init_config_commands=[])
    return dev


def configure(tb, name, lines, show=None):
    dev = connect(tb, name)
    try:
        dev.configure(lines)
        print(f"{name}: " + "; ".join(lines))
        if show:
            print(dev.execute(show))
    finally:
        dev.disconnect()


def wait(tb, names, check, want, seconds, label) -> int:
    """Poll `check` on every named device every 5 s until all results satisfy `want`."""
    devs = {}
    try:
        for name in names:
            devs[name] = connect(tb, name)
        deadline = time.time() + seconds
        while True:
            states = {name: check(dev, name) for name, dev in devs.items()}
            print(time.strftime("%H:%M:%S"), states, flush=True)
            if all(want(s) for s in states.values()):
                return 0
            if time.time() > deadline:
                print(f"timed out waiting for {label}")
                return 1
            time.sleep(5)
    finally:
        for dev in devs.values():
            dev.disconnect()


def check_hold_time(tb) -> int:
    """Exit 0 only if both sessions run FAST_TIMERS. Timers change at the next session start,
    so a session that was already up when setup-bgp-fast ran keeps the 180 s default."""
    keepalive, hold = FAST_TIMERS
    ok = True
    for name, cfg in BGP.items():
        dev = connect(tb, name)
        try:
            got = bgp_negotiated_timers(dev.execute(f"show bgp ipv4 unicast neighbors {cfg['peer']}"))
        finally:
            dev.disconnect()
        print(f"{name}: negotiated (hold, keepalive) = {got}")
        ok = ok and got == (hold, keepalive)
    if not ok:
        print(
            f"expected hold {hold} s and keepalive {keepalive} s on both peers; reset the session with "
            f"`clear ip bgp {BGP['R1']['peer']}` on R1 or use a fresh reservation"
        )
    return 0 if ok else 1


def reset(tb) -> int:
    """Return R1 and R2 to the shipped configuration, so one reservation can carry runs whose
    setups conflict (a router runs one BGP process). Each router is read before it is changed,
    and one that needs nothing gets no configure at all."""
    for name in ROUTER_IDS:
        dev = connect(tb, name)
        try:
            lines = reset_lines(dev.execute("show running-config"))
            if lines:
                dev.configure(lines)
                print(f"{name}: " + "; ".join(lines))
            else:
                print(f"{name}: nothing to reset")
        finally:
            dev.disconnect()
    return 0


def _send(name, lines, show=None):
    """A command that sends fixed lines to one router."""

    def run(tb, seconds):
        configure(tb, name, list(lines), show=show)
        return 0

    return run


def _setup_on_both(build):
    """A command that sends each router the lines `build(name)` gives it."""

    def run(tb, seconds):
        for name in ROUTER_IDS:
            configure(tb, name, build(name))
        return 0

    return run


def _wait_for(names, check, want, label):
    def run(tb, seconds):
        return wait(tb, names, check, want, seconds, label)

    return run


_LINK = "interface Ethernet0/1"  # the R1-R2 link
_R1_PEER = f"neighbor {BGP['R1']['peer']} shutdown"
_R1_BGP = f"router bgp {BGP['R1']['asn']}"
_BGP_SUMMARY = "show bgp ipv4 unicast summary"

# name -> (what the usage line shows, run(testbed, seconds) -> exit code), in usage order.
COMMANDS: dict[str, tuple[str, Callable[[Any, int], int]]] = {
    "setup-ospf": ("setup-ospf", _setup_on_both(ospf_setup_lines)),
    "shut": ("shut", _send("R1", [_LINK, "shutdown"], "show ip interface brief")),
    "noshut": ("noshut", _send("R1", [_LINK, "no shutdown"], "show ip interface brief")),
    "wait-full": (
        "wait-full [seconds]",
        _wait_for(OSPF_PEERS, ospf_check, lambda s: s is True, "both OSPF neighbors FULL"),
    ),
    "wait-gone": (
        "wait-gone [seconds]",
        _wait_for(OSPF_PEERS, ospf_check, lambda s: s is None, "the OSPF neighbors to clear"),
    ),
    "setup-bgp": ("setup-bgp", _setup_on_both(bgp_setup_lines)),
    "bgp-shut": ("bgp-shut", _send("R1", [_R1_BGP, _R1_PEER], _BGP_SUMMARY)),
    "bgp-noshut": ("bgp-noshut", _send("R1", [_R1_BGP, f"no {_R1_PEER}"], _BGP_SUMMARY)),
    "wait-bgp-up": (
        "wait-bgp-up [seconds]",
        _wait_for(BGP, bgp_check, lambda s: s is True, "both BGP sessions Established"),
    ),
    "wait-bgp-down": (
        "wait-bgp-down [seconds]",
        _wait_for(BGP, bgp_check, lambda s: s is not True, "both BGP sessions to leave Established"),
    ),
    "setup-bgp-fast": ("setup-bgp-fast", _setup_on_both(lambda name: bgp_setup_lines(name, FAST_TIMERS))),
    "check-hold-time": ("check-hold-time", lambda tb, seconds: check_hold_time(tb)),
    "bgp-block": ("bgp-block", _send("R1", bgp_block_lines(), _BGP_SUMMARY)),
    "bgp-unblock": ("bgp-unblock", _send("R1", bgp_unblock_lines(), _BGP_SUMMARY)),
    "reset": ("reset", lambda tb, seconds: reset(tb)),
}
USAGE = "usage: labctl.py " + " | ".join(usage for usage, _ in COMMANDS.values())


def load_testbed(path):
    from genie.testbed import load  # the lab extra, needed only past this point

    return load(str(path))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(USAGE)
        return 2
    try:
        seconds = int(argv[2]) if len(argv) > 2 else 120
    except ValueError:
        print(USAGE)
        return 2
    _, run = COMMANDS[argv[1]]
    return run(load_testbed(testbed_path(os.environ)), seconds)


if __name__ == "__main__":
    sys.exit(main())
