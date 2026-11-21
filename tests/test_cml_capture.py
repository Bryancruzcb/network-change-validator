"""scripts/lab/cml_capture.py: finding the R1-R2 link through the CML API, against a fake CML.

The field names follow CML 2.7.2's own OpenAPI description (/api/v0/openapi.json), read from
the sandbox controller on 2026-11-20: a lab has lab_title, a link has node_a, node_b,
interface_a, and interface_b, and nodes and interfaces have a label. The last tests pin the
command line, including the optional capture filter, and that the filter reaches the start
request, with the HTTP calls replaced.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

LAB = "lab-1111"
LINKS = [
    # default-lab also joins each router to the backend on Ethernet0/2
    {"id": "link-mgmt", "node_a": "n1", "interface_a": "i1-2", "node_b": "n9", "interface_b": "i9-0"},
    {"id": "link-r1r2", "node_a": "n2", "interface_a": "i2-1", "node_b": "n1", "interface_b": "i1-1"},
]
NODES = {"n1": "R1", "n2": "R2", "n9": "backend"}
INTERFACES = {"i1-1": "Ethernet0/1", "i1-2": "Ethernet0/2", "i2-1": "Ethernet0/1", "i9-0": "port1"}


@pytest.fixture
def cml(root, monkeypatch):
    path = root / "scripts" / "lab" / "cml_capture.py"
    spec = importlib.util.spec_from_file_location("cml_capture", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cml_capture", module)
    spec.loader.exec_module(module)
    return module


def _fake_get(labs):
    def get(path):
        if path == "/labs":
            return list(labs)
        if path.startswith("/labs/") and path.count("/") == 2:
            return {"id": path.split("/")[2], "lab_title": labs[path.split("/")[2]]}
        if path == f"/labs/{LAB}/links?data=true":
            return LINKS
        kind, item = path.split("/")[3:5]
        return {"label": (NODES if kind == "nodes" else INTERFACES)[item]}

    return get


def test_locate_finds_the_r1_r2_link_whichever_end_is_a(cml):
    get = _fake_get({"lab-0000": "someone-else", LAB: "default-lab"})
    assert cml.locate(get, "default-lab") == (LAB, "link-r1r2")


def test_find_lab_refuses_a_missing_or_repeated_title(cml):
    with pytest.raises(LookupError, match="found 0"):
        cml.find_lab([{"id": "a", "lab_title": "other"}], "default-lab")
    with pytest.raises(LookupError, match="found 2"):
        cml.find_lab(
            [{"id": "a", "lab_title": "default-lab"}, {"id": "b", "lab_title": "default-lab"}], "default-lab"
        )


def test_find_link_refuses_when_no_link_joins_both_ends(cml):
    interfaces = dict(INTERFACES, **{"i2-1": "Ethernet0/3"})
    with pytest.raises(LookupError, match="found 0"):
        cml.find_link(LINKS, NODES, interfaces)


def test_capture_body_keeps_bgp_only_and_stops_on_its_own(cml):
    assert cml.capture_body() == {"maxtime": 900, "bpfilter": "tcp port 179"}


def test_cli_refuses_bad_usage_and_a_missing_login(cml, monkeypatch, capsys):
    assert cml.main(["cml_capture.py"]) == 2
    assert cml.main(["cml_capture.py", "stop"]) == 2
    assert cml.main(["cml_capture.py", "start", "extra"]) == 2
    monkeypatch.delenv("NCV_CML_USER", raising=False)
    monkeypatch.delenv("NCV_CML_PASS", raising=False)
    assert cml.main(["cml_capture.py", "start"]) == 2
    assert "NCV_CML_USER is not set" in capsys.readouterr().out


def test_parse_args_reads_the_action_the_filter_and_the_path(cml):
    assert cml.parse_args(["cml_capture.py", "start"]) == ("start", "tcp port 179", None)
    assert cml.parse_args(["cml_capture.py", "start", "--filter", "ip proto 89"]) == (
        "start",
        "ip proto 89",
        None,
    )
    assert cml.parse_args(["cml_capture.py", "stop", "link.pcap"]) == ("stop", None, "link.pcap")
    longest = "x" * 128
    assert cml.parse_args(["cml_capture.py", "start", "--filter", longest]) == ("start", longest, None)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["capture"],
        ["start", "extra"],
        ["start", "--filter"],
        ["start", "--filter", ""],
        ["start", "--filter", "x" * 129],  # the CML API refuses a bpfilter over 128 characters
        ["start", "--filter", "ip proto 89", "extra"],
        ["start", "ip proto 89", "--filter"],
        ["stop"],
        ["stop", "link.pcap", "--filter", "ip proto 89"],
    ],
)
def test_parse_args_refuses_bad_usage(cml, monkeypatch, capsys, args):
    assert cml.parse_args(["cml_capture.py", *args]) is None
    monkeypatch.setenv("NCV_CML_USER", "user")
    monkeypatch.setenv("NCV_CML_PASS", "unused")
    assert cml.main(["cml_capture.py", *args]) == 2
    assert capsys.readouterr().out == cml.USAGE + "\n"


def _fake_api(cml, monkeypatch):
    """Replaces the HTTP calls and the link lookup; returns the list of (method, path, body) sent."""
    sent = []

    def request(host, method, path, token=None, body=None):
        sent.append((method, path, body))
        return b'"token"' if path == "/authenticate" else b"{}"

    monkeypatch.setattr(cml, "_request", request)
    monkeypatch.setattr(cml, "locate", lambda get, title: (LAB, "link-r1r2"))
    monkeypatch.setenv("NCV_CML_USER", "user")
    monkeypatch.setenv("NCV_CML_PASS", "unused")
    return sent


def test_capture_body_carries_the_filter_it_is_given(cml):
    assert cml.capture_body(bpfilter="ip proto 89") == {"maxtime": 900, "bpfilter": "ip proto 89"}


@pytest.mark.parametrize(
    "args, bpfilter", [([], "tcp port 179"), (["--filter", "ip proto 89"], "ip proto 89")]
)
def test_start_sends_the_filter_to_the_capture_and_names_it(cml, monkeypatch, capsys, args, bpfilter):
    sent = _fake_api(cml, monkeypatch)
    assert cml.main(["cml_capture.py", "start", *args]) == 0
    start = f"/labs/{LAB}/links/link-r1r2/capture/start"
    assert sent[-1] == ("PUT", start, {"maxtime": 900, "bpfilter": bpfilter})
    assert f"capturing {bpfilter} on the R1-R2 link of default-lab" in capsys.readouterr().out
