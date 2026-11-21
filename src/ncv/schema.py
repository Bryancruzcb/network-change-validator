from __future__ import annotations

from typing import Any

SECTIONS = ("ospf", "bgp", "routing", "interface", "config")
LEARNED_FEATURES = tuple(name for name in SECTIONS if name != "config")


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected a JSON object")
    return value


def _text_fields(record: dict[str, Any], fields: tuple[str, ...], where: str) -> None:
    for key in fields:
        if record.get(key) is not None and not isinstance(record[key], str):
            raise ValueError(f"{where}.{key}: expected a string or null")


def _bgp_records(neighbors: Any, where: str, keyed_by_vrf: bool) -> None:
    """Check one map of BGP peer records; both stored shapes share it, only the vrf field differs."""
    for neighbor, rec in _object(neighbors, where).items():
        path = f"{where}.{neighbor}"
        rec = _object(rec, path)
        if keyed_by_vrf and "vrf" in rec:
            # Policy reads the VRF from the key, so a field here would be silently ignored even
            # when it names another VRF.
            raise ValueError(f"{path}.vrf: the vrf is the key, not a field")
        _text_fields(rec, ("state",) if keyed_by_vrf else ("state", "vrf"), path)
        remote_as = rec.get("remote_as")
        if remote_as is not None and (type(remote_as) is not int or remote_as < 0):
            raise ValueError(f"{path}.remote_as: expected a non-negative integer or null")


def _bgp_node(node: dict[str, Any], loc: str) -> None:
    # New captures key peers by VRF, so one address can sit in two VRFs. Older snapshots keep
    # one flat record per address with the VRF inside it; they still load. A node holding both
    # would leave a peer's VRF ambiguous, so it is refused.
    if "neighbors" in node and "vrfs" in node:
        raise ValueError(f"{loc}: has both neighbors and vrfs")
    if "vrfs" in node:
        for vrf, rec in _object(node["vrfs"], f"{loc}.vrfs").items():
            path = f"{loc}.vrfs.{vrf}"
            _bgp_records(_object(rec, path).get("neighbors", {}), f"{path}.neighbors", True)
    else:
        _bgp_records(node.get("neighbors", {}), f"{loc}.neighbors", False)


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
        elif name == "bgp":
            _bgp_node(node, loc)
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
