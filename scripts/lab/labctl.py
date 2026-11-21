"""Operator-side actions on the DevNet CML default-lab, deliberately outside ncv.

ncv never pushes configuration. These are the hands that set each run up in the lab and make
its one planned change, so the captures around it have something to catch, and `reset` takes
it all away again. Isolated lab only.

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
  labctl.py setup-ospf-fast           setup-ospf with a 1 s hello on Ethernet0/1 of both routers
  labctl.py check-dead-time           exit 1 unless both routers report Hello 1, Dead 4 on Ethernet0/1
  labctl.py ospf-block | ospf-unblock  add / remove an inbound ACL on R1 Ethernet0/1 that drops OSPF from R2
  labctl.py wait-ospf-lost [seconds]  poll until neither router has its OSPF neighbor FULL
  labctl.py setup-ibgp                iBGP in AS 65010 between the loopbacks, which reach each other over OSPF
  labctl.py wait-ibgp-up [seconds]    poll until both iBGP sessions are Established and have learned a prefix
  labctl.py wait-ibgp-down [seconds]  poll until neither iBGP session is Established
  labctl.py check-ibgp-hold-time      exit 1 unless both iBGP sessions negotiated the 9 s hold time
  labctl.py wait-vrf-gone [seconds]   poll until neither router lists vrf NCV (IOS deletes a VRF slowly)
  labctl.py setup-vrf                 add eBGP in vrf NCV on Ethernet0/1.100 to setup-bgp-fast's BGP process
  labctl.py wait-vrf-bgp-up [seconds]  poll until both vrf NCV sessions are Established and have a prefix
  labctl.py wait-vrf-bgp-down [seconds]  poll until neither vrf NCV session is Established
  labctl.py check-vrf-hold-time       exit 1 unless both vrf NCV sessions negotiated the 9 s hold time
  labctl.py vrf-shut | vrf-noshut     shutdown / no shutdown on R1 Ethernet0/1.100
  labctl.py reset                     remove what these scripts add from R1 and R2, back to what ships
  labctl.py probe                     print what a fixed list of read-only commands shows on R1 and R2

The testbed is the file NCV_TESTBED names (a relative path is read from the repository root),
or testbeds/lab.yaml under the repository root when NCV_TESTBED is unset or empty, wherever
this is run from. `probe` changes nothing: it only reads, and it leaves out `show running-config`,
which holds the passwords. The check-* commands print each show command and the raw text they parsed
before their reading, so a run's log keeps that text. Genie is imported only when a command
runs, so the show-output parsers, the planned configuration lines, and the command table here
can be tested without the lab extra installed.
"""

