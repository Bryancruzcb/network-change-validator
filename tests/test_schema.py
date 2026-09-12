"""Snapshot section validation reports the offending file and field."""

from __future__ import annotations

import json

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
