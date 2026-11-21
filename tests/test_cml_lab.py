"""scripts/lab/cml_lab.py: the read-only inventory of the CML controller, against a fake CML.

The inventory below is invented: no real listing of this controller's node definitions, image
definitions, or topology has been seen, and several of those response shapes are unverified.
Only the field names cml_capture.py already relies on (lab_title, label, interface_a and
interface_b) come from the controller's own API description. The report must therefore print
"unknown" where a field is missing and say so where a response has another shape, never raise.
Every test runs with urllib's urlopen replaced by one that fails the test, so none can reach a
controller; the HTTP calls go through a fake `request` passed to main.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request

import pytest

LAB = "lab-1"
TOPOLOGY = f"/labs/{LAB}/topology?exclude_configurations=true"
# Invented values; the words "hunter2" and "vpn-login" stand for secrets that must never be
# printed or saved, in the places CML could carry them.
SECRET = "hunter2"
INVENTORY = {
    "/labs": ["lab-0", LAB],
    "/labs/lab-0": {"id": "lab-0", "lab_title": "someone-else"},
    f"/labs/{LAB}": {"id": LAB, "lab_title": "default-lab", "lab_notes": f"vpn-login {SECRET}"},
    "/system_information": {"version": "2.7.2", "ready": True},
    "/system_stats": {"all": {"cpu": {"percent": 12.5}, "memory": {"used": 8, "total": 32}}},
    "/licensing": {"registration": {"status": "COMPLETED"}, "authorization": {"status": "IN_COMPLIANCE"}},
    "/node_definitions/": [
        {
            "id": "iol-xe",
            "description": f"default login {SECRET}",
            "sim": {"linux_native": {"ram": 768, "cpus": 1}},
            "device": {
                "interfaces": {"physical": ["Ethernet0/0", "Ethernet0/1", "Ethernet0/2", "Ethernet0/3"]}
            },
        },
        {"id": "cat8000v", "sim": {"linux_native": {"ram": 4096, "cpus": 1}}},
        "iosv",
    ],
    "/image_definitions/": [
        {"id": "iol-xe-17-12-01", "node_definition_id": "iol-xe"},
        {"id": "cat8000v-17-13-01", "node_definition": "cat8000v"},
    ],
    TOPOLOGY: {
        "lab": {"title": "default-lab", "notes": f"console {SECRET}", "description": SECRET},
        # a text annotation on the canvas, where a lab's author can write a login
        "annotations": [{"type": "text", "text_content": f"login cisco/{SECRET}"}],
        "nodes": [
            {
                "id": "n1",
                "label": "R1",
                "node_definition": "iol-xe",
                "image_definition": "iol-xe-17-12-01",
                "configuration": f"enable password {SECRET}",
                "vnc_key": SECRET,
                "interfaces": [
                    {"id": "i1-1", "label": "Ethernet0/1", "slot": 1},
                    {"id": "i1-3", "label": "Ethernet0/3", "slot": 3},
                ],
            },
            {"id": "n2", "label": "R2", "node_definition": "iol-xe", "configuration": [{"content": SECRET}]},
        ],
        # interfaces listed at the top level, as the other form CML may use
        "interfaces": [{"id": "i2-1", "node": "n2", "label": "Ethernet0/1", "slot": 1}],
        "links": [{"id": "l1", "interface_a": "i2-1", "interface_b": "i1-1"}],
    },
    f"/labs/{LAB}/nodes/n1/state": {"state": "BOOTED"},
    f"/labs/{LAB}/nodes/n2/state": {"state": "BOOTED"},
}
REPORT = [
    "CML version: 2.7.2",
    "licensing: registration COMPLETED, authorization IN_COMPLIANCE",
    "controller memory: 8 used of 32, as the API counts it",
    "controller CPU in use: 12.5 %",
    "node definition iol-xe: RAM 768, CPUs 1, interfaces Ethernet0/0 to Ethernet0/3 (4)",
    "node definition cat8000v: RAM 4096, CPUs 1, interfaces unknown",
    "node definition iosv: RAM unknown, CPUs unknown, interfaces unknown",
    "image definition iol-xe-17-12-01: node definition iol-xe",
    "image definition cat8000v-17-13-01: node definition cat8000v",
    "lab default-lab: 2 nodes, 1 links",
    "node R1: node definition iol-xe, image iol-xe-17-12-01, state BOOTED",
    "node R2: node definition iol-xe, image unknown, state BOOTED",
    "interface R1 Ethernet0/1: slot 1, connected",
    "interface R1 Ethernet0/3: slot 3, not connected",
    "interface R2 Ethernet0/1: slot 1, connected",
    "link R2 Ethernet0/1 - R1 Ethernet0/1",
    "answer: R1 Ethernet0/3 is free: yes (interface R1 Ethernet0/3: slot 3, not connected)",
    "answer: nxosv9000 available: no (no node definition nxosv9000; images naming it: none)",
    "answer: cat8000v available: yes (node definition cat8000v; images cat8000v-17-13-01)",
    "answer: iosv available: no (node definition iosv, but no image definition names it)",
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("a test tried to reach a CML controller")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def cml_lab(root, monkeypatch):
    path = root / "scripts" / "lab" / "cml_lab.py"
    spec = importlib.util.spec_from_file_location("cml_lab", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cml_lab", module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("NCV_CML_USER", "developer")
    monkeypatch.setenv("NCV_CML_PASS", "cml-login-value")
    for name in ("NCV_CML_HOST", "NCV_CML_LAB"):
        monkeypatch.delenv(name, raising=False)
    return module


def _fake(responses=None, fail=(), login_refused=False):
    """A fake transport: the list of (method, path) it was sent, and the request function.
    A path in `fail` raises the way an unreachable or refusing controller does."""
    responses = INVENTORY if responses is None else responses
    sent = []

    def request(host, method, path, token=None, body=None):
        sent.append((method, path))
        if path == "/authenticate":
            if login_refused:
                raise urllib.error.HTTPError(f"https://{host}/api/v0{path}", 403, "Forbidden", None, None)
            return b'"session-token"'
        if path in fail or path not in responses:
            raise urllib.error.URLError("timed out")
        return json.dumps(responses[path]).encode()

    return sent, request


def test_the_report_from_an_invented_inventory(cml_lab, capsys):
    sent, request = _fake()
    assert cml_lab.main(["cml_lab.py", "inspect"], request) == 0
    assert capsys.readouterr().out.splitlines() == REPORT


def test_every_call_is_a_get_and_none_asks_for_a_node_or_its_configuration(cml_lab):
    sent, request = _fake()
    cml_lab.main(["cml_lab.py", "inspect"], request)
    assert sent[0] == ("POST", "/authenticate")
    assert {method for method, _ in sent[1:]} == {"GET"}
    paths = [path for _, path in sent]
    assert TOPOLOGY in paths
    assert not [p for p in paths if p.startswith(f"/labs/{LAB}/nodes/") and not p.endswith("/state")]
    assert not [p for p in paths if "topology" in p and p != TOPOLOGY]


def test_missing_fields_print_as_unknown_instead_of_raising(cml_lab):
    data = {
        "lab": {"id": LAB, "title": "default-lab"},
        "system_information": {},
        "system_stats": {"all": "busy"},
        "licensing": [],
        "node_definitions": [{}],
        "image_definitions": [{}],
        "topology": {"nodes": [{"id": "n1", "interfaces": [{"id": "i1"}]}]},
        "node_states": {},
    }
    assert cml_lab.describe_inventory(data) == [
        "CML version: unknown",
        "licensing: registration unknown, authorization unknown",
        "controller memory: unknown used of unknown, as the API counts it",
        "controller CPU in use: unknown %",
        "node definition unknown: RAM unknown, CPUs unknown, interfaces unknown",
        "image definition unknown: node definition unknown",
        "lab default-lab: 1 nodes, unknown links",
        "node unknown: node definition unknown, image unknown, state unknown",
        "interface unknown unknown: slot unknown, connection unknown",
        "answer: R1 Ethernet0/3 is free: unknown (the topology lists 0 interfaces Ethernet0/3 on R1)",
        "answer: nxosv9000 available: no (no node definition nxosv9000; images naming it: none)",
        "answer: cat8000v available: no (no node definition cat8000v; images naming it: none)",
        "answer: iosv available: no (no node definition iosv; images naming it: none)",
    ]


def test_a_response_of_another_shape_is_named_instead_of_a_traceback(cml_lab):
    data = {
        "lab": {"id": LAB, "title": "default-lab"},
        "node_definitions": {"iol-xe": {}},
        "image_definitions": [],
        "topology": ["not", "an", "object"],
        "node_states": {},
    }
    lines = cml_lab.describe_inventory(data)
    assert "unexpected response shape from /node_definitions/" in lines
    assert lines.count(f"unexpected response shape from {TOPOLOGY}") == 2
    assert lines[-3:] == ["unexpected response shape from /node_definitions/ or /image_definitions/"] * 3


def test_a_failed_call_is_reported_and_the_inventory_goes_on(cml_lab, capsys):
    sent, request = _fake(fail={"/licensing", "/image_definitions/", f"/labs/{LAB}/nodes/n2/state"})
    assert cml_lab.main(["cml_lab.py", "inspect"], request) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == [
        "/licensing: <urlopen error timed out>",
        "/image_definitions/: <urlopen error timed out>",
        f"/labs/{LAB}/nodes/n2/state: <urlopen error timed out>",
    ]
    assert "licensing: registration unknown, authorization unknown" in out
    assert "image definitions: unknown" in out
    assert "node R2: node definition iol-xe, image unknown, state unknown" in out
    assert "CML version: 2.7.2" in out
    assert out[-1] == ("answer: iosv available: unknown (no response from /image_definitions/)")


def test_a_used_spare_port_is_not_free_and_the_link_is_the_evidence(cml_lab):
    topology = json.loads(json.dumps(INVENTORY[TOPOLOGY]))
    topology["links"].append({"id": "l2", "interface_a": "i1-3", "interface_b": "i2-1"})
    data = {"lab": {"id": LAB}, "topology": topology, "node_states": {}}
    assert (
        cml_lab.spare_port_answer(data)
        == "answer: R1 Ethernet0/3 is free: no (link R1 Ethernet0/3 - R2 Ethernet0/1)"
    )
    assert cml_lab.spare_port_answer({}) == "answer: R1 Ethernet0/3 is free: unknown (no topology response)"


def test_scrub_drops_configuration_notes_and_descriptions_at_any_depth(cml_lab):
    response = {
        "id": "n1",
        "configuration": "enable password x",
        "notes": "x",
        "description": "x",
        "lab_notes": "x",
        "lab_description": "x",
        "nodes": [{"label": "R1", "configuration": [{"content": "x"}], "tags": ["notes"]}],
        "lab": {"title": "t", "notes": "x", "inner": {"description": "x", "keep": 1}},
    }
    assert cml_lab.scrub(response) == {
        "id": "n1",
        "nodes": [{"label": "R1", "tags": ["notes"]}],
        "lab": {"title": "t", "inner": {"keep": 1}},
    }
    assert response["configuration"] == "enable password x"  # the argument is left as it was


def test_scrub_drops_annotations_and_vnc_keys_at_any_depth(cml_lab):
    response = {
        "annotations": [{"type": "text", "text_content": "login cisco/x"}],
        "vnc_key": "x",
        "nodes": [
            {"label": "R1", "vnc_key": "x", "inner": {"annotations": [{"text_content": "x"}], "keep": 1}}
        ],
        "lab": {"title": "t"},
    }
    assert cml_lab.scrub(response) == {
        "nodes": [{"label": "R1", "inner": {"keep": 1}}],
        "lab": {"title": "t"},
    }


def test_no_secret_reaches_the_output_or_the_saved_files(cml_lab, capsys, tmp_path):
    out_dir = tmp_path / "probe-cml"
    sent, request = _fake()
    assert cml_lab.main(["cml_lab.py", "inspect", str(out_dir)], request) == 0
    printed = capsys.readouterr().out
    assert printed.endswith(f"saved 8 responses to {out_dir}\n")
    assert sorted(path.name for path in out_dir.iterdir()) == [
        "image_definitions.json",
        "licensing.json",
        "node-n1-state.json",
        "node-n2-state.json",
        "node_definitions.json",
        "system_information.json",
        "system_stats.json",
        "topology.json",
    ]
    saved = "".join(path.read_text(encoding="utf-8") for path in out_dir.iterdir())
    for text in (printed, saved):
        assert SECRET not in text
        assert "configuration" not in text
        assert "session-token" not in text and "cml-login-value" not in text
    assert json.loads((out_dir / "system_information.json").read_text(encoding="utf-8"))["version"] == "2.7.2"


@pytest.mark.parametrize("args", [[], ["inventory"], ["inspect", "a", "b"], ["check-login", "extra"]])
def test_bad_usage_exits_2_before_any_call(cml_lab, capsys, args):
    sent, request = _fake()
    assert cml_lab.main(["cml_lab.py", *args], request) == 2
    assert capsys.readouterr().out == cml_lab.USAGE + "\n"
    assert sent == []


@pytest.mark.parametrize("missing", ["NCV_CML_USER", "NCV_CML_PASS"])
def test_a_missing_login_exits_2_before_any_call(cml_lab, monkeypatch, capsys, missing):
    monkeypatch.delenv(missing)
    sent, request = _fake()
    assert cml_lab.main(["cml_lab.py", "inspect"], request) == 2
    assert capsys.readouterr().out == f"cml_lab.py: {missing} is not set\n"
    assert sent == []


def test_check_login_exits_0_when_cml_accepts_the_login_and_asks_for_nothing_else(cml_lab, capsys):
    sent, request = _fake()
    assert cml_lab.main(["cml_lab.py", "check-login"], request) == 0
    assert capsys.readouterr().out == "the CML login was accepted\n"
    assert sent == [("POST", "/authenticate")]


@pytest.mark.parametrize("action", ["check-login", "inspect"])
def test_a_refused_login_exits_1_without_the_password_or_the_reply(cml_lab, capsys, action):
    sent, request = _fake(login_refused=True)
    assert cml_lab.main(["cml_lab.py", action], request) == 1
    out = capsys.readouterr().out
    assert out == "the CML login was not accepted (HTTP 403)\n"
    assert sent == [("POST", "/authenticate")]


def test_a_lab_that_cannot_be_found_exits_1(cml_lab, monkeypatch, capsys):
    monkeypatch.setenv("NCV_CML_LAB", "no-such-lab")
    sent, request = _fake()
    assert cml_lab.main(["cml_lab.py", "inspect"], request) == 1
    assert "expected one lab titled 'no-such-lab', found 0" in capsys.readouterr().out


# add-r3 and remove-r3 against an invented controller that changes as it is told. Nothing here
# was seen on the sandbox: the node definition ids and interface labels are from CML's
# documentation, and a real controller may differ in every field read with .get().
LAB_PASS = "r3-admin-value"
NODES = f"/labs/{LAB}/nodes?populate_interfaces=true"
R3_STATE = f"/labs/{LAB}/nodes/n3/state"
R3_START = f"/labs/{LAB}/nodes/n3/state/start"
# How add-r3 reads the new node back: with its configuration, the way virl2_client 2.7.1 reads one.
READBACK = f"/labs/{LAB}/nodes/n3?exclude_configurations=false"


def _r3_inventory():
    """INVENTORY plus what add-r3 reads: an nxosv9000 definition with its RAM and an image, and
    the controller's memory in bytes (32 GiB, 8 GiB used)."""
    inventory = json.loads(json.dumps(INVENTORY))
    inventory["/node_definitions/"].append({"id": "nxosv9000", "sim": {"linux_native": {"ram": 10240}}})
    inventory["/image_definitions/"].append({"id": "nxosv9000-10-4-3", "node_definition_id": "nxosv9000"})
    inventory["/system_stats"] = {"all": {"memory": {"used": 8 * 2**30, "total": 32 * 2**30}}}
    return inventory


