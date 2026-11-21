"""Copying a snapshot validates input and never publishes a partial directory."""

from __future__ import annotations

import pytest

from ncv.snapshot import copy_snapshot, load_snapshot, write_sections


def test_snapshot_copy_validates_and_preserves_evidence(tmp_path, root, pre_snapshot):
    out = tmp_path / "copy"
    copy_snapshot(root / "fixtures/pre", out)
    assert load_snapshot(out) == pre_snapshot
    with pytest.raises(ValueError, match="new or empty"):
        copy_snapshot(root / "fixtures/post", out)
    assert load_snapshot(out) == pre_snapshot
    with pytest.raises(ValueError, match="does not exist"):
        copy_snapshot(tmp_path / "missing", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_a_bgp_section_keyed_by_vrf_survives_a_write_and_load(tmp_path):
    section = {
        "r1": {
            "vrfs": {
                "default": {"neighbors": {"198.51.100.1": {"state": "Established", "remote_as": 65010}}},
                "NCV": {"neighbors": {"198.51.100.1": {"state": "Idle", "remote_as": None}}},
            }
        }
    }
    write_sections(tmp_path, {"bgp": section})
    assert load_snapshot(tmp_path)["bgp"] == section
