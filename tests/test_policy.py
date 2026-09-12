"""Policy evaluation: required evidence, inclusive limits, and config drift."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace

import pytest

from ncv import policy
from ncv.intent import Adjacency, ConfigRule
from ncv.policy import evaluate


def test_demo_fixtures_find_four_classes(demo_intent, pre_snapshot, post_snapshot):
    findings = evaluate(demo_intent, pre_snapshot, post_snapshot)
    assert Counter(f.policy_id for f in findings) == {"V_ADJ": 3, "V_ROUTE": 2, "V_ERR": 1, "V_DRIFT": 2}
    assert len(findings) == 8


def test_clean_pair_is_silent(demo_intent, pre_snapshot):
    assert evaluate(demo_intent, pre_snapshot, pre_snapshot) == []


@pytest.mark.parametrize("mutation", ["missing_interface", "missing_counter", "null_counter"])
def test_missing_counters_are_findings(demo_intent, pre_snapshot, mutation):
    post = deepcopy(pre_snapshot)
    interfaces = post["interface"]["r1"]["interfaces"]
    if mutation == "missing_interface":
        interfaces.clear()
    elif mutation == "missing_counter":
        del interfaces["GigabitEthernet0/1"]["crc"]
    else:
        interfaces["GigabitEthernet0/1"]["crc"] = None
    (finding,) = evaluate(demo_intent, pre_snapshot, post)
    assert finding.policy_id == "V_ERR"
    assert finding.before == {"in_errors": 0, "crc": 0}
    assert finding.after["crc"] is None


@pytest.mark.parametrize(
    "field,value", [("interface", "GigabitEthernet0/2"), ("interface", None), ("state", "UP")]
)
def test_adjacency_requires_full_on_requested_interface(demo_intent, pre_snapshot, field, value):
    post = deepcopy(pre_snapshot)
    post["ospf"]["r1"]["neighbors"]["10.0.12.2"][field] = value
    (finding,) = evaluate(demo_intent, pre_snapshot, post)
    assert finding.policy_id == "V_ADJ"
    assert finding.after[field] == value


@pytest.mark.parametrize(
    "field,value", [("state", "Idle"), ("state", None), ("vrf", "mgmt"), ("remote_as", 65101)]
)
def test_bgp_peer_must_be_established_in_the_declared_vrf_and_as(demo_intent, pre_snapshot, field, value):
    post = deepcopy(pre_snapshot)
    post["bgp"]["r1"]["neighbors"]["203.0.113.1"][field] = value
    (finding,) = evaluate(demo_intent, pre_snapshot, post)
    assert (finding.policy_id, finding.path) == ("V_ADJ", "bgp.neighbors.203.0.113.1")
    assert finding.after[field] == value
    assert "remote AS 65100" in finding.why


def test_bgp_state_is_case_insensitive_and_a_lost_peer_is_a_finding(demo_intent, pre_snapshot):
    post = deepcopy(pre_snapshot)
    post["bgp"]["r1"]["neighbors"]["203.0.113.1"]["state"] = "established"
    assert evaluate(demo_intent, pre_snapshot, post) == []
    post["bgp"]["r1"]["neighbors"].clear()
    (finding,) = evaluate(demo_intent, pre_snapshot, post)
    assert finding.policy_id == "V_ADJ"
    assert finding.after is None


def test_bgp_vrf_and_remote_as_are_checked_only_when_declared(demo_intent, pre_snapshot):
    intent = replace(demo_intent, adjacencies=(Adjacency("r1", "bgp", "203.0.113.1"),))
    post = deepcopy(pre_snapshot)
    post["bgp"]["r1"]["neighbors"]["203.0.113.1"].update(vrf="mgmt", remote_as=65999)
    assert evaluate(intent, pre_snapshot, post) == []


def test_counter_limits_are_inclusive_absolute_values(demo_intent, pre_snapshot):
    post = deepcopy(pre_snapshot)
    rec = post["interface"]["r1"]["interfaces"]["GigabitEthernet0/1"]
    rec.update(in_errors=10, crc=5)
    assert evaluate(demo_intent, pre_snapshot, post) == []
    rec["in_errors"] = 11
    assert [f.policy_id for f in evaluate(demo_intent, post, post)] == ["V_ERR"]


def test_config_matches_full_trimmed_lines(demo_intent, pre_snapshot):
    intent = replace(
        demo_intent,
        must_include=(ConfigRule("r1", ("ntp server 192.0.2.1",)),),
        must_absent=(ConfigRule("r1", ("username left",)),),
    )
    post = deepcopy(pre_snapshot)
    post["config"]["r1"]["running"] = "ntp server 192.0.2.10\nusername leftover\n"
    (finding,) = evaluate(intent, pre_snapshot, post)
    assert finding.path.endswith("must_include")
    post["config"]["r1"]["running"] += "  ntp server 192.0.2.1  \n"
    assert evaluate(intent, pre_snapshot, post) == []


def test_absence_cannot_be_proven_without_config(demo_intent, pre_snapshot):
    intent = replace(demo_intent, must_include=())
    post = deepcopy(pre_snapshot)
    del post["config"]["r1"]
    (finding,) = evaluate(intent, pre_snapshot, post)
    assert finding.policy_id == "V_DRIFT"
    assert finding.after is None


def test_config_rules_share_evidence_but_not_across_evaluations(demo_intent, pre_snapshot, monkeypatch):
    intent = replace(
        demo_intent,
        must_include=(ConfigRule("r1", ("ntp server 192.0.2.1",)),),
        must_absent=(ConfigRule("r1", ("username left",)),),
    )
    post = deepcopy(pre_snapshot)
    post["config"]["r1"]["running"] = "ntp server 192.0.2.1\n"

    splits: list[str] = []
    original = policy._config_lines

    def counting(snap, device):
        splits.append(device)
        return original(snap, device)

    monkeypatch.setattr(policy, "_config_lines", counting)

    assert evaluate(intent, pre_snapshot, post) == []
    # r1 is split once per snapshot and shared by both rule groups, not split four times.
    assert splits == ["r1", "r1"]

    assert evaluate(intent, pre_snapshot, post) == []
    # A later evaluation re-reads the snapshots instead of reusing the first one's sets.
    assert splits == ["r1", "r1", "r1", "r1"]


def test_missing_config_is_reported_once_across_rule_groups(demo_intent, pre_snapshot):
    intent = replace(
        demo_intent,
        must_include=(ConfigRule("r1", ("ntp server 192.0.2.1",)),),
        must_absent=(ConfigRule("r1", ("username left",)),),
    )
    post = deepcopy(pre_snapshot)
    del post["config"]["r1"]
    (finding,) = evaluate(intent, pre_snapshot, post)
    assert finding.policy_id == "V_DRIFT"
    assert finding.path == "config.running"
    assert finding.before is True
    assert finding.after is None