class FakeCML:
    """A controller for add-r3 and remove-r3. It records every (method, path, body) it is sent,
    answers GETs from its table, and changes the table as the POSTs and DELETEs ask. R3's state
    answers come from `states` in turn (the last repeats), the link's from `link_states`.
    `errors` maps (method, path) to the HTTP status to fail with, or to an exception. With
    `as_files`, the node keeps its configuration as a list of named files, the other form CML may
    store it in."""

    def __init__(
        self,
        inventory=None,
        states=("BOOTED",),
        link_states=("STARTED",),
        errors=None,
        keeps=True,
        as_files=False,
    ):
        self.table = inventory or _r3_inventory()
        self.states, self.link_states = list(states), list(link_states)
        self.errors, self.keeps, self.as_files = errors or {}, keeps, as_files
        self.sent = []

    @property
    def topology(self):
        return self.table[TOPOLOGY]

    def add_r3_node(self, definition="nxosv9000", first="Ethernet1/1", linked=True):
        """An R3 already in the lab, as an earlier add-r3 would have left it."""
        self.topology["nodes"].append(
            {
                "id": "n3",
                "label": "R3",
                "node_definition": definition,
                "interfaces": [{"id": "i3-0", "label": "mgmt0"}, {"id": "i3-1", "label": first}],
            }
        )
        if linked:
            self.topology["links"].append({"id": "l3", "interface_a": "i1-3", "interface_b": "i3-1"})

    def _next(self, answers):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def request(self, host, method, path, token=None, body=None):
        self.sent.append((method, path, body))
        if path == "/authenticate":
            return b'"session-token"'
        error = self.errors.get((method, path))
        if isinstance(error, Exception):
            raise error
        if error:
            raise urllib.error.HTTPError(f"https://{host}/api/v0{path}", error, "refused", None, None)
        reply = self._answer(method, path, body)
        return b"" if reply is None else json.dumps(reply).encode()

    def _answer(self, method, path, body):
        if (method, path) == ("POST", NODES):
            config = body["configuration"] if self.keeps else ""
            if self.as_files:
                config = [{"name": "Main", "content": config}]
            self.table[READBACK] = {"id": "n3", "label": "R3", "configuration": config}
            self.add_r3_node(body["node_definition"], linked=False)
            return {"id": "n3", "label": "R3", "configuration": body["configuration"]}  # an echo
        if (method, path) == ("POST", f"/labs/{LAB}/links"):
            link = {"id": "l3", "interface_a": body["src_int"], "interface_b": body["dst_int"]}
            self.topology["links"].append(link)
            return {"id": "l3", "label": "i1-3-i3-1"}
        if method == "GET" and path == R3_STATE:
            return {"state": self._next(self.states)}
        if method == "GET" and path == f"/labs/{LAB}/links/l3":
            return {"id": "l3", "state": self._next(self.link_states)}
        if method == "GET":
            if path not in self.table:
                raise urllib.error.URLError("timed out")
            return self.table[path]
        return None  # a PUT or DELETE that succeeds answers with nothing this script reads


