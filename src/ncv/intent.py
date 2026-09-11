from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Adjacency:
    device: str
    protocol: str
    neighbor: str
    interface: str


@dataclass(frozen=True)
class Route:
    device: str
    vrf: str
    prefix: str
    protocol: str


@dataclass(frozen=True)
class InterfaceLimit:
    device: str
    name: str
    max_in_errors: int
    max_crc: int


@dataclass(frozen=True)
class ConfigRule:
    device: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Intent:
    intent_id: str
    version: int
    devices: tuple[str, ...]
    adjacencies: tuple[Adjacency, ...] = field(default_factory=tuple)
    routes: tuple[Route, ...] = field(default_factory=tuple)
    interfaces: tuple[InterfaceLimit, ...] = field(default_factory=tuple)
    must_include: tuple[ConfigRule, ...] = field(default_factory=tuple)
    must_absent: tuple[ConfigRule, ...] = field(default_factory=tuple)
    exclude_volatile: tuple[str, ...] = field(default_factory=tuple)


def _rules(raw: Any) -> tuple[ConfigRule, ...]:
    if not raw:
        return ()
    out = []
    for item in raw:
        lines = tuple(str(x) for x in item.get("lines") or [])
        out.append(ConfigRule(device=str(item["device"]), lines=lines))
    return tuple(out)


def load_intent(path: str | Path) -> Intent:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"intent must be a mapping: {path}")
    cfg = data.get("config") or {}
    return Intent(
        intent_id=str(data["intent_id"]),
        version=int(data.get("version", 1)),
        devices=tuple(str(d) for d in data.get("devices") or []),
        adjacencies=tuple(
            Adjacency(
                device=str(a["device"]),
                protocol=str(a.get("protocol", "ospf")),
                neighbor=str(a["neighbor"]),
                interface=str(a.get("interface", "")),
            )
            for a in data.get("adjacencies") or []
        ),
        routes=tuple(
            Route(
                device=str(r["device"]),
                vrf=str(r.get("vrf", "default")),
                prefix=str(r["prefix"]),
                protocol=str(r.get("protocol", "")),
            )
            for r in data.get("routes") or []
        ),
        interfaces=tuple(
            InterfaceLimit(
                device=str(i["device"]),
                name=str(i["name"]),
                max_in_errors=int(i.get("max_in_errors", 0)),
                max_crc=int(i.get("max_crc", 0)),
            )
            for i in data.get("interfaces") or []
        ),
        must_include=_rules(cfg.get("must_include")),
        must_absent=_rules(cfg.get("must_absent")),
        exclude_volatile=tuple(str(x) for x in data.get("exclude_volatile") or []),
    )
