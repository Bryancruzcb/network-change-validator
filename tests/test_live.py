"""Live capture paths exercised with fake connections; no live lab required."""

from __future__ import annotations

import builtins
import inspect
import json
import re
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from ncv.cli import main
from ncv.live import FIRST_BOOT_REFUSAL, first_boot_guard, snapshot_live
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
    assert snapshot["bgp"]["r1"]["vrfs"]["default"]["neighbors"]["203.0.113.1"]["state"] == "established"
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


def test_a_feature_the_device_does_not_run_fails_the_capture_by_name(tmp_path, fake_lab):
    device, _ = fake_lab
    device.learn.side_effect = lambda feature: SimpleNamespace()  # Genie learned nothing: no `info`
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="during learn ospf: learn returned no info.*--features"):
        snapshot_live("lab.yaml", str(out), True)
    device.disconnect.assert_called_once()
    assert not out.exists()


@pytest.mark.parametrize("response", ["", None, "% Invalid input detected at '^' marker."])
def test_invalid_config_response_aborts_capture(tmp_path, fake_lab, response):
    device, _ = fake_lab
    device.execute.return_value = response
    with pytest.raises(RuntimeError, match="running-config response"):
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.disconnect.assert_called_once()
    assert not (tmp_path / "out").exists()


class _Statement:
    def __init__(self, pattern, action, loop_continue):
        self.pattern, self.action, self.loop_continue = pattern, action, loop_continue


class _Dialog:
    def __init__(self, statements):
        self.statements = statements


@pytest.fixture
def fake_unicon(monkeypatch):
    """unicon.eal.dialogs with the two classes the guard builds, recording what it was given."""
    dialogs = ModuleType("unicon.eal.dialogs")
    dialogs.Dialog, dialogs.Statement = _Dialog, _Statement
    monkeypatch.setitem(sys.modules, "unicon", ModuleType("unicon"))
    monkeypatch.setitem(sys.modules, "unicon.eal", ModuleType("unicon.eal"))
    monkeypatch.setitem(sys.modules, "unicon.eal.dialogs", dialogs)
    return dialogs


def test_the_capture_connects_with_a_guard_against_a_first_boot_dialog(tmp_path, fake_lab, fake_unicon):
    device, _ = fake_lab
    snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.connect.assert_called_once()
    kwargs = device.connect.call_args.kwargs
    assert kwargs.pop("connect_reply").__class__ is _Dialog
    assert kwargs == {"log_stdout": False, "init_exec_commands": [], "init_config_commands": []}


@pytest.mark.parametrize(
    "prompt",
    [
        "Abort Power On Auto Provisioning [yes - continue with normal setup, skip - bypass password "
        "and basic configuration, no - continue with Power On Auto Provisioning] (yes/skip/no)[no]:",
        'Enter the password for "admin":',
        "Would you like to enter the initial configuration dialog? [yes/no]:",
        "Would you like to enter the basic configuration dialog (yes/no):",
        "Enter enable secret:",
    ],
)
def test_the_guard_matches_each_first_boot_prompt_and_its_action_raises(fake_unicon, prompt):
    (statement,) = first_boot_guard().statements
    assert statement.loop_continue is False
    assert re.search(statement.pattern, prompt)
    with pytest.raises(RuntimeError) as raised:
        statement.action(object())
    assert str(raised.value) == "device is at a first-boot setup dialog; ncv will not answer it"
    assert str(raised.value) == FIRST_BOOT_REFUSAL


def test_the_guard_action_takes_spawn_the_way_unicon_requires(fake_unicon):
    """Unicon 26.8 refuses to build a Statement whose action has `spawn` with a default value
    (StatementValidationError, found with the real Unicon); the fake here does not check that."""
    (statement,) = first_boot_guard().statements
    spawn = inspect.signature(statement.action).parameters["spawn"]
    assert spawn.default is inspect.Parameter.empty
    assert spawn.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


@pytest.mark.parametrize("prompt", ["R3 login:", "Password:", "R1#", "R1>", "Escape character is '^]'."])
def test_the_guard_leaves_an_ordinary_login_to_unicon(fake_unicon, prompt):
    (statement,) = first_boot_guard().statements
    assert not re.search(statement.pattern, prompt)


def test_without_unicon_the_capture_still_connects_without_a_guard(tmp_path, fake_lab):
    device, _ = fake_lab
    assert first_boot_guard() is None
    snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    device.connect.assert_called_once_with(log_stdout=False, init_exec_commands=[], init_config_commands=[])
