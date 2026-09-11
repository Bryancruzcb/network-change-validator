from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

SECTIONS = ("ospf", "routing", "interface", "config")


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected a JSON object")
    return value


def _text_fields(record: dict[str, Any], fields: tuple[str, ...], where: str) -> None:
    for key in fields:
        if record.get(key) is not None and not isinstance(record[key], str):
            raise ValueError(f"{where}.{key}: expected a string or null")


def validate_section(name: str, section: Any, where: str) -> None:
    for device, node in _object(section, where).items():
        loc = f"{where}.{device}"
        node = _object(node, loc)
        if name == "config":
            _text_fields(node, ("running",), loc)
        elif name == "ospf":
            for neighbor, rec in _object(node.get("neighbors", {}), f"{loc}.neighbors").items():
                path = f"{loc}.neighbors.{neighbor}"
                _text_fields(_object(rec, path), ("state", "interface"), path)
        elif name == "routing":
            for vrf, rec in _object(node.get("vrfs", {}), f"{loc}.vrfs").items():
                path = f"{loc}.vrfs.{vrf}"
                rec = _object(rec, path)
                for prefix, route in _object(rec.get("routes", {}), f"{path}.routes").items():
                    route_path = f"{path}.routes.{prefix}"
                    _text_fields(_object(route, route_path), ("protocol",), route_path)
        elif name == "interface":
            for interface, rec in _object(node.get("interfaces", {}), f"{loc}.interfaces").items():
                path = f"{loc}.interfaces.{interface}"
                rec = _object(rec, path)
                _text_fields(rec, ("oper_status",), path)
                for counter in ("in_errors", "crc"):
                    value = rec.get(counter)
                    if value is not None and (type(value) is not int or value < 0):
                        raise ValueError(f"{path}.{counter}: expected a non-negative integer or null")


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
        raise ValueError(f"no snapshot device data in {root}; expected {', '.join(name + '.json' for name in SECTIONS)}")
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
