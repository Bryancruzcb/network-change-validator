from __future__ import annotations

from ipaddress import ip_network
from typing import Any

from .snapshot import validate_section


def normalize_learn(device: str, feature: str, blob: Any) -> dict[str, Any]:
    """Adapt a small set of Genie shapes; reject unsupported or ambiguous data."""
    data = _to_dict(blob)
    if isinstance(data.get("info"), dict):
        data = data["info"]
    if feature == "ospf":
        payload = {"neighbors": _ospf_neighbors(data)}
    elif feature == "routing":
        payload = {"vrfs": _vrfs(data)}
    elif feature == "interface":
        payload = {"interfaces": _ifaces(data)}
    else:
        raise ValueError(f"unsupported learned feature: {feature}")
    result = {device: payload}
    validate_section(feature, result, f"{device}.{feature}")
    return result


def _to_dict(blob: Any) -> dict[str, Any]:
    if isinstance(blob, dict):
        return blob
    info = getattr(blob, "info", None)
    if isinstance(info, dict):
        return info
    method = getattr(blob, "to_dict", None)
    if callable(method):
        result = method()
        if isinstance(result, dict):
            return result
    raise ValueError("learn returned no supported mapping")


def _ospf_neighbors(data: dict[str, Any]) -> dict[str, Any]:
    if not any(key in data for key in ("neighbors", "vrf")):
        raise ValueError("unsupported OSPF data: expected neighbors or vrf")
    found: dict[str, Any] = {}

    def walk(node: Any, interface: str | None = None) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "neighbors":
                if not isinstance(value, dict):
                    raise ValueError("OSPF neighbors must be a mapping")
                for neighbor, rec in value.items():
                    if not isinstance(rec, dict):
                        raise ValueError(f"invalid OSPF neighbor {neighbor}")
                    normalized = {
                        "state": rec.get("state", rec.get("neighbor_state", rec.get("adj_state"))),
                        "interface": rec.get("interface", interface),
                    }
                    if str(neighbor) in found:
                        raise ValueError(f"ambiguous OSPF neighbor {neighbor}: multiple interfaces/VRFs")
                    found[str(neighbor)] = normalized
            elif key in ("interfaces", "interface") and isinstance(value, dict):
                for name, record in value.items():
                    walk(record, str(name))
            else:
                walk(value, interface)

    walk(data)
    return found


def _vrfs(data: dict[str, Any]) -> dict[str, Any]:
    if "vrfs" in data:
        return data["vrfs"]
    vrfs = data.get("vrf")
    if not isinstance(vrfs, dict):
        raise ValueError("unsupported routing data: expected vrf or vrfs")
    out = {}
    for name, rec in vrfs.items():
        if not isinstance(rec, dict):
            raise ValueError(f"invalid routing VRF {name}")
        routes: dict[str, Any] = {}
        _collect_routes(rec, routes)
        out[str(name)] = {"routes": routes}
    return out


def _collect_routes(node: Any, out: dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    for key, rec in node.items():
        if key == "routes":
            if not isinstance(rec, dict):
                raise ValueError("routing routes must be a mapping")
            for prefix, route in rec.items():
                if not isinstance(route, dict):
                    raise ValueError(f"invalid route {prefix}")
                prefix = str(ip_network(prefix))
                if prefix in out:
                    raise ValueError(f"ambiguous duplicate route {prefix}")
                out[prefix] = {"protocol": route.get("protocol", route.get("source_protocol"))}
        else:
            _collect_routes(rec, out)


def _counter(record: dict[str, Any], *names: str) -> int | None:
    for name in names:
        if name in record:
            value = record[name]
            if isinstance(value, str) and value.isdecimal():
                return int(value)
            return value  # Schema validation rejects malformed values; unknown stays None.
    return None


def _ifaces(data: dict[str, Any]) -> dict[str, Any]:
    src = data.get("interfaces")
    if not isinstance(src, dict):
        raise ValueError("unsupported interface data: expected interfaces")
    out = {}
    for name, rec in src.items():
        if not isinstance(rec, dict):
            raise ValueError(f"invalid interface {name}")
        counters = rec.get("counters", rec)
        if not isinstance(counters, dict):
            raise ValueError(f"invalid counters for interface {name}")
        out[str(name)] = {
            "oper_status": rec.get("oper_status"),
            "in_errors": _counter(counters, "in_errors", "in_error"),
            "crc": _counter(counters, "crc", "in_crc_errors"),
        }
    return out
