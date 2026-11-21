"""The CML side of the lab: a read-only inventory, and adding or removing R3, the second platform.

Two things decide what the next runs can do, and nothing in the repository may guess either:
which node definitions and images this controller has, and whether R1 Ethernet0/3, the spare
port, is free for a new link. `inspect` asks the CML 2.7 REST API (/api/v0) and prints what it
finds, ending with those two answers, each "yes", "no", or "unknown" with the line it rests
on. Given a directory, it also saves each response there as one JSON file.

Usage, with the CML login in NCV_CML_USER and NCV_CML_PASS (probe.sh and the run scripts ask):
  cml_lab.py inspect [<output dir>]   read-only: print the inventory; with a directory, save each response
  cml_lab.py check-login              read-only: exit 0 when CML accepts the login, 1 when it does not
  cml_lab.py add-r3 <platform>        add R3 (nxosv9000, cat8000v, or iosv), link it to R1 Ethernet0/3, boot
  cml_lab.py remove-r3                stop, wipe, and delete R3 and its link
  cml_lab.py platform-os <platform>   print the pyATS os of a platform's R3 (no login, no call)

The controller is NCV_CML_HOST (default 10.10.20.161) and the lab NCV_CML_LAB (default
default-lab), read the way cml_capture.py reads them. `inspect` and `check-login` only read:
every call is a GET. Node configurations hold the routers' passwords, so the inventory asks for
the topology without them, never calls /labs/{id}/nodes/{id}, and drops `configuration`, notes,
and descriptions from every response before anything is printed or saved; the /authenticate
response is never saved. Several response shapes are documented nowhere this repository can
check, so every field is read as optional and printed as unknown when it is absent. A call that
fails is reported and skipped; the exit code is 1 only when the login or finding the lab fails.

`add-r3` and `remove-r3` change the lab's topology, the only scripts here that do. add-r3 gives
R3 a day-0 configuration with an admin login whose password is NCV_LAB_PASS; that value is
never printed, saved, or logged: the configuration is echoed as it would be with "<removed>"
for the password, the node POST's response is never printed, and every message this script
prints passes through `redact`. It stops with exit 1 and a one-line reason at the first thing
that is not as it needs, and once R3 exists every such line ends by naming remove-r3. The
request paths and bodies come from Cisco's own client (virl2_client 2.7); which form of
`configuration` the server takes, and whether it links a running IOL node, are assumptions
named where the calls are made. Exit 2 is bad usage or a missing login. Standard library only,
and outside ncv like the rest of scripts/lab.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
from collections.abc import Callable
from ipaddress import ip_interface
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple

# cml_capture.py sits next to this file and scripts/lab is not a package, so the script's own
# directory goes on the import path before the import, which therefore cannot be at the top.
HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import cml_capture  # noqa: E402

# labctl.py holds R1's side of the R3 link: its addresses, AS numbers, and timers.
import labctl  # noqa: E402

USAGE = (
    "usage: cml_lab.py inspect [<output dir>] | check-login | add-r3 <platform> | remove-r3"
    " | platform-os <platform>"
)
# A node's configuration holds the routers' passwords, and sample labs write access details into
# notes and descriptions, so these keys are dropped at any depth.
DROPPED = frozenset({"configuration", "notes", "description", "lab_notes", "lab_description"})
# The controller-wide calls, by the name each response is saved under.
SYSTEM_CALLS = (
    ("system_information", "/system_information"),
    ("system_stats", "/system_stats"),
    ("licensing", "/licensing"),
    ("node_definitions", "/node_definitions/"),
    ("image_definitions", "/image_definitions/"),
)
# The routers' one spare port, the only place a new link could attach without removing one.
SPARE = ("R1", labctl.R3_LINK["interface"])
UNKNOWN = "unknown"
# What reading a response of another shape than expected raises.
SHAPE_ERRORS = (AttributeError, KeyError, TypeError, ValueError)


def topology_path(lab_id: str) -> str:
    return f"/labs/{lab_id}/topology?exclude_configurations=true"


def state_path(lab_id: str, node_id: str) -> str:
    return f"/labs/{lab_id}/nodes/{node_id}/state"


def scrub(value):
    """A copy of a parsed response without the DROPPED keys, at any depth."""
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if key not in DROPPED}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def fetch(get, path: str):
    """(scrubbed response, None), or (None, "<path>: <error>") when the call fails."""
    try:
        return scrub(get(path)), None
    except (OSError, ValueError) as err:  # URLError and HTTPError are OSErrors
        return None, f"{path}: {err}"


def node_ids(topology) -> list[str]:
    return [node["id"] for node in _items(topology.get("nodes", []))]


def inspect(get, title: str) -> tuple[dict, list[str]]:
    """(inventory, failure lines), read through `get(path) -> parsed JSON`. The inventory holds
    the lab, each response that arrived by its SYSTEM_CALLS name or as `topology`, and
    `node_states` by node id. Raises LookupError when the lab is not found, and OSError or
    ValueError when the labs cannot be listed."""
    lab_id = cml_capture.find_lab([get(f"/labs/{lab}") for lab in get("/labs")], title)
    data: dict = {"lab": {"id": lab_id, "title": title}, "node_states": {}}
    failures: list[str] = []
    for name, path in SYSTEM_CALLS:
        response, failure = fetch(get, path)
        if failure:
            failures.append(failure)
        else:
            data[name] = response
    topology, failure = fetch(get, topology_path(lab_id))
    if failure:
        return data, [*failures, failure]
    data["topology"] = topology
    try:
        ids = node_ids(topology)
    except SHAPE_ERRORS:
        return data, [*failures, f"unexpected response shape from {topology_path(lab_id)}"]
    for node_id in ids:
        state, failure = fetch(get, state_path(lab_id, node_id))
        if failure:
            failures.append(failure)
        else:
            data["node_states"][node_id] = state
    return data, failures


def saved_files(data: dict) -> dict[str, object]:
    """File name -> response, one per call that arrived. The lab lookup is not among them."""
    files = {f"{name}.json": data[name] for name, _ in SYSTEM_CALLS if name in data}
    if "topology" in data:
        files["topology.json"] = data["topology"]
    for node_id, state in data.get("node_states", {}).items():
        files[f"node-{node_id}-state.json"] = state
    return files


def _items(value) -> list:
    if not isinstance(value, list):
        raise TypeError(f"expected a list, got {type(value).__name__}")
    return value


def _dig(value, *keys):
    """value[k1][k2]..., or None where a level is missing or not an object."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _show(value) -> str:
    return UNKNOWN if value is None else str(value)