import os
import re
import sys
import time
from collections.abc import Callable
from ipaddress import ip_interface, ip_network
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
EBGP_PEERS = {name: cfg["peer"] for name, cfg in BGP.items()}
# The hold-timer run: keepalive and hold time in seconds. 9 s instead of IOS's default 180 s, so
# the session drops seconds after BGP stops arriving rather than three minutes later.
FAST_TIMERS = (3, 9)
# The hold-timer run's change: an inbound ACL on R1's side of the link that drops TCP port 179
# from R2 in both directions of the session, whichever router opened the TCP connection, and
# passes everything else. Inbound interface ACLs also filter traffic addressed to the router.
BLOCK_ACL = "NCV-BLOCK-BGP"
BLOCK_INTERFACE = "Ethernet0/1"
# The dead-timer run: the OSPF hello interval in seconds on the link, 1 s instead of IOS's 10 s.
# IOS then sets the dead interval to four hellos by itself (4 s instead of 40 s), so R1 gives up
# on R2 seconds after OSPF stops arriving. Only the hello is configured: IOS writes just that
# line into the running config, and whether it would also store a dead interval equal to the
# derived one is not known, while the run's intent has to match the running config exactly.
OSPF_FAST_HELLO = 1
# The dead-timer run's change: an inbound ACL on R1's side of the link that drops every OSPF
# packet from R2 (hellos to 224.0.0.5 and the unicast exchange alike) and passes everything else.
OSPF_BLOCK_ACL = "NCV-BLOCK-OSPF"
# The iBGP run: both routers in one AS, the session between their Loopback0 addresses. Loopback0
# goes into OSPF, the only way either router reaches the other's, so the session depends on
# OSPF. Loopback1 exists to give BGP a prefix to originate; it is not part of the underlay and
# stays out of OSPF. None of these overlaps the lab's own subnets.
IBGP_ASN = 65010
LOOPBACKS = {
    "R1": {"Loopback0": "10.255.255.1/32", "Loopback1": "172.16.1.1/24"},
    "R2": {"Loopback0": "10.255.255.2/32", "Loopback1": "172.16.2.1/24"},
}
# What each router originates into BGP: its Loopback1 subnet. No static route the lab ships with
# covers 172.16.0.0/16, so unlike the eBGP runs the peer should install the prefix, and its loss
# should show in the routing table.
IBGP_PREFIXES = {name: ip_interface(loopbacks["Loopback1"]).network for name, loopbacks in LOOPBACKS.items()}
# Each router's iBGP peer: the other router's Loopback0.
IBGP_PEERS = {
    name: str(ip_interface(LOOPBACKS[other]["Loopback0"]).ip) for name, other in (("R1", "R2"), ("R2", "R1"))
}
# The BGP VRF run: a second eBGP session between the same two routers, inside vrf NCV on a
# dot1Q subinterface of the link, next to the hold-timer run's session in the global table.
VRF = "NCV"
VRF_VLAN = 100
VRF_INTERFACE = "Ethernet0/1.100"
VRF_LOOPBACK = "Loopback100"
# The subinterface reuses the link's own addresses (each router's address is the other's `peer`
# in BGP). That is the point: the same neighbor address is then a BGP peer twice on each router,
# once in each table, and only the VRF tells the two sessions apart.
VRF_ADDRESSES = {name: BGP[other]["peer"] for name, other in (("R1", "R2"), ("R2", "R1"))}
# What each router originates into the VRF session: its Loopback100 subnet, in vrf NCV only.
VRF_LOOPBACKS = {"R1": "172.16.101.1/24", "R2": "172.16.102.1/24"}
# IOS needs a route distinguisher before BGP takes a VRF address family; nothing is imported or
# exported between tables, so no route target is set.
VRF_RD = {name: f"{cfg['asn']}:{VRF_VLAN}" for name, cfg in BGP.items()}
# `show bgp ipv4 unicast ...` lists only the global table; the VRF session is in the VPNv4 one.
VRF_BGP_SUMMARY = f"show bgp vpnv4 unicast vrf {VRF} summary"
VRF_BGP_NEIGHBORS = f"show bgp vpnv4 unicast vrf {VRF} neighbors"
# What the sandbox ships in Ethernet0/3, the one spare port. reset puts it back when a run has
# used it; the order IOS lists the two lines in does not matter.
SHIPPED_ETHERNET0_3 = ("no ip address", "shutdown")
# What `probe` runs on each router, in order. Every one only reads; `show running-config` is left
# out because it holds the passwords. A fresh or reset lab runs neither OSPF nor BGP, so nothing
# here asks about them: the check-* commands print that raw text during the runs.
PROBE_COMMANDS = (
    # The management path: whether Ethernet0/2 in vrf Mgmt-intf is up, has its route back through
    # 10.10.20.254 and an ARP entry for it, runs an SSH server, and reaches the gateway and the
    # CML controller. On 2026-09-12 the management addresses did not answer over the VPN, and
    # nobody recorded why.
    "show ip interface brief",
    "show vrf",
    "show ip route vrf Mgmt-intf",
    "show ip arp vrf Mgmt-intf",
    "show ip ssh",
    "show users",
    "ping vrf Mgmt-intf 10.10.20.254 repeat 2",
    "ping vrf Mgmt-intf 10.10.20.161 repeat 2",
    # What Ethernet0/0 and Ethernet0/3 connect to: CDP names any router on the far side, and the
    # spare port's own counters and state show whether anything is attached.
    "show cdp neighbors",
    "show interfaces Ethernet0/3",
    # The software release, which decides which show formats the parsers meet.
    "show version | include Version",
)


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


