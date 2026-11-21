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
        "nodes": [
            {
                "id": "n1",
                "label": "R1",
                "node_definition": "iol-xe",
                "image_definition": "iol-xe-17-12-01",
                "configuration": f"enable password {SECRET}",
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