def _ident(item):
    """A node or image definition's id: the item itself when the list holds bare ids."""
    return item if isinstance(item, str) else item.get("id")


def _version(data: dict) -> list[str]:
    return [f"CML version: {_show(_dig(data.get('system_information'), 'version'))}"]


def _licensing(data: dict) -> list[str]:
    licensing = data.get("licensing")
    registration = _show(_dig(licensing, "registration", "status"))
    authorization = _show(_dig(licensing, "authorization", "status"))
    return [f"licensing: registration {registration}, authorization {authorization}"]


def _usage(data: dict) -> list[str]:
    stats = data.get("system_stats")
    used, total = _dig(stats, "all", "memory", "used"), _dig(stats, "all", "memory", "total")
    return [
        f"controller memory: {_show(used)} used of {_show(total)}, as the API counts it",
        f"controller CPU in use: {_show(_dig(stats, 'all', 'cpu', 'percent'))} %",
    ]


def _node_definitions(data: dict) -> list[str]:
    if "node_definitions" not in data:
        return [f"node definitions: {UNKNOWN}"]
    lines = []
    for item in _items(data["node_definitions"]):
        if isinstance(item, str):
            lines.append(f"node definition {item}: RAM {UNKNOWN}, CPUs {UNKNOWN}, interfaces {UNKNOWN}")
            continue
        ram, cpus = _dig(item, "sim", "linux_native", "ram"), _dig(item, "sim", "linux_native", "cpus")
        physical = _dig(item, "device", "interfaces", "physical")
        naming = (
            f"{physical[0]} to {physical[-1]} ({len(physical)})"
            if isinstance(physical, list) and physical
            else UNKNOWN
        )
        ident = _show(item.get("id"))
        lines.append(f"node definition {ident}: RAM {_show(ram)}, CPUs {_show(cpus)}, interfaces {naming}")
    return lines or ["node definitions: none listed"]


def _image_node_definition(image: dict):
    return image.get("node_definition_id", image.get("node_definition"))


def _image_definitions(data: dict) -> list[str]:
    if "image_definitions" not in data:
        return [f"image definitions: {UNKNOWN}"]
    lines = [
        f"image definition {_show(_ident(image))}: node definition {_show(_image_node_definition(image))}"
        for image in _items(data["image_definitions"])
    ]
    return lines or ["image definitions: none listed"]


def _parts(topology) -> tuple[dict, dict, list | None]:
    """(node id -> node, interface id -> interface with its node id, links or None when the
    topology has no link list). Interfaces may be nested under each node or listed at the top."""
    nodes = {node["id"]: node for node in _items(topology.get("nodes", []))}
    interfaces = {
        iface["id"]: dict(iface, node=node_id)
        for node_id, node in nodes.items()
        for iface in _items(node.get("interfaces") or [])
    }
    interfaces.update({iface["id"]: iface for iface in _items(topology.get("interfaces") or [])})
    links = topology.get("links")
    return nodes, interfaces, None if links is None else _items(links)


def _end(nodes: dict, interfaces: dict, iface_id) -> str:
    iface = interfaces.get(iface_id, {})
    label = _dig(nodes.get(iface.get("node")), "label")
    return f"{_show(label)} {_show(iface.get('label'))}"


def _link_line(nodes, interfaces, link) -> str:
    a = _end(nodes, interfaces, link.get("interface_a"))
    b = _end(nodes, interfaces, link.get("interface_b"))
    return f"link {a} - {b}"


def _linked(links: list) -> set:
    return {link.get(end) for link in links for end in ("interface_a", "interface_b")}