class Clock:
    """Replaces time.sleep and time.monotonic: sleeping moves the clock, not the test."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def time(self):
        return self.now


@pytest.fixture
def r3_env(cml_lab, monkeypatch):
    monkeypatch.setenv("NCV_LAB_PASS", LAB_PASS)
    return cml_lab


def _r3(cml_lab, fake, *args):
    clock = Clock()
    code = cml_lab.main(["cml_lab.py", *args], fake.request, clock.sleep, clock.time)
    return code, clock


def _calls(fake):
    """What the fake was sent, without the bodies and without the login."""
    return [(method, path) for method, path, _ in fake.sent if path != "/authenticate"]


def _writes(fake):
    return [(method, path) for method, path in _calls(fake) if method != "GET"]


@pytest.mark.parametrize("platform", ["nxosv9000", "cat8000v", "iosv"])
def test_day0_config_holds_what_the_run_depends_on_and_its_echo_never_the_password(r3_env, platform):
    entry = r3_env.PLATFORM_TABLE[platform]
    config = r3_env.day0_config(platform, LAB_PASS).splitlines()
    stripped = [line.strip() for line in config]
    assert config[0] == "hostname R3"
    assert f"interface {entry.first_interface}" in config
    assert "ip ospf hello-interval 1" in stripped
    assert "router bgp 65003" in config
    if platform == "nxosv9000":
        for line in ("feature ospf", "feature bgp", "no switchport", "ip address 10.1.3.3/24", "no shutdown"):
            assert line in stripped
        assert "ip ospf dead-interval 4" in stripped
        # R1 learns 3.3.3.3/32 over OSPF only, and every platform's prediction expects that route
        assert stripped[stripped.index("ip address 3.3.3.3/32") + 1] == "ip router ospf 1 area 0.0.0.0"
        assert stripped[-4:-1] == ["neighbor 10.1.3.1", "remote-as 65001", "timers 3 9"]
        assert "network 172.16.3.0/24" in stripped
        assert f"username admin password {LAB_PASS} role network-admin" in config
    else:
        for line in ("ip address 10.1.3.3 255.255.255.0", "no shutdown", "network 10.1.3.0 0.0.0.255 area 0"):
            assert line in stripped
        assert "network 3.3.3.3 0.0.0.0 area 0" in stripped  # the route every prediction expects
        assert "neighbor 10.1.3.1 remote-as 65001" in stripped
        assert "neighbor 10.1.3.1 timers 3 9" in stripped
        assert "network 172.16.3.0 mask 255.255.255.0" in stripped
        assert f"username admin privilege 15 secret {LAB_PASS}" in config
        assert not [line for line in config if line.startswith("line con")]  # no console login
    echoed = r3_env.day0_config(platform, "<removed>")
    assert LAB_PASS not in echoed and echoed.count("<removed>") == 1


def test_the_platform_table_names_the_interface_and_os_each_testbed_needs(r3_env):
    table = {name: (p.node_definition, p.os, p.first_interface) for name, p in r3_env.PLATFORM_TABLE.items()}
    assert table == {
        "nxosv9000": ("nxosv9000", "nxos", "Ethernet1/1"),
        "cat8000v": ("cat8000v", "iosxe", "GigabitEthernet1"),
        "iosv": ("iosv", "ios", "GigabitEthernet0/0"),
    }
    assert r3_env.PLATFORMS == ("nxosv9000", "cat8000v", "iosv")


def test_redact_replaces_every_occurrence_and_an_empty_secret_changes_nothing(cml_lab):
    assert cml_lab.redact("a hunter2 b hunter2", "hunter2") == "a <removed> b <removed>"
    assert cml_lab.redact("a hunter2", "") == "a hunter2"


def test_platform_os_prints_the_os_without_a_login_or_a_call(cml_lab, monkeypatch, capsys):
    monkeypatch.delenv("NCV_CML_PASS")
    fake = FakeCML()
    assert cml_lab.main(["cml_lab.py", "platform-os", "iosv"], fake.request) == 0
    assert capsys.readouterr().out == "ios\n"
    assert cml_lab.main(["cml_lab.py", "platform-os", "csr1000v"], fake.request) == 2
    assert capsys.readouterr().out == cml_lab.USAGE + "\n"
    assert fake.sent == []


def test_add_r3_needs_the_admin_password_before_any_call(cml_lab, monkeypatch, capsys):
    monkeypatch.delenv("NCV_LAB_PASS", raising=False)
    fake = FakeCML()
    assert cml_lab.main(["cml_lab.py", "add-r3", "nxosv9000"], fake.request) == 2
    assert capsys.readouterr().out == "cml_lab.py: NCV_LAB_PASS is not set\n"
    assert fake.sent == []


def test_add_r3_issues_the_calls_in_order_with_the_right_bodies(r3_env, capsys):
    fake = FakeCML(states=("DEFINED_ON_CORE", "STARTED", "BOOTED"))
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 0
    assert _calls(fake) == [
        ("GET", "/labs"),
        ("GET", "/labs/lab-0"),
        ("GET", f"/labs/{LAB}"),
        ("GET", "/node_definitions/"),
        ("GET", "/image_definitions/"),
        ("GET", TOPOLOGY),
        ("GET", "/system_stats"),
        ("POST", NODES),
        ("GET", READBACK),
        ("GET", TOPOLOGY),
        ("POST", f"/labs/{LAB}/links"),
        ("PUT", f"/labs/{LAB}/nodes/n3/state/start"),
        ("GET", R3_STATE),
        ("GET", R3_STATE),
        ("GET", R3_STATE),
        ("GET", f"/labs/{LAB}/links/l3"),
    ]
    bodies = {path: body for method, path, body in fake.sent if method == "POST" and path != "/authenticate"}
    assert bodies[NODES] == {
        "label": "R3",
        "node_definition": "nxosv9000",
        "x": 0,
        "y": 300,
        "configuration": r3_env.day0_config("nxosv9000", LAB_PASS),
    }
    assert bodies[f"/labs/{LAB}/links"] == {"src_int": "i1-3", "dst_int": "i3-1"}
    assert clock.sleeps == [15, 15]
    out = capsys.readouterr().out
    assert LAB_PASS not in out
    assert "  username admin password <removed> role network-admin\n" in out
    assert "controller memory free: 24576 MiB; the nxosv9000 node definition asks for 10240 MiB\n" in out
    assert "R3 DEFINED_ON_CORE after 0 s\nR3 STARTED after 15 s\nR3 BOOTED after 30 s\n" in out
    assert out.endswith("R3 is booted and linked to R1 Ethernet0/3; cml_lab.py remove-r3 takes it out\n")


def _no_image(fake):
    images = fake.table["/image_definitions/"]
    fake.table["/image_definitions/"] = [image for image in images if "nxos" not in image["id"]]


def _connected(fake):
    fake.topology["links"].append({"id": "l9", "interface_a": "i1-3", "interface_b": "i2-1"})


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (_no_image, "node definition nxosv9000 has no image\n"),
        (lambda fake: fake.add_r3_node("iosv", "GigabitEthernet0/0"), "R3 exists with node definition iosv"),
        (lambda fake: fake.add_r3_node(), None),  # the right platform, but stopped: see below
        (_connected, "R1 Ethernet0/3 is already connected (link R1 Ethernet0/3 - R2 Ethernet0/1)\n"),
    ],
)
def test_each_refusal_stops_before_any_post(r3_env, capsys, change, reason):
    fake = FakeCML(states=("STOPPED",))
    change(fake)
    code, _ = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1
    assert _writes(fake) == []
    out = capsys.readouterr().out
    stopped = "R3 exists with node definition nxosv9000 in state STOPPED; cml_lab.py remove-r3"
    assert (reason or stopped) in out
    assert "R3 was created" not in out


def test_a_controller_without_the_node_definition_is_refused(r3_env, capsys):
    fake = FakeCML()
    fake.table["/node_definitions/"] = [d for d in fake.table["/node_definitions/"] if d != "iosv"]
    code, _ = _r3(r3_env, fake, "add-r3", "iosv")
    assert code == 1
    assert capsys.readouterr().out.splitlines()[-1] == "the controller has no node definition iosv"
    assert _writes(fake) == []


def test_plainly_short_memory_is_refused_with_both_numbers_before_the_post(r3_env, capsys):
    fake = FakeCML()
    fake.table["/system_stats"]["all"]["memory"]["used"] = 26 * 2**30
    code, _ = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1
    assert _writes(fake) == []
    assert capsys.readouterr().out.splitlines()[-1] == (
        "controller memory free: 6144 MiB; the nxosv9000 node definition asks for 10240 MiB: "
        "not enough to start R3"
    )


def test_missing_memory_figures_skip_the_check_and_say_so(r3_env, capsys):
    fake = FakeCML(errors={("GET", "/system_stats"): urllib.error.URLError("timed out")})
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 0
    assert "memory check skipped: /system_stats: <urlopen error timed out>\n" in capsys.readouterr().out
    assert r3_env.memory_check({}, "iosv", None) == (
        "memory check skipped: no /system_stats memory or iosv's RAM in the responses",
        False,
    )


def test_a_login_that_may_not_change_the_lab_is_told_so(r3_env, capsys):
    fake = FakeCML(errors={("POST", NODES): 403})
    code, _ = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "this login may not change default-lab, or the licence's node limit is reached"
    )
    assert _writes(fake) == [("POST", NODES)]


def test_a_node_whose_day0_configuration_cml_dropped_is_not_started(r3_env, capsys):
    fake = FakeCML(keeps=False)
    code, _ = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1
    assert _writes(fake) == [("POST", NODES)]
    assert capsys.readouterr().out.splitlines()[-1] == (
        "CML did not keep the day-0 configuration; R3 was created; cml_lab.py remove-r3 removes it"
    )


def test_a_node_kept_as_a_list_of_files_counts_as_kept(r3_env, capsys):
    fake = FakeCML(as_files=True)
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 0
    assert "CML kept the day-0 configuration\n" in capsys.readouterr().out


def test_kept_day0_reads_the_hostname_from_a_string_or_a_list_of_files(cml_lab):
    day0 = cml_lab.day0_config("iosv", LAB_PASS)
    assert cml_lab.kept_day0({"configuration": day0})
    assert cml_lab.kept_day0({"configuration": [{"name": "Main", "content": day0}]})
    assert cml_lab.kept_day0(
        {"configuration": [{"name": "a", "content": "x"}, {"name": "b", "content": day0}]}
    )
    assert not cml_lab.kept_day0({"configuration": [{"name": "Main", "content": "hostname R1\n"}]})
    assert not cml_lab.kept_day0({"configuration": None})
    assert not cml_lab.kept_day0({})
    assert not cml_lab.kept_day0(None)


def test_a_node_that_never_boots_times_out_with_exit_1(r3_env, capsys):
    fake = FakeCML(states=("STARTED",))
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1
    assert clock.now == 20 * 60 and set(clock.sleeps) == {15}
    assert capsys.readouterr().out.splitlines()[-1] == (
        "R3 did not boot within 20 minutes (last state STARTED); "
        "R3 was created; cml_lab.py remove-r3 removes it"
    )


def test_a_node_cml_never_starts_is_given_up_after_3_minutes(r3_env, capsys):
    fake = FakeCML(states=("QUEUED",))
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1
    assert clock.now == 3 * 60
    assert capsys.readouterr().out.splitlines()[-1] == (
        "CML has not started R3 (memory or licence; see cml_lab.py inspect); "
        "R3 was created; cml_lab.py remove-r3 removes it"
    )


def test_a_node_left_defined_on_core_after_the_start_is_given_up_after_3_minutes(r3_env, capsys):
    fake = FakeCML(states=("DEFINED_ON_CORE",))
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1 and clock.now == 3 * 60
    assert capsys.readouterr().out.splitlines()[-1] == (
        "CML has not started R3 (memory or licence; see cml_lab.py inspect); "
        "R3 was created; cml_lab.py remove-r3 removes it"
    )


def test_a_node_that_stays_stopped_after_the_start_is_given_up_after_3_minutes(r3_env, capsys):
    fake = FakeCML(states=("DEFINED_ON_CORE", "QUEUED", "STOPPED"))
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 1 and clock.now == 3 * 60
    assert capsys.readouterr().out.splitlines()[-1] == (
        "R3 is still STOPPED 180 s after the start; CML does not boot a stopped node by itself; "
        "R3 was created; cml_lab.py remove-r3 removes it"
    )


def test_a_brief_stopped_state_at_the_start_does_not_end_the_wait(r3_env):
    fake = FakeCML(states=("STOPPED", "STOPPED", "STARTED", "BOOTED"))
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 0 and clock.sleeps == [15, 15, 15]


def test_cml_refusing_the_start_exits_1_naming_remove_r3(r3_env, capsys):
    fake = FakeCML(errors={("PUT", R3_START): 400})
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 1
    assert _writes(fake)[-1] == ("PUT", R3_START)
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"PUT {R3_START}: HTTP 400; R3 was created; cml_lab.py remove-r3 removes it"
    )


@pytest.mark.parametrize(
    ("method", "path"), [("POST", NODES), ("POST", f"/labs/{LAB}/links"), ("PUT", R3_START)]
)
def test_an_http_error_whose_body_echoes_the_password_prints_neither(r3_env, capsys, method, path):
    """CML's error body can quote the configuration it was sent; only the status is printed."""
    body = f'{{"description": "rejected: username admin password {LAB_PASS}"}}'.encode()
    error = urllib.error.HTTPError(f"https://cml/api/v0{path}", 422, "Unprocessable", None, io.BytesIO(body))
    fake = FakeCML(errors={(method, path): error})
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 1
    out = capsys.readouterr().out
    assert LAB_PASS not in out
    assert "rejected" not in out and "Unprocessable" not in out
    assert "HTTP 422" in out.splitlines()[-1]


