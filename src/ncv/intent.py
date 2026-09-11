from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_network
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


def _mapping(raw: Any, where: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected a mapping")
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown field(s): {', '.join(sorted(map(str, unknown)))}")
    return raw


def _list(raw: Any, where: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ValueError(f"{where}: expected a list")
    return raw


def _text(raw: Any, where: str, *, empty: bool = False) -> str:
    if not isinstance(raw, str) or (not empty and not raw.strip()):
        raise ValueError(f"{where}: expected a {'possibly empty ' if empty else 'non-empty '}string")
    return raw.strip()


def _integer(raw: Any, where: str) -> int:
    if type(raw) is not int or raw < 0:
        raise ValueError(f"{where}: expected a non-negative integer")
    return raw


def _device(raw: Any, where: str, devices: tuple[str, ...]) -> str:
    device = _text(raw, where)
    if device not in devices:
        raise ValueError(f"{where}: {device!r} is not declared in devices")
    return device


def _rules(raw: Any, where: str, devices: tuple[str, ...]) -> tuple[ConfigRule, ...]:
    out = []
    for index, item in enumerate(_list(raw, where)):
        loc = f"{where}[{index}]"
        item = _mapping(item, loc, {"device", "lines"})
        lines = tuple(
            _text(line, f"{loc}.lines[{i}]")
            for i, line in enumerate(_list(item.get("lines"), f"{loc}.lines"))
        )
        if not lines or any("\n" in line or "\r" in line for line in lines):
            raise ValueError(f"{loc}.lines: expected at least one single config line")
        out.append(ConfigRule(_device(item.get("device"), f"{loc}.device", devices), lines))
    return tuple(out)


def load_intent(path: str | Path) -> Intent:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    where = str(path)
    data = _mapping(
        data,
        where,
        {
            "intent_id",
            "version",
            "devices",
            "adjacencies",
            "routes",
            "interfaces",
            "config",
            "exclude_volatile",
        },
    )
    version = _integer(data.get("version", 1), f"{where}.version")
    if version != 1:
        raise ValueError(f"{where}.version: only version 1 is supported")
    devices = tuple(
        _text(d, f"{where}.devices[{i}]")
        for i, d in enumerate(_list(data.get("devices"), f"{where}.devices"))
    )
    if not devices or len(set(devices)) != len(devices):
        raise ValueError(f"{where}.devices: expected a non-empty list of unique device names")
    adjacencies = []
    for i, a in enumerate(_list(data.get("adjacencies", []), f"{where}.adjacencies")):
        loc = f"{where}.adjacencies[{i}]"
        a = _mapping(a, loc, {"device", "protocol", "neighbor", "interface"})
        protocol = _text(a.get("protocol", "ospf"), f"{loc}.protocol").lower()
        if protocol != "ospf":
            raise ValueError(f"{loc}.protocol: only ospf adjacencies are supported")
        adjacencies.append(
            Adjacency(
                _device(a.get("device"), f"{loc}.device", devices),
                protocol,
                _text(a.get("neighbor"), f"{loc}.neighbor"),
                _text(a.get("interface", ""), f"{loc}.interface", empty=True),
            )
        )
    routes = []
    for i, r in enumerate(_list(data.get("routes", []), f"{where}.routes")):
        loc = f"{where}.routes[{i}]"
        r = _mapping(r, loc, {"device", "vrf", "prefix", "protocol"})
        prefix = _text(r.get("prefix"), f"{loc}.prefix")
        try:
            prefix = str(ip_network(prefix))
        except ValueError as exc:
            raise ValueError(f"{loc}.prefix: invalid network prefix {prefix!r}") from exc
        routes.append(
            Route(
                _device(r.get("device"), f"{loc}.device", devices),
                _text(r.get("vrf", "default"), f"{loc}.vrf"),
                prefix,
                _text(r.get("protocol", ""), f"{loc}.protocol", empty=True).lower(),
            )
        )
    interfaces = []
    for i, item in enumerate(_list(data.get("interfaces", []), f"{where}.interfaces")):
        loc = f"{where}.interfaces[{i}]"
        item = _mapping(item, loc, {"device", "name", "max_in_errors", "max_crc"})
        interfaces.append(
            InterfaceLimit(
                _device(item.get("device"), f"{loc}.device", devices),
                _text(item.get("name"), f"{loc}.name"),
                _integer(item.get("max_in_errors", 0), f"{loc}.max_in_errors"),
                _integer(item.get("max_crc", 0), f"{loc}.max_crc"),
            )
        )
    cfg = _mapping(data.get("config", {}), f"{where}.config", {"must_include", "must_absent"})
    return Intent(
        intent_id=_text(data.get("intent_id"), f"{where}.intent_id"),
        version=version,
        devices=devices,
        adjacencies=tuple(adjacencies),
        routes=tuple(routes),
        interfaces=tuple(interfaces),
        must_include=_rules(cfg.get("must_include", []), f"{where}.config.must_include", devices),
        must_absent=_rules(cfg.get("must_absent", []), f"{where}.config.must_absent", devices),
        exclude_volatile=tuple(
            _text(x, f"{where}.exclude_volatile[{i}]")
            for i, x in enumerate(_list(data.get("exclude_volatile", []), f"{where}.exclude_volatile"))
        ),
    )