def _interface_line(nodes, iface, links) -> str:
    if links is None:
        connected = "connection unknown"
    else:
        connected = "connected" if iface["id"] in _linked(links) else "not connected"
    label = _show(_dig(nodes.get(iface.get("node")), "label"))
    return f"interface {label} {_show(iface.get('label'))}: slot {_show(iface.get('slot'))}, {connected}"


def _state(data: dict, node_id, node: dict) -> str:
    state = data.get("node_states", {}).get(node_id)
    if isinstance(state, dict):
        state = state.get("state")
    return _show(state if state is not None else node.get("state"))


def _lab(data: dict) -> list[str]:
    title = _show(_dig(data, "lab", "title"))
    if "topology" not in data:
        return [f"lab {title}: topology {UNKNOWN}"]
    nodes, interfaces, links = _parts(data["topology"])
    lines = [f"lab {title}: {len(nodes)} nodes, {UNKNOWN if links is None else len(links)} links"]
    lines += [
        f"node {_show(node.get('label'))}: node definition {_show(node.get('node_definition'))}, "
        f"image {_show(node.get('image_definition'))}, state {_state(data, node_id, node)}"
        for node_id, node in nodes.items()
    ]
    lines += [_interface_line(nodes, iface, links) for iface in interfaces.values()]
    lines += [_link_line(nodes, interfaces, link) for link in links or []]
    return lines


def _spare_interfaces(nodes: dict, interfaces: dict) -> list[dict]:
    """Every interface the topology lists as R1 Ethernet0/3: one, when the lab is as expected."""
    node_label, iface_label = SPARE
    return [
        iface
        for iface in interfaces.values()
        if iface.get("label") == iface_label and _dig(nodes.get(iface.get("node")), "label") == node_label
    ]


def spare_port_answer(data: dict) -> str:
    """Whether R1 Ethernet0/3 is free: yes, no, or unknown, with the line it rests on."""
    node_label, iface_label = SPARE
    question = f"answer: {node_label} {iface_label} is free:"
    if "topology" not in data:
        return f"{question} {UNKNOWN} (no topology response)"
    nodes, interfaces, links = _parts(data["topology"])
    found = _spare_interfaces(nodes, interfaces)
    if len(found) != 1:
        count = f"{len(found)} interfaces {iface_label} on {node_label}"
        return f"{question} {UNKNOWN} (the topology lists {count})"
    if links is None:
        return f"{question} {UNKNOWN} (the topology lists no links)"
    used = [link for link in links if found[0]["id"] in _linked([link])]
    if used:
        return f"{question} no ({_link_line(nodes, interfaces, used[0])})"
    return f"{question} yes ({_interface_line(nodes, found[0], links)})"


def platform_images(data: dict, platform: str) -> tuple[bool, list[str]]:
    """(whether the node definitions list `platform`, the images naming it), read from the
    `node_definitions` and `image_definitions` responses in `data`."""
    defined = platform in {_ident(item) for item in _items(data["node_definitions"])}
    images = [
        _show(_ident(image))
        for image in _items(data["image_definitions"])
        if not isinstance(image, str) and _image_node_definition(image) == platform
    ]
    return defined, images


def platform_answer(data: dict, platform: str) -> str:
    """Whether `platform` is available, meaning it has a node definition and at least one image
    naming that definition: yes, no, or unknown, with the evidence."""
    question = f"answer: {platform} available:"
    missing = [path for name, path in SYSTEM_CALLS[3:] if name not in data]
    if missing:
        return f"{question} {UNKNOWN} (no response from {', '.join(missing)})"
    defined, images = platform_images(data, platform)
    listed = ", ".join(images) or "none"
    if defined and images:
        return f"{question} yes (node definition {platform}; images {listed})"
    if defined:
        return f"{question} no (node definition {platform}, but no image definition names it)"
    return f"{question} no (no node definition {platform}; images naming it: {listed})"


def _guarded(build, data: dict, path: str) -> list[str]:
    try:
        return build(data)
    except SHAPE_ERRORS:
        return [f"unexpected response shape from {path}"]


def describe_inventory(data: dict) -> list[str]:
    """The text report of an inventory `inspect` built. A response of an unexpected shape gives
    one line saying so instead of a traceback, and the rest of the report goes on."""
    topology = topology_path(_show(_dig(data, "lab", "id")))
    definitions = "/node_definitions/ or /image_definitions/"
    sections = [
        (_version, "/system_information"),
        (_licensing, "/licensing"),
        (_usage, "/system_stats"),
        (_node_definitions, "/node_definitions/"),
        (_image_definitions, "/image_definitions/"),
        (_lab, topology),
    ]
    lines = [line for build, path in sections for line in _guarded(build, data, path)]
    lines += _guarded(lambda d: [spare_port_answer(d)], data, topology)
    for platform in PLATFORMS:
        lines += _guarded(lambda d, p=platform: [platform_answer(d, p)], data, definitions)
    return lines