def bgp_prefixes_received(output: str, peer: str) -> int | None:
    """From `show bgp ipv4 unicast summary`: how many prefixes the session has received when
    it is Established, else None (listed in another state, or not listed). An Established
    session that has learned nothing yet shows 0, which bgp_session_state counts as up."""
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == peer:
            return int(fields[-1]) if fields[-1].isdigit() else None
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


_OSPF_INTERFACE_TIMERS = re.compile(r"Hello (\d+), Dead (\d+)")


def ospf_interface_timers(output: str):
    """From `show ip ospf interface <intf>`: the (hello, dead) intervals in seconds, read from
    the line `Timer intervals configured, Hello 1, Dead 4, Wait 4, Retransmit 5`, or None if
    the output has no such line (OSPF is not enabled on the interface). Genie's IOS XE parser
    documents the same line, with Hello 10, Dead 40 for the defaults. Only the two numbers are
    matched on that line, since some IOS XE trains append more timers to it."""
    for line in output.splitlines():
        match = _OSPF_INTERFACE_TIMERS.search(line) if "Timer intervals configured" in line else None
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def vrf_listed(output: str, vrf: str) -> bool:
    """From `show vrf`: whether `vrf` has a row, its name being the row's first field. A VRF with
    several interfaces continues on lines holding one interface name each, which a row, with
    at least its name and route distinguisher, cannot be mistaken for."""
    return any(len(fields) > 1 and fields[0] == vrf for fields in map(str.split, output.splitlines()))


def ospf_setup_lines(name: str, hello=None) -> list[str]:
    """The configuration setup-ospf sends to one router: OSPF area 0 on the R1-R2 link. With
    `hello` (seconds), setup-ospf-fast first sets that hello interval on the link, so the
    adjacency forms with the fast timers instead of changing them under a live one."""
    timers = [f"interface {BLOCK_INTERFACE}", f"ip ospf hello-interval {hello}"] if hello else []
    return timers + ["router ospf 1", f"router-id {ROUTER_IDS[name]}", "network 1.1.1.0 0.0.0.255 area 0"]


def _bgp_lines(name: str, asn: int, peer: str, peer_asn: int, prefix, timers=None, source=None) -> list[str]:
    """One router's BGP process with one peer, originating `prefix` (an IPv4 network). With
    `source`, the session runs from that interface's address; with `timers` (keepalive, hold
    time), the per-neighbor timers line."""
    lines = [
        f"router bgp {asn}",
        f"bgp router-id {ROUTER_IDS[name]}",
        "bgp log-neighbor-changes",
        f"neighbor {peer} remote-as {peer_asn}",
    ]
    if source:
        lines.append(f"neighbor {peer} update-source {source}")
    if timers:
        lines.append(f"neighbor {peer} timers {timers[0]} {timers[1]}")
    return lines + [
        "address-family ipv4",
        f"network {prefix.network_address} mask {prefix.netmask}",
        f"neighbor {peer} activate",
        # lets Genie's learn read received-routes instead of an error line
        f"neighbor {peer} soft-reconfiguration inbound",
        "exit-address-family",
    ]


def bgp_setup_lines(name: str, timers=None) -> list[str]:
    """The configuration setup-bgp sends to one router; with `timers` (keepalive, hold time),
    also the per-neighbor timers line setup-bgp-fast adds."""
    cfg = BGP[name]
    lan = ip_network(f"{cfg['network']}/24")
    return _bgp_lines(name, cfg["asn"], cfg["peer"], cfg["peer_asn"], lan, timers)


