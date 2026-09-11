from __future__ import annotations

from typing import Any


def normalize_learn(device: str, feature: str, blob: Any) -> dict[str, Any]:
    data = _to_dict(blob)
    if feature == "ospf":
        return {device: {"neighbors": _ospf_neighbors(data)}}
    if feature == "routing":
        return {device: {"vrfs": _vrfs(data)}}
    if feature == "interface":
        return {device: {"interfaces": _ifaces(data)}}
    if feature == "config":
        return {device: {"running": _running(data)}}
    return {device: data}


def merge_section(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    out = dict(dst)
    for dev, payload in src.items():
        if dev not in out:
            out[dev] = payload
        elif isinstance(out[dev], dict) and isinstance(payload, dict):
            merged = dict(out[dev])
            merged.update(payload)
            out[dev] = merged
        else:
            out[dev] = payload
    return out


def _to_dict(blob: Any) -> dict[str, Any]:
    if blob is None:
        return {}
    if isinstance(blob, dict):
        return blob
    for attr in ("info", "to_dict"):
        val = getattr(blob, attr, None)
        if callable(val):
            got = val()
            if isinstance(got, dict):
                return got
        elif isinstance(val, dict):
            return val
    return {}


def _ospf_neighbors(data: dict[str, Any]) -> dict[str, Any]:
    if "neighbors" in data and isinstance(data["neighbors"], dict):
        return data["neighbors"]
    found: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        nbrs = node.get("neighbors")
        if isinstance(nbrs, dict):
            for key, rec in nbrs.items():
                if not isinstance(rec, dict):
                    continue
                state = rec.get("state") or rec.get("neighbor_state") or rec.get("adj_state")
                iface = rec.get("interface") or rec.get("address") or ""
                if state:
                    found[str(key)] = {"state": str(state), "interface": str(iface)}
        for val in node.values():
            walk(val)

    walk(data)
    return found


def _vrfs(data: dict[str, Any]) -> dict[str, Any]:
    if "vrfs" in data and isinstance(data["vrfs"], dict):
        return data["vrfs"]
    vrfs = (data.get("info") or {}).get("vrf") if isinstance(data.get("info"), dict) else data.get("vrf")
    if not isinstance(vrfs, dict):
        vrfs = {"default": data}
    out: dict[str, Any] = {}
    for vrf_name, vrf in vrfs.items():
        if not isinstance(vrf, dict):
            continue
        routes = vrf.get("routes") or vrf.get("address_family") or {}
        flat: dict[str, Any] = {}
        _collect_routes(routes, flat)
        out[str(vrf_name)] = {"routes": flat}
    return out


def _collect_routes(node: Any, out: dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    for key, rec in node.items():
        if isinstance(rec, dict) and (
            "route" in rec or "next_hop" in rec or "next_hops" in rec or "source_protocol" in rec or "active" in rec
        ):
            proto = rec.get("protocol") or rec.get("source_protocol") or rec.get("route_preference") or ""
            out[str(key)] = {"protocol": str(proto)}
        else:
            _collect_routes(rec, out)


def _ifaces(data: dict[str, Any]) -> dict[str, Any]:
    if "interfaces" in data and isinstance(data["interfaces"], dict):
        inner = data["interfaces"]
        sample = next(iter(inner.values()), None)
        if isinstance(sample, dict) and ("in_errors" in sample or "oper_status" in sample):
            return inner
    src = data.get("interfaces") or data.get("info") or data
    if not isinstance(src, dict):
        return {}
    out: dict[str, Any] = {}
    for name, rec in src.items():
        if not isinstance(rec, dict):
            continue
        counters = rec.get("counters") if isinstance(rec.get("counters"), dict) else rec
        out[str(name)] = {
            "oper_status": str(rec.get("oper_status") or rec.get("enabled") or ""),
            "in_errors": int(counters.get("in_errors") or counters.get("in_error") or 0),
            "crc": int(counters.get("in_crc_errors") or counters.get("crc") or 0),
        }
    return out


def _running(data: dict[str, Any]) -> str:
    if isinstance(data.get("running"), str):
        return data["running"]
    cfg = data.get("config") or data.get("running_config") or data.get("text") or ""
    if isinstance(cfg, str):
        return cfg
    return ""