# R3, the second platform: a router of another platform, added to the lab and linked to R1's
# spare port. Its addresses, from research for the run: 3.3.3.3/32 on Loopback0 (in OSPF, and
# the router id) and 172.16.3.1/24 on Loopback1 (originated into BGP); the link is labctl's.
R3 = "R3"
R3_LOOPBACKS = {"Loopback0": f"{labctl.R3_RID}/32", "Loopback1": "172.16.3.1/24"}
# Where R3 is drawn on the lab's canvas; cosmetic.
R3_POSITION = (0, 300)
REMOVED = "<removed>"
MIB = 1024 * 1024
POLL_SECONDS = 15
BOOT_SECONDS = 20 * 60  # an NX-OS 9000v is said to take 5 to 15 minutes; IOSv one to three
NOT_STARTED_SECONDS = 3 * 60  # still QUEUED or DEFINED_ON_CORE this long: CML is not starting it
STOP_SECONDS = 3 * 60
NOT_STARTED = ("QUEUED", "DEFINED_ON_CORE")
STARTING = ("STARTED", "QUEUED")
CREATED = "R3 was created; cml_lab.py remove-r3 removes it"
# What _ask gives instead of failing when a call it may accept that for answers 404 (gone).
GONE = object()


def _r3_link():
    """(R3's address on the link with its prefix length, R1's address, R1's AS)."""
    r1 = ip_interface(labctl.R3_LINK["R1"])
    return ip_interface(f"{labctl.R3_LINK['R3']}/{r1.network.prefixlen}"), r1.ip, labctl.BGP["R1"]["asn"]


def nxos_day0(password: str, interface: str) -> list[str]:
    """R3's day-0 configuration on NX-OS 9000v: the features first, the data port taken out of
    switchport mode and brought up (NX-OS ships both the other way), OSPF enabled per interface,
    and the timers that make the run fast: a 1 s hello and a 4 s dead interval on the link, and
    the hold-timer run's BGP timers. The admin login is the one the console asks for."""
    link, r1, r1_asn = _r3_link()
    keepalive, hold = labctl.FAST_TIMERS
    hello = labctl.OSPF_FAST_HELLO
    return [
        f"hostname {R3}",
        "no password strength-check",
        f"username admin password {password} role network-admin",
        "feature ospf",
        "feature bgp",
        "interface loopback0",
        f"  ip address {R3_LOOPBACKS['Loopback0']}",
        "  ip router ospf 1 area 0.0.0.0",
        "interface loopback1",
        f"  ip address {R3_LOOPBACKS['Loopback1']}",
        f"interface {interface}",
        "  no switchport",
        f"  ip address {link.with_prefixlen}",
        f"  ip ospf hello-interval {hello}",
        f"  ip ospf dead-interval {4 * hello}",
        "  ip router ospf 1 area 0.0.0.0",
        "  no shutdown",
        "router ospf 1",
        f"  router-id {labctl.R3_RID}",
        f"router bgp {labctl.R3_ASN}",
        f"  router-id {labctl.R3_RID}",
        "  address-family ipv4 unicast",
        f"    network {ip_interface(R3_LOOPBACKS['Loopback1']).network}",
        f"  neighbor {r1}",
        f"    remote-as {r1_asn}",
        f"    timers {keepalive} {hold}",
        "    address-family ipv4 unicast",
    ]


def ios_day0(password: str, interface: str) -> list[str]:
    """R3's day-0 configuration on Catalyst 8000V (IOS XE) or IOSv: the same router in IOS
    syntax, with a 1 s hello on the link (IOS derives the 4 s dead interval) and the hold-timer
    run's BGP timers. The console line gets no login, so Unicon meets no login prompt there."""
    link, r1, r1_asn = _r3_link()
    keepalive, hold = labctl.FAST_TIMERS
    loopback0, loopback1 = (ip_interface(R3_LOOPBACKS[name]) for name in ("Loopback0", "Loopback1"))
    return [
        f"hostname {R3}",
        f"username admin privilege 15 secret {password}",
        "interface Loopback0",
        f" ip address {loopback0.ip} {loopback0.netmask}",
        "interface Loopback1",
        f" ip address {loopback1.ip} {loopback1.netmask}",
        f"interface {interface}",
        f" ip address {link.ip} {link.netmask}",
        f" ip ospf hello-interval {labctl.OSPF_FAST_HELLO}",
        " no shutdown",
        "router ospf 1",
        f" router-id {labctl.R3_RID}",
        f" network {link.network.network_address} {link.network.hostmask} area 0",
        f" network {loopback0.ip} 0.0.0.0 area 0",
        f"router bgp {labctl.R3_ASN}",
        f" bgp router-id {labctl.R3_RID}",
        " bgp log-neighbor-changes",
        f" neighbor {r1} remote-as {r1_asn}",
        f" neighbor {r1} timers {keepalive} {hold}",
        " address-family ipv4",
        f"  network {loopback1.network.network_address} mask {loopback1.netmask}",
        f"  neighbor {r1} activate",
        " exit-address-family",
        "line vty 0 4",
        " login local",
        " transport input ssh telnet",
    ]


class Platform(NamedTuple):
    """One platform R3 can be built from: its CML node definition, the pyATS `os` its testbed
    entry needs, the label of its first data interface (the one linked to R1), and the builder
    of its day-0 configuration from (password, that interface)."""

    node_definition: str
    os: str
    first_interface: str
    day0: Callable[[str, str], list[str]]


