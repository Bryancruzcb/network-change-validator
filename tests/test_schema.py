"""Snapshot section validation reports the offending file and field."""

from __future__ import annotations

import json
import re

import pytest

from ncv.snapshot import load_snapshot


@pytest.mark.parametrize("payload", [[], {"r1": []}, {"r1": {"interfaces": {"Gi1": {"crc": "oops"}}}}])
def test_bad_snapshot_has_file_context(tmp_path, payload):
    path = tmp_path / "interface.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="interface.json"):
        load_snapshot(tmp_path)


@pytest.mark.parametrize("record", [{"remote_as": "65100"}, {"remote_as": True}, {"state": 1}])
def test_bad_bgp_record_has_file_and_field_context(tmp_path, record):
    (tmp_path / "bgp.json").write_text(json.dumps({"r1": {"neighbors": {"203.0.113.1": record}}}))
    with pytest.raises(ValueError, match="bgp.json"):
        load_snapshot(tmp_path)


BY_VRF = {
    "r1": {
        "vrfs": {
            "default": {"neighbors": {"198.51.100.1": {"state": "Established", "remote_as": 65010}}},
            "NCV": {"neighbors": {"198.51.100.1": {"state": "Idle", "remote_as": None}}},
        }
    },
    "r2": {"vrfs": {}},
}


def test_bgp_section_keyed_by_vrf_loads(tmp_path):
    (tmp_path / "bgp.json").write_text(json.dumps(BY_VRF))
    assert load_snapshot(tmp_path)["bgp"] == BY_VRF


def test_bgp_node_with_both_neighbors_and_vrfs_is_refused(tmp_path):
    node = {"neighbors": {}, "vrfs": {}}
    (tmp_path / "bgp.json").write_text(json.dumps({"r1": node}))
    with pytest.raises(ValueError, match=r"bgp\.json\.r1: has both neighbors and vrfs"):
        load_snapshot(tmp_path)


def test_bad_remote_as_inside_vrfs_has_file_and_field_context(tmp_path):
    bad = {"r1": {"vrfs": {"NCV": {"neighbors": {"198.51.100.1": {"state": "Idle", "remote_as": -1}}}}}}
    (tmp_path / "bgp.json").write_text(json.dumps(bad))
    field = re.escape("bgp.json.r1.vrfs.NCV.neighbors.198.51.100.1.remote_as: expected")
    with pytest.raises(ValueError, match=field):
        load_snapshot(tmp_path)
