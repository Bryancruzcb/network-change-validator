"""The live lab captures, sanitized, replayed offline.

fixtures/lab-2026-09-12, fixtures/lab-2026-09-18, and fixtures/lab-2026-11-20 hold real
captures from a Cisco DevNet CML sandbox (see each SOURCE.md). These tests pin what those
runs showed, so an adapter or policy change that would have missed the real change fails
here first.
"""

from __future__ import annotations

import json

import pytest

from ncv.cli import main


def _diff(root, tmp_path, run, before, after, intent, lab="lab-2026-09-12"):
    lab = root / "fixtures" / lab
    report = tmp_path / f"{run}-{before}-{after}"
    code = main(
        [
            "diff",
            str(lab / run / before),
            str(lab / run / after),
            "--intent",
            str(lab / intent),
            "--report",
            str(report),
        ]
    )
    findings = json.loads((report / "report.json").read_text(encoding="utf-8"))["findings"]
    return code, sorted((f["policy_id"], f["device"], f["path"]) for f in findings)


def test_route_run_catches_the_shut_link(root, tmp_path):
    code, findings = _diff(root, tmp_path, "routes", "pre", "post", "intent-routes.yaml")
    assert code == 1
    assert findings == [
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.1.1.1.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.20.20.20.0/24"),
    ]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_route_run_is_clean_without_the_change(root, tmp_path, after):
    code, findings = _diff(root, tmp_path, "routes", "pre", after, "intent-routes.yaml")
    assert code == 0
    assert findings == []


def test_ospf_run_catches_both_lost_adjacencies_and_routes(root, tmp_path):
    code, findings = _diff(root, tmp_path, "ospf", "pre", "post", "intent-ospf.yaml")
    assert code == 1
    assert findings == [
        ("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"),
        ("V_ADJ", "R2", "ospf.neighbors.1.1.1.1"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.1.1.1.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.20.20.20.0/24"),
    ]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_ospf_run_is_clean_without_the_change(root, tmp_path, after):
    code, findings = _diff(root, tmp_path, "ospf", "pre", after, "intent-ospf.yaml")
    assert code == 0
    assert findings == []


def test_bgp_run_catches_both_lost_sessions_and_the_shutdown_line(root, tmp_path):
    code, findings = _diff(root, tmp_path, "bgp", "pre", "post", "intent-bgp.yaml", lab="lab-2026-09-18")
    assert code == 1
    assert findings == [
        ("V_ADJ", "R1", "bgp.neighbors.1.1.1.2"),
        ("V_ADJ", "R2", "bgp.neighbors.1.1.1.1"),
        ("V_DRIFT", "R1", "config.running.must_absent"),
    ]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_bgp_run_is_clean_without_the_change(root, tmp_path, after):
    code, findings = _diff(root, tmp_path, "bgp", "pre", after, "intent-bgp.yaml", lab="lab-2026-09-18")
    assert code == 0
    assert findings == []


HOLDTIMER = {"run": "bgp-holdtimer", "intent": "intent-bgp-holdtimer.yaml", "lab": "lab-2026-11-20"}


def test_holdtimer_run_catches_both_lost_sessions_and_nothing_else(root, tmp_path):
    """No rule names the ACL that caused it, so only the adjacency rules fire."""
    h = HOLDTIMER
    code, findings = _diff(root, tmp_path, h["run"], "pre", "post", h["intent"], lab=h["lab"])
    assert code == 1
    assert findings == [("V_ADJ", "R1", "bgp.neighbors.1.1.1.2"), ("V_ADJ", "R2", "bgp.neighbors.1.1.1.1")]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_holdtimer_run_is_clean_without_the_change(root, tmp_path, after):
    h = HOLDTIMER
    code, findings = _diff(root, tmp_path, h["run"], "pre", after, h["intent"], lab=h["lab"])
    assert code == 0
    assert findings == []


def test_holdtimer_post_capture_holds_the_acl_and_idle_sessions(root):
    """The change is in the captured config, and both sessions were captured Idle."""
    post = root / "fixtures" / "lab-2026-11-20" / "bgp-holdtimer" / "post"
    running = json.loads((post / "config.json").read_text(encoding="utf-8"))["R1"]["running"]
    assert " ip access-group NCV-BLOCK-BGP in" in running.splitlines()
    bgp = json.loads((post / "bgp.json").read_text(encoding="utf-8"))
    assert {dev: next(iter(rec["neighbors"].values()))["state"] for dev, rec in bgp.items()} == {
        "R1": "Idle",
        "R2": "Idle",
    }