# In the order the inventory's answers list them. The interface labels are from CML's
# documentation and the research for this run, not from a node this controller created.
PLATFORM_TABLE = MappingProxyType(
    {
        "nxosv9000": Platform("nxosv9000", "nxos", "Ethernet1/1", nxos_day0),
        "cat8000v": Platform("cat8000v", "iosxe", "GigabitEthernet1", ios_day0),
        "iosv": Platform("iosv", "ios", "GigabitEthernet0/0", ios_day0),
    }
)
PLATFORMS = tuple(PLATFORM_TABLE)


def day0_config(platform: str, password: str) -> str:
    """R3's day-0 configuration for `platform`, with `password` as its admin password."""
    entry = PLATFORM_TABLE[platform]
    return "\n".join(entry.day0(password, entry.first_interface)) + "\n"


def redact(text: str, secret: str) -> str:
    """`text` with every occurrence of `secret` replaced; unchanged for an empty secret. Every
    message this script prints goes through it, since a CML validation error can echo the field
    it rejected, and the day-0 configuration holds the admin password."""
    return text.replace(secret, REMOVED) if secret else text


def node_body(platform: str, password: str) -> dict:
    """The body of the node POST. UNVERIFIED: `configuration` as one string. Cisco's client sends
    a string or a list of {"name", "content"} files, and which form CML 2.7.2 keeps is not known;
    add-r3 reads the node back to check, before it starts anything."""
    x, y = R3_POSITION
    return {
        "label": R3,
        "node_definition": PLATFORM_TABLE[platform].node_definition,
        "x": x,
        "y": y,
        "configuration": day0_config(platform, password),
    }


def kept_day0(node) -> bool:
    """Whether the node CML read back holds R3's day-0 configuration, judged by its `hostname R3`
    line, whether CML stores the configuration as one string or as a list of files. A boolean
    only: the configuration itself holds the password."""
    config = node.get("configuration") if isinstance(node, dict) else None
    if isinstance(config, list):
        config = "\n".join(str(item.get("content", "")) for item in config if isinstance(item, dict))
    return isinstance(config, str) and f"hostname {R3}" in (line.strip() for line in config.splitlines())


def memory_check(stats, platform: str, ram_mib) -> tuple[str, bool]:
    """(the line to print, whether free memory is plainly short of what the node definition asks
    for). /system_stats is read as bytes and the node definition's RAM as MiB, which is how
    Cisco's client treats them; neither unit is checked against this controller. When either
    number is missing the check is skipped, and the line says which."""
    used, total = _dig(stats, "all", "memory", "used"), _dig(stats, "all", "memory", "total")
    numbers = {"/system_stats memory": (used, total), f"{platform}'s RAM": (ram_mib,)}
    missing = [name for name, values in numbers.items() if not all(_is_number(v) for v in values)]
    if missing:
        return f"memory check skipped: no {' or '.join(missing)} in the responses", False
    free = int(total - used) // MIB
    line = f"controller memory free: {free} MiB; the {platform} node definition asks for {ram_mib} MiB"
    return line, free < ram_mib


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Refusal(Exception):
    """add-r3 or remove-r3 met something not as it needs: the message says what, in one line."""


def caller(request, host: str, token: str):
    """A `call(method, path, body=None) -> parsed JSON or None` for one session, through
    `request`. An empty reply, as a state change may give, is None."""

    def call(method: str, path: str, body=None):
        reply = request(host, method, path, token, body)
        return json.loads(reply) if reply and reply.strip() else None

    return call


def _ask(call, method: str, path: str, body=None, gone_ok: bool = False):
    """`call`, with a failure turned into a Refusal naming the call (an HTTP error by its code
    only: CML's reply body can echo what it was sent). With `gone_ok`, a 404 gives GONE."""
    try:
        return call(method, path, body)
    except urllib.error.HTTPError as err:
        if gone_ok and err.code == 404:
            return GONE
        raise Refusal(f"{method} {path}: HTTP {err.code}") from None
    except (OSError, ValueError) as err:
        raise Refusal(f"{method} {path}: {err}") from None


def _find_lab(call, title: str) -> str:
    try:
        return cml_capture.find_lab([call("GET", f"/labs/{lab}") for lab in call("GET", "/labs")], title)
    except (LookupError, OSError, ValueError) as err:
        raise Refusal(f"could not find lab {title!r}: {err}") from None


def _read_topology(call, lab_id: str) -> tuple[dict, dict, list | None]:
    """(nodes, interfaces, links) of the lab, labels and all, read from its topology export."""
    path = topology_path(lab_id)
    try:
        return _parts(_ask(call, "GET", path))
    except SHAPE_ERRORS:
        raise Refusal(f"unexpected response shape from {path}") from None


def _node_path(lab_id: str, node_id: str) -> str:
    return f"/labs/{lab_id}/nodes/{node_id}"


def _state_of(reply):
    return reply.get("state") if isinstance(reply, dict) else reply