def test_a_link_that_is_not_started_is_started_once_and_refused_if_it_stays_down(r3_env, capsys):
    fake = FakeCML(link_states=("DEFINED_ON_CORE", "STARTED"))
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 0
    assert _writes(fake)[-1] == ("PUT", f"/labs/{LAB}/links/l3/state/start")
    out = capsys.readouterr().out
    assert "the R1-R3 link is DEFINED_ON_CORE; starting it\nthe R1-R3 link is STARTED\n" in out
    fake = FakeCML(link_states=("STOPPED",))
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "the R1-R3 link is still STOPPED after a start; R3 was created; cml_lab.py remove-r3 removes it"
    )


def test_an_error_that_echoes_the_password_is_printed_without_it(r3_env, capsys):
    """A CML validation error can quote the field it rejected; the link POST here does."""
    echo = urllib.error.URLError(f"rejected configuration 'username admin password {LAB_PASS}'")
    fake = FakeCML(errors={("POST", f"/labs/{LAB}/links"): echo})
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 1
    out = capsys.readouterr().out
    assert LAB_PASS not in out
    assert "username admin password <removed>" in out
    assert out.splitlines()[-1].endswith("; R3 was created; cml_lab.py remove-r3 removes it")


def test_an_existing_r3_that_is_booted_is_done_and_one_still_starting_is_waited_for(r3_env, capsys):
    fake = FakeCML(states=("BOOTED",))
    fake.add_r3_node()
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 0
    assert _writes(fake) == []
    assert "R3 (nxosv9000) is already booted\n" in capsys.readouterr().out
    fake = FakeCML(states=("STARTED", "STARTED", "BOOTED"))
    fake.add_r3_node()
    code, clock = _r3(r3_env, fake, "add-r3", "nxosv9000")
    assert code == 0 and clock.sleeps == [15]
    assert _writes(fake) == []
    assert "R3 (nxosv9000) is STARTED; waiting for it to boot\n" in capsys.readouterr().out


