"""Live capture paths exercised with fake connections; no live lab required."""

from __future__ import annotations

import builtins
import json
from unittest.mock import Mock

import pytest

from ncv.cli import main
from ncv.live import snapshot_live
from ncv.snapshot import load_snapshot


def test_live_refuses_without_lab_flag(tmp_path):
    with pytest.raises(PermissionError):
        snapshot_live("testbeds/lab.yaml", str(tmp_path / "out"), i_am_in_a_lab=False)
    assert not (tmp_path / "out").exists()


def test_guard_precedes_import_and_output(tmp_path, monkeypatch, capsys):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(("genie", "pyats"))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    out = tmp_path / "out"
    assert main(["snapshot", "--testbed", "lab.yaml", "--output", str(out)]) == 2
    assert "--i-am-in-a-lab" in capsys.readouterr().err
    assert not out.exists()


def test_optional_dependency_error(tmp_path, monkeypatch):
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name.startswith("genie"):
            raise ImportError("mock missing dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(RuntimeError, match="optional lab extra"):
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    assert not (tmp_path / "out").exists()


def test_mock_capture_is_complete_and_disables_initialization(tmp_path, fake_lab):
    device, _ = fake_lab
    out = snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.connect.assert_called_once_with(log_stdout=False, init_exec_commands=[], init_config_commands=[])
    assert device.connections["cli"]["arguments"]["init_config_commands"] == []
    device.execute.assert_called_once_with("show running-config")
    device.configure.assert_not_called()
    device.disconnect.assert_called_once()
    snapshot = load_snapshot(out)
    assert snapshot["interface"]["r1"]["interfaces"]["Gi1"]["crc"] == 0
    assert snapshot["bgp"]["r1"]["neighbors"]["203.0.113.1"]["state"] == "established"
    assert json.loads((out / "SOURCE.json").read_text())["devices"] == ["r1"]
    assert len(list((out / "raw").iterdir())) == 5


@pytest.mark.parametrize("operation", ["connect", "learn", "execute"])
def test_failed_capture_disconnects_and_never_publishes(tmp_path, fake_lab, operation):
    device, _ = fake_lab
    getattr(device, operation).side_effect = RuntimeError("synthetic failure")
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="lab capture failed for r1"):
        snapshot_live("lab.yaml", str(out), True)
    device.disconnect.assert_called_once()
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []


def test_nonempty_output_refused_before_testbed_load(tmp_path, fake_lab):
    device, load = fake_lab
    (tmp_path / "keep").write_text("evidence")
    with pytest.raises(ValueError, match="new or empty"):
        snapshot_live("lab.yaml", str(tmp_path), True)
    load.assert_not_called()
    device.connect.assert_not_called()
    assert (tmp_path / "keep").read_text() == "evidence"


@pytest.mark.parametrize("devices", [{}, {"../escape": Mock()}])
def test_invalid_testbed_does_not_connect(tmp_path, fake_lab, devices):
    device, load = fake_lab
    load.return_value.devices = devices
    with pytest.raises(ValueError):
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.connect.assert_not_called()
    assert not (tmp_path / "out").exists()


def test_features_can_be_narrowed_to_what_the_lab_runs(tmp_path, fake_lab):
    device, _ = fake_lab
    out = snapshot_live("lab.yaml", str(tmp_path / "out"), True, features=("interface",))
    assert [call.args[0] for call in device.learn.call_args_list] == ["interface"]
    snapshot = load_snapshot(out)
    assert snapshot["bgp"] == {} and snapshot["ospf"] == {}
    assert json.loads((out / "SOURCE.json").read_text())["features"] == ["interface", "config"]


@pytest.mark.parametrize("features", [(), ("ospf", "arp")])
def test_unknown_features_are_refused_before_connecting(tmp_path, fake_lab, features):
    device, load = fake_lab
    with pytest.raises(ValueError, match="subset"):
        snapshot_live("lab.yaml", str(tmp_path / "out"), True, features=features)
    load.assert_not_called()
    device.connect.assert_not_called()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("response", ["", None, "% Invalid input detected at '^' marker."])
def test_invalid_config_response_aborts_capture(tmp_path, fake_lab, response):
    device, _ = fake_lab
    device.execute.return_value = response
    with pytest.raises(RuntimeError, match="running-config response"):
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.disconnect.assert_called_once()
    assert not (tmp_path / "out").exists()