def _labelled_r3(nodes: dict) -> str | None:
    found = [node_id for node_id, node in nodes.items() if node.get("label") == R3]
    if len(found) > 1:
        raise Refusal(f"{len(found)} nodes are labelled {R3}; remove the extra ones in the CML UI first")
    return found[0] if found else None


def _free_spare(nodes: dict, interfaces: dict, links) -> str:
    """The id of R1 Ethernet0/3, refusing unless the topology shows it, once, and unconnected."""
    node_label, iface_label = SPARE
    found = _spare_interfaces(nodes, interfaces)
    if len(found) != 1:
        raise Refusal(f"the topology lists {len(found)} interfaces {iface_label} on {node_label}")
    if links is None:
        raise Refusal(
            f"the topology lists no links, so whether {node_label} {iface_label} is free is unknown"
        )
    used = [link for link in links if found[0]["id"] in _linked([link])]
    if used:
        raise Refusal(
            f"{node_label} {iface_label} is already connected ({_link_line(nodes, interfaces, used[0])})"
        )
    return found[0]["id"]


def _first_interface(interfaces: dict, node_id: str, platform: Platform) -> list:
    return [
        iface_id
        for iface_id, iface in interfaces.items()
        if iface.get("node") == node_id and iface.get("label") == platform.first_interface
    ]


def _existing_link(nodes, interfaces, links, node_id: str, platform: Platform):
    """The id of the link from R1 Ethernet0/3 to R3's first data interface, or None."""
    spare = {iface["id"] for iface in _spare_interfaces(nodes, interfaces)}
    ours = set(_first_interface(interfaces, node_id, platform))
    for link in links or []:
        ends = {link.get("interface_a"), link.get("interface_b")}
        if ends & spare and ends & ours:
            return link.get("id")
    return None


def _check_memory(call, definitions, platform: Platform, say) -> None:
    entry = next(
        (d for d in definitions if isinstance(d, dict) and d.get("id") == platform.node_definition), None
    )
    ram = _dig(entry, "sim", "linux_native", "ram")
    try:
        stats = call("GET", "/system_stats")
    except (OSError, ValueError) as err:
        say(f"memory check skipped: /system_stats: {err}")
        return
    line, short = memory_check(stats, platform.node_definition, ram)
    if short:
        raise Refusal(f"{line}: not enough to start R3")
    say(line)


def _create_node(call, lab_id: str, title: str, name: str, password: str) -> str:
    path = f"/labs/{lab_id}/nodes?populate_interfaces=true"
    try:
        reply = call("POST", path, node_body(name, password))  # never printed: it may echo the node
    except urllib.error.HTTPError as err:
        if err.code == 403:
            raise Refusal(f"this login may not change {title}") from None
        raise Refusal(f"POST {path}: HTTP {err.code}") from None
    except (OSError, ValueError) as err:
        raise Refusal(f"POST {path}: {err}") from None
    node_id = reply.get("id") if isinstance(reply, dict) else None
    if not node_id:
        raise Refusal(
            f"POST {path} gave no node id; if the lab now shows {R3}, cml_lab.py remove-r3 removes it"
        )
    return node_id


def _r3_interface(call, lab_id: str, node_id: str, platform: Platform) -> str:
    _, interfaces, _ = _read_topology(call, lab_id)
    found = _first_interface(interfaces, node_id, platform)
    if len(found) != 1:
        labels = sorted(str(i.get("label")) for i in interfaces.values() if i.get("node") == node_id)
        raise Refusal(
            f"{R3} has no interface {platform.first_interface} (it has: {', '.join(labels) or 'none'})"
        )
    return found[0]


def _create_link(call, lab_id: str, spare: str, r3_interface: str) -> str:
    # UNVERIFIED: that CML adds a link to R1 while R1 runs. R1 Ethernet0/3 already exists, so no
    # interface is hot-added, but nobody has tried this on the sandbox.
    path = f"/labs/{lab_id}/links"
    try:
        reply = call("POST", path, {"src_int": spare, "dst_int": r3_interface})
    except (OSError, ValueError) as err:
        detail = f"HTTP {err.code}" if isinstance(err, urllib.error.HTTPError) else str(err)
        raise Refusal(
            f"could not link R1 Ethernet0/3 to {R3}: POST {path}: {detail} "
            "(whether CML links a running R1 is unverified)"
        ) from None
    link_id = reply.get("id") if isinstance(reply, dict) else None
    if not link_id:
        raise Refusal(f"POST {path} gave no link id")
    return link_id


def _wait_booted(call, lab_id: str, node_id: str, say, sleep, now) -> None:
    """Poll R3's state every POLL_SECONDS until BOOTED, printing each, for at most BOOT_SECONDS.
    Still QUEUED or DEFINED_ON_CORE after NOT_STARTED_SECONDS means CML is not starting it."""
    path = f"{_node_path(lab_id, node_id)}/state"
    began = now()
    while True:
        state = _state_of(_ask(call, "GET", path))
        elapsed = now() - began
        say(f"{R3} {state} after {elapsed:.0f} s")
        if state == "BOOTED":
            return
        if state in NOT_STARTED and elapsed >= NOT_STARTED_SECONDS:
            raise Refusal(f"CML has not started {R3} (memory or licence; see cml_lab.py inspect)")
        if elapsed >= BOOT_SECONDS:
            raise Refusal(f"{R3} did not boot within {BOOT_SECONDS // 60} minutes (last state {state})")
        sleep(POLL_SECONDS)