def test_an_existing_booted_r3_whose_link_is_down_gets_the_link_started(r3_env, capsys):
    fake = FakeCML(states=("BOOTED",), link_states=("STOPPED", "STARTED"))
    fake.add_r3_node()
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 0
    assert _writes(fake) == [("PUT", f"/labs/{LAB}/links/l3/state/start")]
    assert "the R1-R3 link is STOPPED; starting it\nthe R1-R3 link is STARTED\n" in capsys.readouterr().out


def test_a_booted_r3_of_another_platform_is_refused_with_no_write(r3_env, capsys):
    fake = FakeCML(states=("BOOTED",))
    fake.add_r3_node("iosv", "GigabitEthernet0/0")
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 1
    assert _writes(fake) == []
    assert capsys.readouterr().out.splitlines()[-1] == (
        "R3 exists with node definition iosv in state BOOTED; cml_lab.py remove-r3 removes it"
    )


@pytest.mark.parametrize("args", [["add-r3", "nxosv9000"], ["remove-r3"]])
def test_two_nodes_labelled_r3_are_refused_with_no_write(r3_env, capsys, args):
    fake = FakeCML()
    fake.add_r3_node()
    fake.topology["nodes"].append({"id": "n4", "label": "R3", "node_definition": "iosv", "interfaces": []})
    assert _r3(r3_env, fake, *args)[0] == 1
    assert _writes(fake) == []
    assert capsys.readouterr().out.splitlines()[-1] == (
        "2 nodes are labelled R3; remove the extra ones in the CML UI first"
    )