def ibgp_setup_lines(name: str) -> list[str]:
    """The configuration setup-ibgp sends to one router: its two loopbacks, setup-ospf-fast's
    lines with Loopback0 added to area 0, and iBGP to the peer's Loopback0, sourced from this
    router's own, with the hold-timer run's timers. The session forms only once OSPF has
    carried each Loopback0 to the other router."""
    addresses = []
    for interface, cidr in LOOPBACKS[name].items():
        address = ip_interface(cidr)
        addresses += [f"interface {interface}", f"ip address {address.ip} {address.netmask}"]
    source = ip_interface(LOOPBACKS[name]["Loopback0"]).ip
    ospf = ospf_setup_lines(name, OSPF_FAST_HELLO) + [f"network {source} 0.0.0.0 area 0"]
    peer = IBGP_PEERS[name]
    bgp = _bgp_lines(name, IBGP_ASN, peer, IBGP_ASN, IBGP_PREFIXES[name], FAST_TIMERS, "Loopback0")
    return addresses + ospf + bgp


def vrf_setup_lines(name: str) -> list[str]:
    """The configuration setup-vrf sends to one router, added to setup-bgp-fast's BGP process:
    vrf NCV, the subinterface and Loopback100 in it, and the VRF session with the hold-timer
    run's timers. The order is forced: the route distinguisher before BGP's VRF address family,
    the dot1Q tag before any address on the subinterface, and `vrf forwarding` before
    `ip address`, since it strips an address already there and the global table would refuse
    the link's own subnet a second time."""
    cfg, peer = BGP[name], BGP[name]["peer"]
    link = ip_interface(f"{VRF_ADDRESSES[name]}/24")
    loopback = ip_interface(VRF_LOOPBACKS[name])
    return [
        f"vrf definition {VRF}",
        f"rd {VRF_RD[name]}",
        "address-family ipv4",
        "exit-address-family",
        f"interface {VRF_INTERFACE}",
        f"encapsulation dot1Q {VRF_VLAN}",
        f"vrf forwarding {VRF}",
        f"ip address {link.ip} {link.netmask}",
        f"interface {VRF_LOOPBACK}",
        f"vrf forwarding {VRF}",
        f"ip address {loopback.ip} {loopback.netmask}",
        f"router bgp {cfg['asn']}",
        f"address-family ipv4 vrf {VRF}",
        f"neighbor {peer} remote-as {cfg['peer_asn']}",
        f"neighbor {peer} timers {FAST_TIMERS[0]} {FAST_TIMERS[1]}",
        f"neighbor {peer} activate",
        f"neighbor {peer} soft-reconfiguration inbound",
        f"network {loopback.network.network_address} mask {loopback.netmask}",
        "exit-address-family",
    ]


def vrf_shut_lines() -> list[str]:
    """The BGP VRF run's change on R1: the VRF's subinterface goes down, the link stays up."""
    return [f"interface {VRF_INTERFACE}", "shutdown"]


def vrf_noshut_lines() -> list[str]:
    """The undo for vrf_shut_lines."""
    return [f"interface {VRF_INTERFACE}", "no shutdown"]


def _block_lines(acl: str, entries: list[str]) -> list[str]:
    """An ACL whose `entries` drop what a run blocks and whose last line passes everything else,
    then its inbound binding on the link. `exit` leaves ACL mode before the interface line."""
    return [
        f"ip access-list extended {acl}",
        *entries,
        "permit ip any any",
        "exit",
        f"interface {BLOCK_INTERFACE}",
        f"ip access-group {acl} in",
    ]


def _unblock_lines(acl: str) -> list[str]:
    """The undo for _block_lines: unbind the ACL first, then delete it."""
    return [
        f"interface {BLOCK_INTERFACE}",
        f"no ip access-group {acl} in",
        "exit",
        f"no ip access-list extended {acl}",
    ]


def bgp_block_lines() -> list[str]:
    """The hold-timer run's change on R1: the ACL, then its inbound binding on the link."""
    local, remote = BGP["R2"]["peer"], BGP["R1"]["peer"]
    return _block_lines(
        BLOCK_ACL,
        [f"deny tcp host {remote} host {local} eq bgp", f"deny tcp host {remote} eq bgp host {local}"],
    )


def bgp_unblock_lines() -> list[str]:
    """The undo for bgp_block_lines: unbind the ACL first, then delete it."""
    return _unblock_lines(BLOCK_ACL)


