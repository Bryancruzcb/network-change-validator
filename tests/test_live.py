"""Synthetic Genie-shaped inputs and fake connections; no live lab required."""
import builtins
import json
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from ncv.cli import main
from ncv.live import snapshot_live
from ncv.normalize import normalize_learn
from ncv.snapshot import load_snapshot


@pytest.fixture
def fake_lab(monkeypatch):
    device = Mock()
    device.connections = {"cli": {"arguments": {"init_config_commands": ["hostname unwanted"]}}}
    device.learn.side_effect = lambda feature: SimpleNamespace(info={
        "ospf": {"neighbors": {}},
        "routing": {"vrf": {"default": {"address_family": {"ipv4": {"routes": {}}}}}},
        "interface": {"interfaces": {"Gi1": {"oper_status": "up", "counters": {"in_errors": 0, "in_crc_errors": 0}}}},
    }[feature])
    device.execute.return_value = "hostname r1\n"
    module = ModuleType("genie.testbed")
    module.load = Mock(return_value=SimpleNamespace(devices={"r1": device}))
    monkeypatch.setitem(__import__("sys").modules, "genie", ModuleType("genie"))
    monkeypatch.setitem(__import__("sys").modules, "genie.testbed", module)
    return device, module.load


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
    assert load_snapshot(out)["interface"]["r1"]["interfaces"]["Gi1"]["crc"] == 0
    assert json.loads((out / "SOURCE.json").read_text())["devices"] == ["r1"]
    assert len(list((out / "raw").iterdir())) == 4


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


def test_ospf_preserves_parent_interface():
    data = {"info": {"vrf": {"default": {"address_family": {"ipv4": {"instance": {"1": {
        "areas": {"0.0.0.0": {"interfaces": {"Gi1": {"neighbors": {
            "10.0.0.2": {"state": "FULL", "address": "10.0.0.2"}
        }}}}}
    }}}}}}}}
    neighbor = normalize_learn("r1", "ospf", data)["r1"]["neighbors"]["10.0.0.2"]
    assert neighbor == {"state": "FULL", "interface": "Gi1"}


def test_ospf_duplicate_neighbor_is_rejected():
    data = {"vrf": {"default": {"interfaces": {
        name: {"neighbors": {"10.0.0.2": {"state": "FULL"}}} for name in ("Gi1", "Gi2")
    }}}}
    with pytest.raises(ValueError, match="ambiguous OSPF"):
        normalize_learn("r1", "ospf", data)


def test_routing_uses_source_protocol_not_route_preference():
    data = {"vrf": {"default": {"address_family": {"ipv4": {"routes": {
        "10.0.0.0/24": {"source_protocol": "ospf", "route_preference": 110},
        "10.1.0.0/24": {"route_preference": 110},
    }}}}}}
    routes = normalize_learn("r1", "routing", data)["r1"]["vrfs"]["default"]["routes"]
    assert routes["10.0.0.0/24"]["protocol"] == "ospf"
    assert routes["10.1.0.0/24"]["protocol"] is None


def test_interface_missing_counters_remain_unknown():
    data = {"info": {"interfaces": {"Gi1": {"oper_status": "up", "counters": {"in_errors": "0"}}}}}
    rec = normalize_learn("r1", "interface", data)["r1"]["interfaces"]["Gi1"]
    assert rec == {"oper_status": "up", "in_errors": 0, "crc": None}


@pytest.mark.parametrize("feature", ["ospf", "routing", "interface", "unknown"])
def test_unsupported_learn_shapes_rejected(feature):
    with pytest.raises(ValueError, match="unsupported"):
        normalize_learn("r1", feature, {"unexpected": {}})


@pytest.mark.parametrize("response", ["", None, "% Invalid input detected at '^' marker."])
def test_invalid_config_response_aborts_capture(tmp_path, fake_lab, response):
    device, _ = fake_lab
    device.execute.return_value = response
    with pytest.raises(RuntimeError, match="running-config response"):
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.disconnect.assert_called_once()
    assert not (tmp_path / "out").exists()