def test_an_existing_r3_without_its_link_is_refused(r3_env, capsys):
    fake = FakeCML(states=("BOOTED",))
    fake.add_r3_node(linked=False)
    assert _r3(r3_env, fake, "add-r3", "nxosv9000")[0] == 1
    assert "no link joins R1 Ethernet0/3 and its Ethernet1/1; cml_lab.py remove-r3" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["BOOTED", "STARTED"])  # booted, and still booting
def test_remove_r3_stops_a_running_node_waits_wipes_and_deletes_its_link_then_the_node(r3_env, capsys, state):
    fake = FakeCML(states=(state, "STARTED", "STOPPED"))
    fake.add_r3_node()
    code, clock = _r3(r3_env, fake, "remove-r3")
    assert code == 0
    node = f"/labs/{LAB}/nodes/n3"
    assert _writes(fake) == [
        ("PUT", f"{node}/state/stop"),
        ("PUT", f"{node}/wipe_disks"),
        ("DELETE", f"/labs/{LAB}/links/l3"),
        ("DELETE", node),
    ]
    assert clock.sleeps == [15]
    assert capsys.readouterr().out.endswith(
        "deleted link R1 Ethernet0/3 - R3 Ethernet1/1\ndeleted R3 from default-lab\n"
    )


def test_remove_r3_of_a_node_that_never_started_neither_stops_nor_wipes_it(r3_env):
    fake = FakeCML(states=("DEFINED_ON_CORE",))
    fake.add_r3_node()
    assert _r3(r3_env, fake, "remove-r3")[0] == 0
    assert _writes(fake) == [("DELETE", f"/labs/{LAB}/links/l3"), ("DELETE", f"/labs/{LAB}/nodes/n3")]


