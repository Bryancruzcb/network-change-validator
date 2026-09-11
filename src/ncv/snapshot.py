from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_snapshot(dir_path: str | Path) -> dict[str, Any]:
    root = Path(dir_path)
    if not root.is_dir():
        raise FileNotFoundError(root)
    snap: dict[str, Any] = {}
    for name in ("ospf", "routing", "interface", "config"):
        fp = root / f"{name}.json"
        if fp.exists():
            snap[name] = json.loads(fp.read_text(encoding="utf-8"))
        else:
            snap[name] = {}
    if not any(snap.values()):
        raise ValueError(f"no snapshot files in {root}")
    return snap