def ospf_block_lines() -> list[str]:
    """The dead-timer run's change on R1: the ACL, then its inbound binding on the link. One
    deny line covers every destination R2's OSPF uses: 224.0.0.5, 224.0.0.6, and R1 itself."""
    return _block_lines(OSPF_BLOCK_ACL, [f"deny ospf host {BGP['R1']['peer']} any"])


def ospf_unblock_lines() -> list[str]:
    """The undo for ospf_block_lines: unbind the ACL first, then delete it."""
    return _unblock_lines(OSPF_BLOCK_ACL)


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
# The BGP processes and interfaces the scripts create, by name, so reset never removes one a
# reservation shipped with or an operator added: the eBGP runs' AS 65001 and 65002, the iBGP
# run's AS 65010, the iBGP loopbacks, and the VRF run's loopback and subinterface.
_ADDED_BGP = frozenset(f"router bgp {asn}" for asn in (*(cfg["asn"] for cfg in BGP.values()), IBGP_ASN))
_ADDED_INTERFACES = frozenset(
    f"interface {name}" for name in [*LOOPBACKS["R1"], *LOOPBACKS["R2"], VRF_LOOPBACK, VRF_INTERFACE]
)
_LINK_RESETS = (
    ("shutdown", "no shutdown"),
    ("ip ospf hello-interval", "no ip ospf hello-interval"),
    ("ip ospf dead-interval", "no ip ospf dead-interval"),
)


def reset_lines(running_config: str) -> list[str]:
    """The configuration that undoes the lab scripts' work on one router, read from its
    running config. A line is emitted only for something present, unbinding before deleting,
    so a config the sandbox shipped gives []. BGP processes and interfaces are removed only
    when they carry a name the scripts create, so one a reservation ships with stays.
    Mgmt-intf, Ethernet0/0 and 0/2, the static routes, users, and lines are never touched:
    they are how the scripts reach the routers."""
    blocks = config_blocks(running_config)
    body = dict(blocks)
    lines: list[str] = []
    for head, children in blocks:
        if head.startswith("interface "):
            bound = [m for m in map(_ACCESS_GROUP.fullmatch, children) if m]
            if bound:
                lines += [head, *(f"no ip access-group {m.group(1)} {m.group(2)}" for m in bound)]
    lines += [f"no {head}" for head, _ in blocks if _ACCESS_LIST.fullmatch(head)]
    lines += [f"no {head}" for head, _ in blocks if head in _ADDED_BGP]
    if "router ospf 1" in body:
        lines.append("no router ospf 1")
    link = body.get("interface Ethernet0/1", ())
    undo = [no for prefix, no in _LINK_RESETS if any(c.startswith(prefix) for c in link)]
    if undo:
        lines += ["interface Ethernet0/1", *undo]
    lines += [f"no {head}" for head, _ in blocks if head in _ADDED_INTERFACES]
    spare = body.get("interface Ethernet0/3")
    if spare is not None and sorted(c for c in spare if c != "!") != sorted(SHIPPED_ETHERNET0_3):
        lines += ["default interface Ethernet0/3", "interface Ethernet0/3", "shutdown"]
    if "vrf definition NCV" in body:
        lines.append("no vrf definition NCV")
    return lines


def ospf_check(dev, name):
    return ospf_neighbor_state(dev.execute("show ip ospf neighbor"), OSPF_PEERS[name])


_BGP_SUMMARY = "show bgp ipv4 unicast summary"


def bgp_check(peers, read=bgp_session_state, summary=_BGP_SUMMARY):
    """A wait check on one BGP table: `read` applied to each router's `summary` output for its
    peer in `peers`. By default it reads whether the session in the global table is
    Established; the VRF table prints its summary in the same format."""

    def check(dev, name):
        return read(dev.execute(summary), peers[name])

    return check


def vrf_check(dev, name):
    return vrf_listed(dev.execute("show vrf"), VRF)


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


def show_on(tb, name, command) -> str:
    """One show command on one router, disconnecting whatever happens."""
    dev = connect(tb, name)
    try:
        return dev.execute(command)
    finally:
        dev.disconnect()