def test_remove_r3_of_a_queued_node_that_stops_into_defined_on_core_removes_it_in_one_run(r3_env, capsys):
    fake = FakeCML(states=("QUEUED", "DEFINED_ON_CORE"))
    fake.add_r3_node()
    code, clock = _r3(r3_env, fake, "remove-r3")
    assert code == 0 and clock.sleeps == []
    node = f"/labs/{LAB}/nodes/n3"
    assert _writes(fake) == [  # no wipe: a node that never started has no disks
        ("PUT", f"{node}/state/stop"),
        ("DELETE", f"/labs/{LAB}/links/l3"),
        ("DELETE", node),
    ]
    assert capsys.readouterr().out.endswith("deleted R3 from default-lab\n")


def test_remove_r3_with_no_r3_does_nothing(r3_env, capsys):
    fake = FakeCML()
    assert _r3(r3_env, fake, "remove-r3")[0] == 0
    assert _writes(fake) == []
    assert capsys.readouterr().out == "no node labelled R3 in default-lab; nothing to remove\n"


def test_remove_r3_treats_a_node_already_gone_as_removed(r3_env):
    node = f"/labs/{LAB}/nodes/n3"
    gone = {("DELETE", f"/labs/{LAB}/links/l3"): 404, ("DELETE", node): 404}
    fake = FakeCML(states=("STOPPED",), errors=gone)
    fake.add_r3_node()
    assert _r3(r3_env, fake, "remove-r3")[0] == 0
    assert _writes(fake) == [
        ("PUT", f"{node}/wipe_disks"),
        ("DELETE", f"/labs/{LAB}/links/l3"),
        ("DELETE", node),
    ]


def test_remove_r3_that_will_not_stop_gives_up_after_3_minutes(r3_env, capsys):
    fake = FakeCML(states=("BOOTED",))
    fake.add_r3_node()
    code, clock = _r3(r3_env, fake, "remove-r3")
    assert code == 1 and clock.now == 3 * 60
    assert _writes(fake) == [("PUT", f"/labs/{LAB}/nodes/n3/state/stop")]
    assert "did not stop within 3 minutes (last state BOOTED)" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["add-r3"], ["add-r3", "csr1000v"], ["remove-r3", "now"]])
def test_add_and_remove_bad_usage_exits_2_before_any_call(r3_env, capsys, args):
    fake = FakeCML()
    assert r3_env.main(["cml_lab.py", *args], fake.request) == 2
    assert capsys.readouterr().out == r3_env.USAGE + "\n"
    assert fake.sent == []
