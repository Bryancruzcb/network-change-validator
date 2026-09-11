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
