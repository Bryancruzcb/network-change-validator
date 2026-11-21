"""A read-only inventory of the CML controller and default-lab, for planning the next lab runs.

Two things decide what the next runs can do, and nothing in the repository may guess either:
which node definitions and images this controller has, and whether R1 Ethernet0/3, the spare
port, is free for a new link. This asks the CML 2.7 REST API (/api/v0) and prints what it
finds, ending with those two answers, each "yes", "no", or "unknown" with the line it rests
on. Given a directory, it also saves each response there as one JSON file.

Usage, with the CML login in NCV_CML_USER and NCV_CML_PASS (probe.sh asks for them):
  cml_lab.py inspect [<output dir>]   print the inventory; with a directory, save each response
  cml_lab.py check-login              exit 0 when CML accepts the login, 1 when it does not

The controller is NCV_CML_HOST (default 10.10.20.161) and the lab NCV_CML_LAB (default
default-lab), read the way cml_capture.py reads them. Every call is a GET. Node configurations
hold the routers' passwords, so the topology is asked for without them, /labs/{id}/nodes/{id}
is never called, and `configuration`, notes, and descriptions are dropped from every response
before anything is printed or saved; the /authenticate response is never saved. Several
response shapes are documented nowhere this repository can check, so every field is read as
optional and printed as unknown when it is absent. A call that fails is reported and skipped;
the exit code is 1 only when the login or finding the lab fails, and 2 on bad usage or a
missing login. Standard library only, and outside ncv like the rest of scripts/lab.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path

# cml_capture.py sits next to this file and scripts/lab is not a package, so the script's own
# directory goes on the import path before the import, which therefore cannot be at the top.
HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import cml_capture  # noqa: E402

USAGE = "usage: cml_lab.py inspect [<output dir>] | check-login"
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
# The node types a second platform could be built from, in the order the answers list them.
PLATFORMS = ("nxosv9000", "cat8000v", "iosv")
# The routers' one spare port, the only place a new link could attach without removing one.
SPARE = ("R1", "Ethernet0/3")
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


def spare_port_answer(data: dict) -> str:
    """Whether R1 Ethernet0/3 is free: yes, no, or unknown, with the line it rests on."""
    node_label, iface_label = SPARE
    question = f"answer: {node_label} {iface_label} is free:"
    if "topology" not in data:
        return f"{question} {UNKNOWN} (no topology response)"
    nodes, interfaces, links = _parts(data["topology"])
    found = [
        iface
        for iface in interfaces.values()
        if iface.get("label") == iface_label and _dig(nodes.get(iface.get("node")), "label") == node_label
    ]
    if len(found) != 1:
        count = f"{len(found)} interfaces {iface_label} on {node_label}"
        return f"{question} {UNKNOWN} (the topology lists {count})"
    if links is None:
        return f"{question} {UNKNOWN} (the topology lists no links)"
    used = [link for link in links if found[0]["id"] in _linked([link])]
    if used:
        return f"{question} no ({_link_line(nodes, interfaces, used[0])})"
    return f"{question} yes ({_interface_line(nodes, found[0], links)})"


def platform_answer(data: dict, platform: str) -> str:
    """Whether `platform` is available, meaning it has a node definition and at least one image
    naming that definition: yes, no, or unknown, with the evidence."""
    question = f"answer: {platform} available:"
    missing = [path for name, path in SYSTEM_CALLS[3:] if name not in data]
    if missing:
        return f"{question} {UNKNOWN} (no response from {', '.join(missing)})"
    defined = platform in {_ident(item) for item in _items(data["node_definitions"])}
    images = [
        _show(_ident(image))
        for image in _items(data["image_definitions"])
        if not isinstance(image, str) and _image_node_definition(image) == platform
    ]
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


def parse_args(argv: list[str]) -> tuple[str, str | None] | None:
    """(action, output directory) from the command line, or None for bad usage."""
    args = argv[1:]
    if args == ["check-login"]:
        return "check-login", None
    if args[:1] == ["inspect"] and len(args) <= 2:
        return "inspect", args[1] if len(args) == 2 else None
    return None


def main(argv: list[str], request=None) -> int:
    """`request(host, method, path, token, body) -> bytes` is the transport, cml_capture's
    HTTPS call unless a test gives another."""
    parsed = parse_args(argv)
    if parsed is None:
        print(USAGE)
        return 2
    action, output = parsed
    try:
        host, title, login = cml_capture.login_from(os.environ)
    except KeyError as missing:
        print(f"cml_lab.py: {missing.args[0]} is not set")
        return 2
    if output is not None:
        try:
            Path(output).mkdir(parents=True, exist_ok=True)
        except OSError as err:
            print(f"cml_lab.py: cannot write to {output}: {err}")
            return 2
    request = request or cml_capture._request
    try:
        token = cml_capture.authenticate(request, host, login)
    except urllib.error.HTTPError as err:  # the reply's body is never printed
        print(f"the CML login was not accepted (HTTP {err.code})")
        return 1
    except (OSError, ValueError) as err:
        print(f"cml_lab.py: could not reach CML at {host}: {err}")
        return 1
    if action == "check-login":
        print("the CML login was accepted")
        return 0
    try:
        data, failures = inspect(cml_capture.getter(request, host, token), title)
    except (LookupError, OSError, ValueError) as err:
        print(f"cml_lab.py: could not find lab {title!r}: {err}")
        return 1
    for line in failures + describe_inventory(data):
        print(line)
    if output is not None:
        files = saved_files(data)
        for name, value in files.items():
            text = json.dumps(value, indent=2, sort_keys=True) + "\n"
            (Path(output) / name).write_text(text, encoding="utf-8")
        print(f"saved {len(files)} responses to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
