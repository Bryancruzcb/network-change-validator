from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .normalize import merge_section, normalize_learn

FEATURES = ("ospf", "routing", "interface")


def snapshot_live(testbed_path: str, output_dir: str, i_am_in_a_lab: bool) -> Path:
    if not i_am_in_a_lab:
        raise PermissionError(
            "live snapshot refused: pass --i-am-in-a-lab after pointing the testbed at a lab you own"
        )
    try:
        from genie.testbed import load
    except ImportError as exc:
        raise RuntimeError(
            "pyATS/Genie is not installed. pip install 'pyats[full]' in a venv, then retry"
        ) from exc

    out = Path(output_dir)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    testbed = load(testbed_path)
    sections: dict[str, dict[str, Any]] = {name: {} for name in (*FEATURES, "config")}

    for name, device in testbed.devices.items():
        device.connect(log_stdout=False)
        try:
            for feature in FEATURES:
                try:
                    learned = device.learn(feature)
                except Exception as exc:
                    (raw_dir / f"{name}_{feature}_error.txt").write_text(str(exc), encoding="utf-8")
                    continue
                dumped = _dump(learned)
                (raw_dir / f"{name}_{feature}.json").write_text(
                    json.dumps(dumped, indent=2, default=str) + "\n", encoding="utf-8"
                )
                sections[feature] = merge_section(
                    sections[feature], normalize_learn(name, feature, dumped)
                )
            try:
                running = device.execute("show running-config")
            except Exception as exc:
                running = f"! collect failed: {exc}\n"
            sections["config"][name] = {"running": str(running)}
            (raw_dir / f"{name}_config.txt").write_text(str(running), encoding="utf-8")
        finally:
            try:
                device.disconnect()
            except Exception:
                pass

    for feature, payload in sections.items():
        (out / f"{feature}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    meta = {
        "source": "live-pyats",
        "testbed": testbed_path,
        "devices": list(testbed.devices.keys()),
        "features": list(FEATURES) + ["config"],
    }
    (out / "SOURCE.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return out


def _dump(learned: Any) -> Any:
    if hasattr(learned, "to_dict"):
        try:
            return learned.to_dict()
        except Exception:
            pass
    info = getattr(learned, "info", None)
    if isinstance(info, dict):
        return {"info": info}
    if isinstance(learned, dict):
        return learned
    return {"repr": repr(learned)}
