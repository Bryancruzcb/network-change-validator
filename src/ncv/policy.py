from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .intent import Intent


@dataclass(frozen=True)
class Finding:
    policy_id: str
    device: str
    path: str
    before: Any
    after: Any
    why: str
    action: str


FULL_STATES = {"up", "full", "FULL", "UP"}


def evaluate(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_devices(intent, pre, post))
    findings.extend(_adjacencies(intent, pre, post))
    findings.extend(_routes(intent, pre, post))
    findings.extend(_errors(intent, post))
    findings.extend(_drift(intent, pre, post))
    return findings


def _devices(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    present_pre = _device_set(pre)
    present_post = _device_set(post)
    for dev in intent.devices:
        if dev not in present_post:
            out.append(
                Finding(
                    policy_id="V_DRIFT",
                    device=dev,
                    path="devices",
                    before=dev in present_pre,
                    after=False,
                    why="intent device missing from post snapshot",
                    action="confirm the device is in the testbed and reachable in lab",
                )
            )
    return out


def _device_set(snap: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for section in snap.values():
        if isinstance(section, dict):
            names.update(section.keys())
    return names


def _nbr_state(snap: dict[str, Any], device: str, neighbor: str) -> str | None:
    node = (snap.get("ospf") or {}).get(device) or {}
    nbrs = node.get("neighbors") or {}
    rec = nbrs.get(neighbor)
    if rec is None:
        return None
    return str(rec.get("state", ""))


def _adjacencies(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for adj in intent.adjacencies:
        before = _nbr_state(pre, adj.device, adj.neighbor)
        after = _nbr_state(post, adj.device, adj.neighbor)
        ok = after is not None and after.lower() in {s.lower() for s in FULL_STATES}
        if ok:
            continue
        out.append(
            Finding(
                policy_id="V_ADJ",
                device=adj.device,
                path=f"ospf.neighbors.{adj.neighbor}.state",
                before=before,
                after=after,
                why=(
                    f"required {adj.protocol} neighbor {adj.neighbor} "
                    f"on {adj.interface} is not FULL in post snapshot"
                ),
                action="in lab, restore the peer-facing interface / neighbor config and re-learn",
            )
        )
    return out


def _route_rec(snap: dict[str, Any], device: str, vrf: str, prefix: str) -> dict[str, Any] | None:
    node = (snap.get("routing") or {}).get(device) or {}
    vrfs = node.get("vrfs") or {}
    routes = (vrfs.get(vrf) or {}).get("routes") or {}
    rec = routes.get(prefix)
    return rec if isinstance(rec, dict) else None


def _routes(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for rt in intent.routes:
        before = _route_rec(pre, rt.device, rt.vrf, rt.prefix)
        after = _route_rec(post, rt.device, rt.vrf, rt.prefix)
        if after is None:
            out.append(
                Finding(
                    policy_id="V_ROUTE",
                    device=rt.device,
                    path=f"routing.vrfs.{rt.vrf}.routes.{rt.prefix}",
                    before=None if before is None else before.get("protocol"),
                    after=None,
                    why=f"required prefix {rt.prefix} missing from {rt.device} vrf {rt.vrf}",
                    action="in lab, restore the originating advertisement and re-learn routing",
                )
            )
            continue
        if rt.protocol and str(after.get("protocol", "")).lower() != rt.protocol.lower():
            out.append(
                Finding(
                    policy_id="V_ROUTE",
                    device=rt.device,
                    path=f"routing.vrfs.{rt.vrf}.routes.{rt.prefix}.protocol",
                    before=None if before is None else before.get("protocol"),
                    after=after.get("protocol"),
                    why=f"prefix {rt.prefix} present but protocol is {after.get('protocol')}, intent {rt.protocol}",
                    action="check redistribution / protocol source in lab only",
                )
            )
    return out


def _iface(snap: dict[str, Any], device: str, name: str) -> dict[str, Any]:
    node = (snap.get("interface") or {}).get(device) or {}
    ifaces = node.get("interfaces") or {}
    rec = ifaces.get(name)
    return rec if isinstance(rec, dict) else {}


def _errors(intent: Intent, post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for lim in intent.interfaces:
        rec = _iface(post, lim.device, lim.name)
        in_err = int(rec.get("in_errors", 0) or 0)
        crc = int(rec.get("crc", 0) or 0)
        if in_err > lim.max_in_errors or crc > lim.max_crc:
            out.append(
                Finding(
                    policy_id="V_ERR",
                    device=lim.device,
                    path=f"interface.{lim.name}.counters",
                    before=None,
                    after={"in_errors": in_err, "crc": crc},
                    why=(
                        f"{lim.name} errors in_errors={in_err} (max {lim.max_in_errors}), "
                        f"crc={crc} (max {lim.max_crc})"
                    ),
                    action="inspect cabling / SFP in lab; do not clear counters on production",
                )
            )
    return out


def _running(snap: dict[str, Any], device: str) -> str:
    node = (snap.get("config") or {}).get(device) or {}
    return str(node.get("running", ""))


def _drift(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for rule in intent.must_include:
        text = _running(post, rule.device)
        for line in rule.lines:
            if line not in text:
                out.append(
                    Finding(
                        policy_id="V_DRIFT",
                        device=rule.device,
                        path="config.running.must_include",
                        before=line in _running(pre, rule.device),
                        after=False,
                        why=f"required line missing: {line}",
                        action="restore the intended line in lab running-config",
                    )
                )
    for rule in intent.must_absent:
        text = _running(post, rule.device)
        for line in rule.lines:
            if line in text:
                out.append(
                    Finding(
                        policy_id="V_DRIFT",
                        device=rule.device,
                        path="config.running.must_absent",
                        before=line in _running(pre, rule.device),
                        after=True,
                        why=f"forbidden line present: {line}",
                        action="remove the leftover line in lab; do not touch production",
                    )
                )
    return out


def findings_to_dicts(findings: list[Finding]) -> list[dict[str, Any]]:
    return [asdict(f) for f in findings]
