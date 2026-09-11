from __future__ import annotations

from typing import Any

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
