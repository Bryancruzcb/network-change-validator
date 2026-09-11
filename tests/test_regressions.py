"""Offline regressions for incomplete evidence and misleading passes."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest
import yaml

from ncv.cli import main
from ncv.intent import ConfigRule, load_intent
from ncv.policy import Finding, evaluate
from ncv.report import write_report
from ncv.snapshot import copy_snapshot, load_snapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def baseline():
    return load_intent(ROOT / "intents/demo.yaml"), load_snapshot(ROOT / "fixtures/pre")


@pytest.mark.parametrize("mutation", ["missing_interface", "missing_counter", "null_counter"])
def test_missing_counters_are_findings(baseline, mutation):
    intent, pre = baseline
    post = deepcopy(pre)
    interfaces = post["interface"]["r1"]["interfaces"]
    if mutation == "missing_interface":
        interfaces.clear()
    elif mutation == "missing_counter":
        del interfaces["GigabitEthernet0/1"]["crc"]
    else:
        interfaces["GigabitEthernet0/1"]["crc"] = None
    finding, = evaluate(intent, pre, post)
    assert finding.policy_id == "V_ERR"
    assert finding.before == {"in_errors": 0, "crc": 0}
    assert finding.after["crc"] is None


@pytest.mark.parametrize("field,value", [("interface", "GigabitEthernet0/2"), ("interface", None), ("state", "UP")])
def test_adjacency_requires_full_on_requested_interface(baseline, field, value):
    intent, pre = baseline
    post = deepcopy(pre)
    post["ospf"]["r1"]["neighbors"]["10.0.12.2"][field] = value
    finding, = evaluate(intent, pre, post)
    assert finding.policy_id == "V_ADJ"
    assert finding.after[field] == value


def test_counter_limits_are_inclusive_absolute_values(baseline):
    intent, pre = baseline
    post = deepcopy(pre)
    rec = post["interface"]["r1"]["interfaces"]["GigabitEthernet0/1"]
    rec.update(in_errors=10, crc=5)
    assert evaluate(intent, pre, post) == []
    rec["in_errors"] = 11
    assert [f.policy_id for f in evaluate(intent, post, post)] == ["V_ERR"]


def test_config_matches_full_trimmed_lines(baseline):
    intent, pre = baseline
    intent = replace(intent, must_include=(ConfigRule("r1", ("ntp server 192.0.2.1",)),),
                     must_absent=(ConfigRule("r1", ("username left",)),))
    post = deepcopy(pre)
    post["config"]["r1"]["running"] = "ntp server 192.0.2.10\nusername leftover\n"
    finding, = evaluate(intent, pre, post)
    assert finding.path.endswith("must_include")
    post["config"]["r1"]["running"] += "  ntp server 192.0.2.1  \n"
    assert evaluate(intent, pre, post) == []


def test_absence_cannot_be_proven_without_config(baseline):
    intent, pre = baseline
    intent = replace(intent, must_include=())
    post = deepcopy(pre)
    del post["config"]["r1"]
    finding, = evaluate(intent, pre, post)
    assert finding.policy_id == "V_DRIFT"
    assert finding.after is None


@pytest.mark.parametrize("change,match", [
    ({"devices": "r1"}, "expected a list"),
    ({"version": 2}, "only version 1"),
    ({"rouets": []}, "unknown field"),
    ({"interfaces": [{"device": "r1", "name": "Gi1", "max_crc": -1}]}, "non-negative"),
    ({"interfaces": [{"device": "r1", "name": "Gi1", "max_crc": True}]}, "non-negative"),
    ({"routes": [{"device": "r3", "prefix": "10.0.0.0/24"}]}, "not declared"),
    ({"routes": [{"device": "r1", "prefix": "bad"}]}, "invalid network"),
    ({"adjacencies": [{"device": "r1", "protocol": "bgp", "neighbor": "1.1.1.1"}]}, "only ospf"),
])
def test_invalid_intent_has_field_context(tmp_path, change, match):
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump({"intent_id": "test", "devices": ["r1"], **change}))
    with pytest.raises(ValueError, match=match) as error:
        load_intent(path)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("payload", [[], {"r1": []}, {"r1": {"interfaces": {"Gi1": {"crc": "oops"}}}}])
def test_bad_snapshot_has_file_context(tmp_path, payload):
    path = tmp_path / "interface.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="interface.json"):
        load_snapshot(tmp_path)


def test_invalid_input_cli_is_exit_two_without_traceback(tmp_path, capsys):
    assert main(["diff", str(tmp_path), str(tmp_path), "--intent", str(ROOT / "intents/demo.yaml"),
                 "--report", str(tmp_path / "report")]) == 2
    captured = capsys.readouterr()
    assert "no snapshot device data" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("sources", [[], ["--from-dir", "fixtures/pre", "--testbed", "lab.yaml"]])
def test_snapshot_requires_exactly_one_source(tmp_path, sources):
    with pytest.raises(SystemExit) as error:
        main(["snapshot", "--output", str(tmp_path / "out"), *sources])
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()


def test_snapshot_copy_validates_and_preserves_evidence(tmp_path, baseline):
    out = tmp_path / "copy"
    copy_snapshot(ROOT / "fixtures/pre", out)
    assert load_snapshot(out) == baseline[1]
    with pytest.raises(ValueError, match="new or empty"):
        copy_snapshot(ROOT / "fixtures/post", out)
    assert load_snapshot(out) == baseline[1]
    with pytest.raises(ValueError, match="does not exist"):
        copy_snapshot(tmp_path / "missing", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_report_escapes_markdown_and_keeps_json_evidence(tmp_path):
    finding = Finding("V_DRIFT", "r|1", "config", None, "<tag>", "line\nbreak | <script>", "review")
    path = write_report(tmp_path, "demo\n# injected", [finding])
    assert json.loads(path.read_text())["findings"][0]["after"] == "<tag>"
    md = (tmp_path / "report.md").read_text()
    assert "r\\|1" in md and "&lt;script&gt;" in md
    assert "\n# injected" not in md
