"""Copying a snapshot validates input and never publishes a partial directory."""

from __future__ import annotations

import pytest

from ncv.snapshot import copy_snapshot, load_snapshot


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
