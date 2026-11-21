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
# The prompts of a device that has no configuration yet: NX-OS's POAP and admin-password
# questions, and the setup dialog and enable-secret question of IOS and IOS XE.
FIRST_BOOT_DIALOG = (
    r"Abort( Power On)? Auto Provisioning|Enter the password for|"
    r"(initial|basic) configuration dialog|Enter enable secret"
)
FIRST_BOOT_REFUSAL = "device is at a first-boot setup dialog; ncv will not answer it"


def _refuse_first_boot_dialog(spawn: Any) -> None:
    # Unicon calls an action with what its parameter names ask for, and refuses a `spawn` that is
    # not a plain positional parameter, so this one has no default.
    raise RuntimeError(FIRST_BOOT_REFUSAL)


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
                operation = "show running-config"
                running = device.execute("show running-config")
                if not isinstance(running, str) or not running.strip() or running.lstrip().startswith("%"):
                    raise ValueError("empty, non-text, or CLI error running-config response")
                sections["config"][name] = {"running": running}
                (raw_dir / f"{name}_config.txt").write_text(running, encoding="utf-8")
            except Exception as exc:
                raise RuntimeError(f"lab capture failed for {name} during {operation}: {exc}") from exc
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
