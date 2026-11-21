"""Policy evaluation: required evidence, inclusive limits, and config drift."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace

import pytest

from ncv import policy
from ncv.intent import Adjacency, ConfigRule, Intent
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


# BGP snapshots keyed by VRF, built here: the published fixtures keep the flat shape.
PEER = "198.51.100.1"
UP = {"state": "Established", "remote_as": 65010}
DOWN = {"state": "Idle", "remote_as": 65010}
FLAT_DOWN = {"state": "Idle", "vrf": "default", "remote_as": 65010}


def _bgp_snap(node):
    return {"bgp": {"r1": node}}


def _by_vrf(**vrfs):
    return _bgp_snap({"vrfs": {vrf: {"neighbors": {PEER: rec}} for vrf, rec in vrfs.items()}})


def _bgp_intent(*adjacencies):
    return Intent("by-vrf", 1, ("r1",), adjacencies=adjacencies)


@pytest.mark.parametrize(
    "post,vrf,after,path",
    [
        pytest.param(
            _bgp_snap({"neighbors": {PEER: FLAT_DOWN}}),
            "default",
            FLAT_DOWN,
            f"bgp.neighbors.{PEER}",
            id="legacy-vrf-named",
        ),
        pytest.param(
            _bgp_snap({"neighbors": {PEER: FLAT_DOWN}}),
            "",
            FLAT_DOWN,
            f"bgp.neighbors.{PEER}",
            id="legacy-vrf-omitted",
        ),
        pytest.param(
            _by_vrf(default=DOWN, NCV=UP),
            "default",
            DOWN,
            f"bgp.vrfs.default.neighbors.{PEER}",
            id="by-vrf-named",
        ),
        pytest.param(
            _by_vrf(default=UP),
            "NCV",
            None,
            f"bgp.vrfs.NCV.neighbors.{PEER}",
            id="by-vrf-named-vrf-missing",
        ),
        pytest.param(
            _by_vrf(default=DOWN, NCV=UP),
            "",
            DOWN,
            f"bgp.vrfs.default.neighbors.{PEER}",
            id="by-vrf-omitted-in-default",
        ),
        pytest.param(
            _by_vrf(NCV=UP),
            "",
            None,
            f"bgp.vrfs.default.neighbors.{PEER}",
            id="by-vrf-omitted-only-in-another-vrf",
        ),
        pytest.param(
            _bgp_snap({"vrfs": {"default": {"neighbors": {"192.0.2.9": UP}}}}),
            "",
            None,
            f"bgp.vrfs.default.neighbors.{PEER}",
            id="by-vrf-omitted-in-no-vrf",
        ),
    ],
)
def test_bgp_evidence_and_path_follow_the_stored_shape(post, vrf, after, path):
    (finding,) = evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER, vrf=vrf)), post, post)
    assert (finding.policy_id, finding.path, finding.before, finding.after) == ("V_ADJ", path, after, after)


@pytest.mark.parametrize("vrf,post", [("NCV", _by_vrf(NCV=UP)), ("", _by_vrf(default=UP))])
def test_a_by_vrf_record_established_in_its_vrf_is_compliant(vrf, post):
    assert evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER, vrf=vrf, remote_as=65010)), post, post) == []


def test_a_rule_that_names_no_vrf_ignores_the_same_address_in_another_vrf():
    # The default session is up; a VRF neighbor with the same address is down. The rule that
    # names no vrf is about the default session only, so nothing moved for it.
    post = _by_vrf(default=UP, NCV=DOWN)
    assert evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER)), _by_vrf(default=UP), post) == []


@pytest.mark.parametrize(
    "vrf,remote_as,why",
    [
        ("", None, f"required BGP neighbor {PEER} must be Established in vrf default"),
        ("", 65010, f"required BGP neighbor {PEER} must be Established in vrf default with remote AS 65010"),
        ("NCV", None, f"required BGP neighbor {PEER} must be Established in vrf NCV"),
        ("NCV", 65010, f"required BGP neighbor {PEER} must be Established in vrf NCV with remote AS 65010"),
    ],
)
def test_a_by_vrf_finding_names_the_vrf_it_checked(vrf, remote_as, why):
    post = _by_vrf(default=DOWN, NCV=DOWN)
    (finding,) = evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER, vrf=vrf, remote_as=remote_as)), post, post)
    assert finding.why == why
    assert finding.action == "inspect the peer session, its vrf, and its remote AS in the lab"


@pytest.mark.parametrize(
    "snap,path",
    [
        pytest.param(_bgp_snap({"neighbors": {}}), f"bgp.neighbors.{PEER}", id="neighbors-key-is-flat"),
        pytest.param(_bgp_snap({}), f"bgp.vrfs.default.neighbors.{PEER}", id="empty-node-is-by-vrf"),
        pytest.param({"bgp": {}}, f"bgp.vrfs.default.neighbors.{PEER}", id="missing-device-is-by-vrf"),
        pytest.param({}, f"bgp.vrfs.default.neighbors.{PEER}", id="missing-section-is-by-vrf"),
    ],
)
def test_a_node_is_flat_only_when_it_holds_neighbors(snap, path):
    # A device with no data at all also gets the V_DRIFT "missing from post" finding; only the
    # adjacency finding is about the shape.
    findings = evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER)), snap, snap)
    (finding,) = [f for f in findings if f.policy_id == "V_ADJ"]
    assert (finding.path, finding.before, finding.after) == (path, None, None)


def test_the_same_peer_in_two_vrfs_is_judged_per_named_vrf():
    post = _by_vrf(default=UP, NCV=DOWN)
    intent = _bgp_intent(Adjacency("r1", "bgp", PEER, vrf="default"), Adjacency("r1", "bgp", PEER, vrf="NCV"))
    (finding,) = evaluate(intent, post, post)
    assert finding.path == f"bgp.vrfs.NCV.neighbors.{PEER}"
    assert finding.after == DOWN
    assert finding.why == f"required BGP neighbor {PEER} must be Established in vrf NCV"
    assert finding.action == "inspect the peer session, its vrf, and its remote AS in the lab"


def test_a_remote_as_mismatch_in_the_named_vrf_is_a_finding():
    post = _by_vrf(NCV={"state": "Established", "remote_as": 65999})
    (finding,) = evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER, vrf="NCV", remote_as=65010)), post, post)
    assert finding.path == f"bgp.vrfs.NCV.neighbors.{PEER}"
    assert finding.why == f"required BGP neighbor {PEER} must be Established in vrf NCV with remote AS 65010"


def test_a_legacy_pre_meets_a_by_vrf_post():
    flat_up = {"state": "Established", "vrf": "default", "remote_as": 65010}
    pre = _bgp_snap({"neighbors": {PEER: flat_up}})
    post = _by_vrf(default=DOWN)
    (finding,) = evaluate(
        _bgp_intent(Adjacency("r1", "bgp", PEER, vrf="default", remote_as=65010)), pre, post
    )
    assert (finding.before, finding.after) == (flat_up, DOWN)
    assert finding.path == f"bgp.vrfs.default.neighbors.{PEER}"


@pytest.mark.parametrize(
    "vrf,why",
    [
        ("default", f"required BGP neighbor {PEER} must be Established in vrf default"),
        ("", f"required BGP neighbor {PEER} must be Established"),
    ],
)
def test_a_by_vrf_pre_meets_a_legacy_post(vrf, why):
    # Each snapshot is read in its own shape: the pre by its default-VRF key, the post (and so
    # the path, compliance, and wording) by the flat record.
    pre = _by_vrf(default=UP)
    post = _bgp_snap({"neighbors": {PEER: FLAT_DOWN}})
    (finding,) = evaluate(_bgp_intent(Adjacency("r1", "bgp", PEER, vrf=vrf)), pre, post)
    assert (finding.before, finding.after) == (UP, FLAT_DOWN)
    assert finding.path == f"bgp.neighbors.{PEER}"
    assert finding.why == why