def _start_link(call, lab_id: str, link_id: str, say) -> None:
    """Make sure the R1-R3 link is STARTED: start it once if it is not, and refuse if it still
    is not. A link added while R1 runs may stay down otherwise."""
    path = f"/labs/{lab_id}/links/{link_id}"
    state = _state_of(_ask(call, "GET", path))
    if state != "STARTED":
        say(f"the R1-{R3} link is {state}; starting it")
        _ask(call, "PUT", f"{path}/state/start")
        state = _state_of(_ask(call, "GET", path))
        if state != "STARTED":
            raise Refusal(f"the R1-{R3} link is still {state} after a start")
    say(f"the R1-{R3} link is STARTED")


def _resume(call, lab_id: str, node_id: str, topology, platform: Platform, say, sleep, now) -> int:
    """An R3 that already exists: done when it is the requested platform and BOOTED, the boot
    poll resumed when it is that platform and still starting, refused otherwise."""
    nodes, interfaces, links = topology
    definition = nodes[node_id].get("node_definition")
    state = _state_of(_ask(call, "GET", f"{_node_path(lab_id, node_id)}/state"))
    if definition != platform.node_definition or state not in ("BOOTED", *STARTING):
        raise Refusal(
            f"{R3} exists with node definition {definition} in state {state}; cml_lab.py remove-r3 removes it"
        )
    link_id = _existing_link(nodes, interfaces, links, node_id, platform)
    if link_id is None:
        raise Refusal(
            f"{R3} exists but no link joins R1 Ethernet0/3 and its {platform.first_interface}; "
            "cml_lab.py remove-r3 removes it"
        )
    if state == "BOOTED":
        say(f"{R3} ({definition}) is already booted")
    else:
        say(f"{R3} ({definition}) is {state}; waiting for it to boot")
        _wait_booted(call, lab_id, node_id, say, sleep, now)
    _start_link(call, lab_id, link_id, say)
    return 0


def add_r3(call, title: str, name: str, password: str, say, sleep=time.sleep, now=time.monotonic) -> int:
    """add-r3 <name>: R3 on that platform, linked to R1 Ethernet0/3 and booted. Exit 0 when R3 is
    BOOTED and its link STARTED, 1 at the first thing that is not as needed."""
    platform = PLATFORM_TABLE[name]
    definition = platform.node_definition
    created = False
    try:
        lab_id = _find_lab(call, title)
        listings = {
            "node_definitions": _ask(call, "GET", "/node_definitions/"),
            "image_definitions": _ask(call, "GET", "/image_definitions/"),
        }
        try:
            defined, images = platform_images(listings, definition)
        except SHAPE_ERRORS:
            raise Refusal(
                "unexpected response shape from /node_definitions/ or /image_definitions/"
            ) from None
        if not defined:
            raise Refusal(f"the controller has no node definition {definition}")
        if not images:
            raise Refusal(f"node definition {definition} has no image")
        say(f"node definition {definition}: images {', '.join(images)}")
        topology = _read_topology(call, lab_id)
        nodes, interfaces, links = topology
        existing = _labelled_r3(nodes)
        if existing is not None:
            return _resume(call, lab_id, existing, topology, platform, say, sleep, now)
        spare = _free_spare(nodes, interfaces, links)
        say(f"{SPARE[0]} {SPARE[1]} is free")
        _check_memory(call, listings["node_definitions"], platform, say)
        say(f"day-0 configuration for {R3}, with its password removed:")
        for line in day0_config(name, REMOVED).splitlines():
            say(f"  {line}")
        node_id = _create_node(call, lab_id, title, name, password)
        created = True
        say(f"created {R3} ({definition}) in {title}")
        if not kept_day0(_ask(call, "GET", _node_path(lab_id, node_id))):
            raise Refusal("CML did not keep the day-0 configuration")
        say("CML kept the day-0 configuration")
        link_id = _create_link(call, lab_id, spare, _r3_interface(call, lab_id, node_id, platform))
        say(f"linked {SPARE[0]} {SPARE[1]} to {R3} {platform.first_interface}")
        _ask(call, "PUT", f"{_node_path(lab_id, node_id)}/state/start")
        say(f"started {R3}; polling every {POLL_SECONDS} s for up to {BOOT_SECONDS // 60} minutes")
        _wait_booted(call, lab_id, node_id, say, sleep, now)
        _start_link(call, lab_id, link_id, say)
        say(f"{R3} is booted and linked to {SPARE[0]} {SPARE[1]}; cml_lab.py remove-r3 takes it out")
        return 0
    except Refusal as why:
        say(f"{why}; {CREATED}" if created else str(why))
        return 1


