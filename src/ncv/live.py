from __future__ import annotations

import json
import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from .normalize import learned_to_mapping, normalize_learn
from .schema import LEARNED_FEATURES
from .snapshot import snapshot_destination, write_sections

FEATURES = LEARNED_FEATURES
# The prompts of a device that has no configuration yet: NX-OS's POAP, secure-password and
# admin-password questions, and the setup dialog and enable-secret question of IOS and IOS XE.
FIRST_BOOT_DIALOG = (
    r"Abort( Power On)? Auto Provisioning|Do you want to enforce secure password standard|"
    r"Enter the password for|(initial|basic) configuration dialog|Enter enable secret"
)
FIRST_BOOT_REFUSAL = "device is at a first-boot setup dialog; ncv will not answer it"
RUNNING_CONFIG_STEP = "show running-config"
RUNNING_CONFIG_REFUSAL = "empty, non-text, or CLI error running-config response"


class FirstBootDialogError(RuntimeError):
    """The first-boot guard's refusal. It has its own type so that a connect it stopped can be
    told apart from every other failed connect, however Unicon wraps it."""


def caused_by(exc: BaseException, kind: type[BaseException]) -> bool:
    """Whether the exception, or anything it was raised from or while handling, is of the given
    kind."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [exc]
    while pending:
        link = pending.pop()
        if link is None or id(link) in seen:
            continue
        if isinstance(link, kind):
            return True
        seen.add(id(link))
        pending += [link.__cause__, link.__context__]
    return False


def failure_detail(operation: str, exc: Exception) -> str:
    """What a failed capture step says about its exception. Unicon reports a connect the
    first-boot guard stopped as its own `failed to connect`, with the guard's reason only in the
    chain of causes, so that case gives the reason instead. Unicon's timeout and failure
    exceptions quote the device's output so far, and during the running-config read that output
    is a running config with its passwords, so that step names only the exception's type. ncv's
    own refusal of the response holds no device output and keeps its text."""
    if caused_by(exc, FirstBootDialogError):
        return FIRST_BOOT_REFUSAL
    if operation != RUNNING_CONFIG_STEP or (
        isinstance(exc, ValueError) and str(exc) == RUNNING_CONFIG_REFUSAL
    ):
        return str(exc)
    return f"{type(exc).__name__} (details withheld: the device's output can hold passwords)"


def _refuse_first_boot_dialog(spawn: Any) -> None:
    # Unicon calls an action with what its parameter names ask for, and refuses a `spawn` that is
    # not a plain positional parameter, so this one has no default.
    raise FirstBootDialogError(FIRST_BOOT_REFUSAL)


def first_boot_guard() -> Any | None:
    """A Unicon dialog that fails the connection at a first-boot setup dialog, or None when
    Unicon cannot be imported.

    Left alone, Unicon's connect answers that dialog itself: on NX-OS it aborts POAP, declines
    the secure-password standard, and types the admin password, and its generic plugin answers
    the setup dialog and `Enter enable secret`. That is a configuration change made during a
    capture, which ncv never makes. Passed as `connect_reply`, this dialog comes before
    Unicon's own statements, so it sees the prompt first. Checked offline against Unicon 26.8's
    mock devices only.
    """
    try:
        from unicon.eal.dialogs import Dialog, Statement
    except ImportError:
        return None
    statement = Statement(pattern=FIRST_BOOT_DIALOG, action=_refuse_first_boot_dialog, loop_continue=False)
    return Dialog([statement])


def snapshot_live(
    testbed_path: str,
    output_dir: str,
    i_am_in_a_lab: bool,
    features: tuple[str, ...] = FEATURES,
) -> Path:
    if not i_am_in_a_lab:
        raise PermissionError(
            "live snapshot refused: pass --i-am-in-a-lab after pointing the testbed at a lab you own"
        )
    unsupported = [name for name in features if name not in FEATURES]
    if not features or unsupported:
        raise ValueError(f"features must be a non-empty subset of {', '.join(FEATURES)}")
    try:
        from genie.testbed import load
    except ImportError as exc:
        raise RuntimeError(
            "pyATS/Genie is not installed; install the optional lab extra: python3 -m pip install -e '.[lab]'"
        ) from exc

    with snapshot_destination(output_dir) as stage:
        try:
            testbed = load(testbed_path)
        except Exception as exc:
            raise RuntimeError(f"cannot load lab testbed {testbed_path}: {exc}") from exc
        if not testbed.devices:
            raise ValueError("lab testbed has no devices")
        for name in testbed.devices:
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError(f"unsupported lab device name {name!r}; use letters, digits, _ or -")
        sections: dict[str, dict[str, Any]] = {name: {} for name in (*features, "config")}
        raw_dir = stage / "raw"
        raw_dir.mkdir()
        for name, device in testbed.devices.items():
            operation = "connect"
            try:
                # Unicon defaults can initialize configuration. Disable initialization,
                # including testbed arguments which otherwise take precedence over kwargs.
                for connection in device.connections.values():
                    if isinstance(connection, dict):
                        arguments = connection.setdefault("arguments", {})
                        arguments.update(init_exec_commands=[], init_config_commands=[])
                # A fresh guard per device: a Unicon dialog is not documented as reusable.
                guard = first_boot_guard()
                refuse_first_boot = {} if guard is None else {"connect_reply": guard}
                device.connect(
                    log_stdout=False, init_exec_commands=[], init_config_commands=[], **refuse_first_boot
                )
                for feature in features:
                    operation = f"learn {feature}"
                    dumped = learned_to_mapping(device.learn(feature))
                    sections[feature].update(normalize_learn(name, feature, dumped))
                    (raw_dir / f"{name}_{feature}.json").write_text(
                        json.dumps(dumped, indent=2, default=str) + "\n", encoding="utf-8"
                    )
                operation = RUNNING_CONFIG_STEP
                running = device.execute(RUNNING_CONFIG_STEP)
                if not isinstance(running, str) or not running.strip() or running.lstrip().startswith("%"):
                    raise ValueError(RUNNING_CONFIG_REFUSAL)
                sections["config"][name] = {"running": running}
                (raw_dir / f"{name}_config.txt").write_text(running, encoding="utf-8")
            except Exception as exc:
                detail = failure_detail(operation, exc)
                raise RuntimeError(f"lab capture failed for {name} during {operation}: {detail}") from exc
            finally:
                with suppress(Exception):  # Preserve the collection error, if any.
                    device.disconnect()
        write_sections(stage, sections)
        meta = {
            "source": "live-pyats",
            "testbed": testbed_path,
            "devices": list(testbed.devices),
            "features": [*features, "config"],
        }
        (stage / "SOURCE.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return Path(output_dir)
