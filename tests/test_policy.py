from pathlib import Path

from ncv.intent import load_intent
from ncv.policy import evaluate
from ncv.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_demo_fixtures_find_four_classes():
    intent = load_intent(ROOT / "intents" / "demo.yaml")
    pre = load_snapshot(ROOT / "fixtures" / "pre")
    post = load_snapshot(ROOT / "fixtures" / "post")
    findings = evaluate(intent, pre, post)
    ids = {f.policy_id for f in findings}
    assert ids == {"V_ADJ", "V_ROUTE", "V_ERR", "V_DRIFT"}
    assert len(findings) == 7


def test_clean_pair_is_silent():
    intent = load_intent(ROOT / "intents" / "demo.yaml")
    pre = load_snapshot(ROOT / "fixtures" / "pre")
    findings = evaluate(intent, pre, pre)
    assert findings == []


def test_live_refuses_without_lab_flag():
    from ncv.live import snapshot_live
    import pytest

    with pytest.raises(PermissionError):
        snapshot_live("testbeds/lab.yaml", "/tmp/ncv-out", i_am_in_a_lab=False)