def _wait_stopped(call, lab_id: str, node_id: str, say, sleep, now) -> None:
    path = f"{_node_path(lab_id, node_id)}/state"
    began = now()
    while True:
        state = _state_of(_ask(call, "GET", path))
        elapsed = now() - began
        say(f"{R3} {state} after {elapsed:.0f} s")
        if state == "STOPPED":
            return
        if elapsed >= STOP_SECONDS:
            raise Refusal(
                f"{R3} did not stop within {STOP_SECONDS // 60} minutes (last state {state}); "
                "run cml_lab.py remove-r3 again"
            )
        sleep(POLL_SECONDS)


def remove_r3(call, title: str, say, sleep=time.sleep, now=time.monotonic) -> int:
    """remove-r3: stop R3 unless it is already stopped, wipe its disks, delete its link, then the
    node. No R3, or one that disappears on the way (a 404), is exit 0."""
    try:
        lab_id = _find_lab(call, title)
        nodes, interfaces, links = _read_topology(call, lab_id)
        node_id = _labelled_r3(nodes)
        if node_id is None:
            say(f"no node labelled {R3} in {title}; nothing to remove")
            return 0
        node = _node_path(lab_id, node_id)
        reply = _ask(call, "GET", f"{node}/state", gone_ok=True)
        if reply is GONE:
            say(f"{R3} is already gone")
            return 0
        state = _state_of(reply)
        if state not in ("STOPPED", "DEFINED_ON_CORE"):
            say(f"{R3} is {state}; stopping it")
            if _ask(call, "PUT", f"{node}/state/stop", gone_ok=True) is not GONE:
                _wait_stopped(call, lab_id, node_id, say, sleep, now)
        # A node that never started (DEFINED_ON_CORE) has no disks to wipe.
        if state != "DEFINED_ON_CORE":
            _ask(call, "PUT", f"{node}/wipe_disks", gone_ok=True)
            say(f"wiped {R3}'s disks")
        ours = {iface_id for iface_id, iface in interfaces.items() if iface.get("node") == node_id}
        for link in links or []:
            if ours & _linked([link]):
                _ask(call, "DELETE", f"/labs/{lab_id}/links/{link.get('id')}", gone_ok=True)
                say(f"deleted {_link_line(nodes, interfaces, link)}")
        _ask(call, "DELETE", node, gone_ok=True)
        say(f"deleted {R3} from {title}")
        return 0
    except Refusal as why:
        say(str(why))
        return 1


def parse_args(argv: list[str]) -> tuple[str, str | None] | None:
    """(action, its argument: the output directory or the platform) from the command line, or
    None for bad usage, which includes a platform the table does not have."""
    args = argv[1:]
    if args in (["check-login"], ["remove-r3"]):
        return args[0], None
    if len(args) == 2 and args[0] in ("add-r3", "platform-os") and args[1] in PLATFORM_TABLE:
        return args[0], args[1]
    if args[:1] == ["inspect"] and len(args) <= 2:
        return "inspect", args[1] if len(args) == 2 else None
    return None


def main(argv: list[str], request=None, sleep=time.sleep, now=time.monotonic) -> int:
    """`request(host, method, path, token, body) -> bytes` is the transport, cml_capture's
    HTTPS call unless a test gives another; `sleep` and `now` are the clock the boot and stop
    polls use."""
    parsed = parse_args(argv)
    if parsed is None:
        print(USAGE)
        return 2
    action, argument = parsed
    if action == "platform-os":
        print(PLATFORM_TABLE[argument].os)
        return 0
    password = os.environ.get("NCV_LAB_PASS", "")
    if action == "add-r3" and not password:
        print("cml_lab.py: NCV_LAB_PASS is not set")
        return 2

    def say(text: str) -> None:
        print(redact(text, password), flush=True)

    try:
        host, title, login = cml_capture.login_from(os.environ)
    except KeyError as missing:
        say(f"cml_lab.py: {missing.args[0]} is not set")
        return 2
    output = argument if action == "inspect" else None
    if output is not None:
        try:
            Path(output).mkdir(parents=True, exist_ok=True)
        except OSError as err:
            say(f"cml_lab.py: cannot write to {output}: {err}")
            return 2
    request = request or cml_capture._request
    try:
        token = cml_capture.authenticate(request, host, login)
    except urllib.error.HTTPError as err:  # the reply's body is never printed
        say(f"the CML login was not accepted (HTTP {err.code})")
        return 1
    except (OSError, ValueError) as err:
        say(f"cml_lab.py: could not reach CML at {host}: {err}")
        return 1
    if action == "check-login":
        say("the CML login was accepted")
        return 0
    if action == "add-r3":
        return add_r3(caller(request, host, token), title, argument, password, say, sleep, now)
    if action == "remove-r3":
        return remove_r3(caller(request, host, token), title, say, sleep, now)
    try:
        data, failures = inspect(cml_capture.getter(request, host, token), title)
    except (LookupError, OSError, ValueError) as err:
        say(f"cml_lab.py: could not find lab {title!r}: {err}")
        return 1
    for line in failures + describe_inventory(data):
        say(line)
    if output is not None:
        files = saved_files(data)
        for name, value in files.items():
            text = json.dumps(value, indent=2, sort_keys=True) + "\n"
            (Path(output) / name).write_text(text, encoding="utf-8")
        say(f"saved {len(files)} responses to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
