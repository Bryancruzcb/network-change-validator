from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .schema import SECTIONS, validate_section


def load_snapshot(dir_path: str | Path) -> dict[str, Any]:
    root = Path(dir_path)
    if not root.is_dir():
        raise ValueError(f"snapshot directory does not exist or is not a directory: {root}")
    snap: dict[str, Any] = {}
    for name in SECTIONS:
        fp = root / f"{name}.json"
        if fp.exists():
            try:
                snap[name] = json.loads(fp.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {fp}: {exc}") from exc
            validate_section(name, snap[name], str(fp))
        else:
            snap[name] = {}
    if not any(snap.values()):
        expected = ", ".join(name + ".json" for name in SECTIONS)
        raise ValueError(f"no snapshot device data in {root}; expected {expected}")
    return snap


@contextmanager
def snapshot_destination(output_dir: str | Path) -> Iterator[Path]:
    """Publish a complete capture only after every collection/write succeeds."""
    out = Path(output_dir)
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError(f"snapshot output must be a new or empty directory: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="ncv-snapshot-", dir=out.parent) as temp:
        stage = Path(temp) / "snapshot"
        stage.mkdir()
        yield stage
        if out.exists():
            out.rmdir()  # Only removes an empty directory, even if it changed meanwhile.
        stage.rename(out)


def write_sections(root: Path, snapshot: dict[str, Any]) -> None:
    for name in SECTIONS:
        payload = snapshot.get(name, {})
        validate_section(name, payload, name)
        (root / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def copy_snapshot(source: str | Path, output_dir: str | Path) -> Path:
    snapshot = load_snapshot(source)
    with snapshot_destination(output_dir) as stage:
        write_sections(stage, snapshot)
        provenance = Path(source) / "SOURCE.json"
        if provenance.is_file():
            (stage / "SOURCE.json").write_bytes(provenance.read_bytes())
    return Path(output_dir)