def echoed(name: str, command: str, output: str) -> str:
    """The command as a router prompt would show it, then its output exactly as it came, for a
    run's log. No saved capture holds the text the check-* commands parse, and a fresh lab runs
    neither OSPF nor BGP, so a run's own log is the only place that text can be recorded."""
    return f"{name}# {command}\n{output}" + ("" if output.endswith("\n") else "\n")


def show_and_echo(tb, name, command) -> str:
    """show_on, printing the command and the raw output it returned before handing it back."""
    output = show_on(tb, name, command)
    print(echoed(name, command, output), end="")
    return output


def check_hold_time(tb, peers, neighbors="show bgp ipv4 unicast neighbors", clear="clear ip bgp") -> int:
    """Exit 0 only if each router's session to its peer in `peers` runs FAST_TIMERS, read from
    `<neighbors> <peer>`; `clear` is the command the advice names for resetting R1's session.
    Timers change at the next session start, so a session that was already up when the timers
    were configured keeps the 180 s default."""
    keepalive, hold = FAST_TIMERS
    ok = True
    for name, peer in peers.items():
        got = bgp_negotiated_timers(show_and_echo(tb, name, f"{neighbors} {peer}"))
        print(f"{name}: negotiated (hold, keepalive) = {got}")
        ok = ok and got == (hold, keepalive)
    if not ok:
        print(
            f"expected hold {hold} s and keepalive {keepalive} s on both peers; reset the session with "
            f"`{clear} {peers['R1']}` on R1 or use a fresh reservation"
        )
    return 0 if ok else 1


