"""Live capture paths exercised with fake connections; no live lab required."""

from __future__ import annotations

import builtins
import inspect
import json
import re
import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from ncv.cli import main
from ncv.live import FIRST_BOOT_REFUSAL, FirstBootDialogError, caused_by, first_boot_guard, snapshot_live
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


class SubCommandFailure(Exception):
    """Named like Unicon's, whose text quotes everything the device printed before it failed."""


def test_a_failed_running_config_read_names_only_the_exception_type(tmp_path, fake_lab, capsys):
    device, _ = fake_lab
    device.execute.side_effect = SubCommandFailure(
        "Command 'show running-config' failed, buffer: 'enable password 0 MARKER-PASSWORD'"
    )
    out = tmp_path / "out"
    with pytest.raises(RuntimeError) as raised:
        snapshot_live("lab.yaml", str(out), True)
    assert str(raised.value) == (
        "lab capture failed for r1 during show running-config: SubCommandFailure "
        "(details withheld: the device's output can hold passwords)"
    )
    assert raised.value.__cause__ is device.execute.side_effect
    device.disconnect.assert_called_once()
    assert not out.exists()
    # The CLI prints the message alone, so the device's output reaches no terminal or log.
    assert main(["snapshot", "--testbed", "lab.yaml", "--output", str(out), "--i-am-in-a-lab"]) == 2
    captured = capsys.readouterr()
    assert "SubCommandFailure (details withheld" in captured.err
    assert "MARKER-PASSWORD" not in captured.err + captured.out


@pytest.mark.parametrize(
    "operation, failure, message",
    [
        ("learn", RuntimeError("synthetic learn failure"), "during learn ospf: synthetic learn failure"),
        ("connect", ConnectionError("no answer on port 23"), "during connect: no answer on port 23"),
        (
            "execute",
            None,
            "during show running-config: empty, non-text, or CLI error running-config response",
        ),
    ],
)
def test_every_other_failed_step_keeps_the_exception_text(tmp_path, fake_lab, operation, failure, message):
    device, _ = fake_lab
    if failure is None:
        device.execute.return_value = ""  # ncv's own refusal of the response
    else:
        getattr(device, operation).side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    assert str(raised.value) == f"lab capture failed for r1 {message}"


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
        "Do you want to enforce secure password standard (yes/no) [y]:",
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
    with pytest.raises(FirstBootDialogError) as raised:
        statement.action(object())
    assert str(raised.value) == "device is at a first-boot setup dialog; ncv will not answer it"
    assert str(raised.value) == FIRST_BOOT_REFUSAL


def _wrapped_the_way_unicon_wraps(link: str) -> Exception:
    """A failed connect whose chain of causes ends at the guard's refusal, linked one of the two
    ways Python chains exceptions: `__cause__` (raise ... from) or `__context__` (a raise inside
    an except)."""
    refusal = FirstBootDialogError(FIRST_BOOT_REFUSAL)
    inner, outer = TimeoutError("sub command failed"), ConnectionError("failed to connect to r1")
    setattr(inner, f"__{link}__", refusal)
    setattr(outer, f"__{link}__", inner)
    return outer


@pytest.mark.parametrize("link", ["cause", "context"])
def test_a_connect_the_guard_stopped_names_the_first_boot_dialog(tmp_path, fake_lab, capsys, link):
    """Real Unicon 26.8 reports it as `failed to connect to R3`, with the guard's reason two
    causes down; without this the operator cannot tell it from a wrong console path."""
    device, _ = fake_lab
    device.connect.side_effect = _wrapped_the_way_unicon_wraps(link)
    expected = f"lab capture failed for r1 during connect: {FIRST_BOOT_REFUSAL}"
    with pytest.raises(RuntimeError) as raised:
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    assert str(raised.value) == expected
    device.disconnect.assert_called_once()
    assert not (tmp_path / "out").exists()
    assert (
        main(["snapshot", "--testbed", "lab.yaml", "--output", str(tmp_path / "cli"), "--i-am-in-a-lab"]) == 2
    )
    assert capsys.readouterr().err.strip() == f"ncv: error: {expected}"


def test_a_connect_that_failed_for_another_reason_keeps_its_own_message(tmp_path, fake_lab):
    device, _ = fake_lab
    try:
        raise ConnectionError("failed to connect to r1") from TimeoutError("no answer")
    except ConnectionError as failure:
        device.connect.side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    assert str(raised.value) == "lab capture failed for r1 during connect: failed to connect to r1"


def test_the_guards_own_refusal_is_the_one_the_capture_recognises(tmp_path, fake_lab, fake_unicon):
    """The guard's action and the capture's message meet only through the exception's type, so
    this takes the exception from the action itself and wraps it as real Unicon 26.8 does: a
    connection error raised from a state machine error raised from the refusal."""
    device, _ = fake_lab
    (statement,) = first_boot_guard().statements
    with pytest.raises(FirstBootDialogError) as refused:
        statement.action(object())
    state_machine, failed = RuntimeError("state machine"), ConnectionError("failed to connect to r1")
    state_machine.__cause__, failed.__cause__ = refused.value, state_machine
    device.connect.side_effect = failed
    with pytest.raises(RuntimeError) as raised:
        snapshot_live("lab.yaml", str(tmp_path / "out"), True)
    assert str(raised.value) == f"lab capture failed for r1 during connect: {FIRST_BOOT_REFUSAL}"


def test_caused_by_reads_the_whole_chain():
    refusal, middle, outer = FirstBootDialogError("x"), TimeoutError("y"), ConnectionError("z")
    middle.__cause__, outer.__context__ = refusal, middle
    assert caused_by(refusal, FirstBootDialogError)
    assert caused_by(outer, FirstBootDialogError)
    assert not caused_by(outer, KeyError)
    raised_from_another = ConnectionError("z")
    raised_from_another.__cause__, raised_from_another.__context__ = OSError("w"), refusal
    assert caused_by(raised_from_another, FirstBootDialogError)


def test_caused_by_ends_on_a_loop_of_causes():
    """Run on its own thread with a time limit, so a walk that never ends fails here instead of
    hanging the suite."""
    first, second = ValueError("a"), ValueError("b")
    first.__cause__, second.__cause__ = second, first
    answers: list[bool] = []
    walk = threading.Thread(
        target=lambda: answers.append(caused_by(first, FirstBootDialogError)), daemon=True
    )
    walk.start()
    walk.join(timeout=5)
    assert answers == [False]


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