def check_dead_time(tb) -> int:
    """Exit 0 only if both routers run a 1 s hello and the 4 s dead interval IOS derives from it
    on the link. A mismatch on one end means the adjacency would never form, or a stale one from
    a reused reservation is still carrying the old timers."""
    hello, dead = OSPF_FAST_HELLO, 4 * OSPF_FAST_HELLO  # IOS sets the dead interval to four hellos
    ok = True
    for name in ROUTER_IDS:
        got = ospf_interface_timers(show_and_echo(tb, name, f"show ip ospf interface {BLOCK_INTERFACE}"))
        print(f"{name}: {BLOCK_INTERFACE} (hello, dead) = {got}")
        ok = ok and got == (hello, dead)
    if not ok:
        print(
            f"expected Hello {hello} s and Dead {dead} s on {BLOCK_INTERFACE} of both routers; "
            "`labctl.py reset` followed by `labctl.py setup-ospf-fast` gives a clean start"
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


def probe(tb) -> int:
    """Run PROBE_COMMANDS on R1 and then R2, printing each command and its output as it came.
    A command the router rejects is printed with the error and the probe goes on (Unicon raises
    on `% Invalid input`), so it fails only when it cannot connect to a router."""
    failed = []
    for name in ROUTER_IDS:
        try:
            dev = connect(tb, name)
        except Exception as err:  # whatever Unicon raises, the console path itself is broken
            print(f"{name}: could not connect: {type(err).__name__}: {err}")
            failed.append(name)
            continue
        try:
            for command in PROBE_COMMANDS:
                try:
                    output = dev.execute(command)
                except Exception as err:
                    print(f"{name}# {command}: {type(err).__name__}: {err}")
                    continue
                print(echoed(name, command, output), end="")
        finally:
            dev.disconnect()
    return 1 if failed else 0


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
_OSPF_NEIGHBORS = "show ip ospf neighbor"

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
        _wait_for(BGP, bgp_check(EBGP_PEERS), lambda s: s is True, "both BGP sessions Established"),
    ),
    "wait-bgp-down": (
        "wait-bgp-down [seconds]",
        _wait_for(
            BGP, bgp_check(EBGP_PEERS), lambda s: s is not True, "both BGP sessions to leave Established"
        ),
    ),
    "setup-bgp-fast": ("setup-bgp-fast", _setup_on_both(lambda name: bgp_setup_lines(name, FAST_TIMERS))),
    "check-hold-time": ("check-hold-time", lambda tb, seconds: check_hold_time(tb, EBGP_PEERS)),
    "bgp-block": ("bgp-block", _send("R1", bgp_block_lines(), _BGP_SUMMARY)),
    "bgp-unblock": ("bgp-unblock", _send("R1", bgp_unblock_lines(), _BGP_SUMMARY)),
    "setup-ospf-fast": (
        "setup-ospf-fast",
        _setup_on_both(lambda name: ospf_setup_lines(name, OSPF_FAST_HELLO)),
    ),
    "check-dead-time": ("check-dead-time", lambda tb, seconds: check_dead_time(tb)),
    "ospf-block": ("ospf-block", _send("R1", ospf_block_lines(), _OSPF_NEIGHBORS)),
    "ospf-unblock": ("ospf-unblock", _send("R1", ospf_unblock_lines(), _OSPF_NEIGHBORS)),
    # wait-gone would never finish after ospf-block: R2 still hears R1 and keeps its entry,
    # in a state other than FULL, while R1 drops R2 when its dead timer runs out.
    "wait-ospf-lost": (
        "wait-ospf-lost [seconds]",
        _wait_for(OSPF_PEERS, ospf_check, lambda s: s is not True, "both OSPF neighbors to leave FULL"),
    ),
    "setup-ibgp": ("setup-ibgp", _setup_on_both(ibgp_setup_lines)),
    # Established is not enough here: a session that has just come up may have learned nothing
    # yet (a prefix count of 0), and the captures follow this wait closely, so it waits for at
    # least one learned prefix on both routers.
    "wait-ibgp-up": (
        "wait-ibgp-up [seconds]",
        _wait_for(
            IBGP_PEERS,
            bgp_check(IBGP_PEERS, bgp_prefixes_received),
            lambda count: count is not None and count >= 1,
            "both iBGP sessions Established with a prefix learned",
        ),
    ),
    "wait-ibgp-down": (
        "wait-ibgp-down [seconds]",
        _wait_for(
            IBGP_PEERS,
            bgp_check(IBGP_PEERS),
            lambda s: s is not True,
            "both iBGP sessions to leave Established",
        ),
    ),
    "check-ibgp-hold-time": ("check-ibgp-hold-time", lambda tb, seconds: check_hold_time(tb, IBGP_PEERS)),
    # reset removes vrf NCV, and IOS finishes deleting a VRF in the background, refusing its
    # route distinguisher until then, so setup-vrf right after reset would fail.
    "wait-vrf-gone": (
        "wait-vrf-gone [seconds]",
        _wait_for(
            ROUTER_IDS, vrf_check, lambda listed: not listed, f"vrf {VRF} to be deleted on both routers"
        ),
    ),
    "setup-vrf": ("setup-vrf", _setup_on_both(vrf_setup_lines)),
    # As with the iBGP run: the intent names the prefix each VRF session learns, so the wait is
    # for a learned prefix, not for Established alone.
    "wait-vrf-bgp-up": (
        "wait-vrf-bgp-up [seconds]",
        _wait_for(
            BGP,
            bgp_check(EBGP_PEERS, bgp_prefixes_received, VRF_BGP_SUMMARY),
            lambda count: count is not None and count >= 1,
            f"both vrf {VRF} BGP sessions Established with a prefix learned",
        ),
    ),
    "wait-vrf-bgp-down": (
        "wait-vrf-bgp-down [seconds]",
        _wait_for(
            BGP,
            bgp_check(EBGP_PEERS, summary=VRF_BGP_SUMMARY),
            lambda s: s is not True,
            f"both vrf {VRF} BGP sessions to leave Established",
        ),
    ),
    "check-vrf-hold-time": (
        "check-vrf-hold-time",
        lambda tb, seconds: check_hold_time(tb, EBGP_PEERS, VRF_BGP_NEIGHBORS, f"clear ip bgp vrf {VRF}"),
    ),
    "vrf-shut": ("vrf-shut", _send("R1", vrf_shut_lines(), VRF_BGP_SUMMARY)),
    "vrf-noshut": ("vrf-noshut", _send("R1", vrf_noshut_lines(), VRF_BGP_SUMMARY)),
    "reset": ("reset", lambda tb, seconds: reset(tb)),
    "probe": ("probe", lambda tb, seconds: probe(tb)),
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
