from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .intent import Adjacency, Intent


@dataclass(frozen=True)
class Finding:
    policy_id: str
    device: str
    path: str
    before: Any
    after: Any
    why: str
    action: str


def evaluate(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_devices(intent, pre, post))
    findings.extend(_adjacencies(intent, pre, post))
    findings.extend(_routes(intent, pre, post))
    findings.extend(_errors(intent, pre, post))
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


def _neighbor(snap: dict[str, Any], protocol: str, device: str, neighbor: str) -> dict[str, Any] | None:
    return (snap.get(protocol, {}).get(device, {}).get("neighbors", {})).get(neighbor)


def _ospf_compliant(adj: Adjacency, after: dict[str, Any] | None) -> bool:
    record = after or {}
    state = str(record.get("state", "")).lower().split("/")[0].strip()
    return state == "full" and (not adj.interface or record.get("interface") == adj.interface)


def _bgp_compliant(adj: Adjacency, after: dict[str, Any] | None) -> bool:
    record = after or {}
    if str(record.get("state", "")).strip().lower() != "established":
        return False
    if adj.vrf and record.get("vrf") != adj.vrf:
        return False
    return adj.remote_as is None or record.get("remote_as") == adj.remote_as


def _adjacencies(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for adj in intent.adjacencies:
        before = _neighbor(pre, adj.protocol, adj.device, adj.neighbor)
        after = _neighbor(post, adj.protocol, adj.device, adj.neighbor)
        if adj.protocol == "ospf":
            if _ospf_compliant(adj, after):
                continue
            why = f"required OSPF neighbor {adj.neighbor} must be FULL" + (
                f" on {adj.interface}" if adj.interface else ""
            )
            action = "inspect peer state and interface configuration in the lab"
        else:
            if _bgp_compliant(adj, after):
                continue
            why = (
                f"required BGP neighbor {adj.neighbor} must be Established"
                + (f" in vrf {adj.vrf}" if adj.vrf else "")
                + (f" with remote AS {adj.remote_as}" if adj.remote_as is not None else "")
            )
            action = "inspect the peer session, its vrf, and its remote AS in the lab"
        out.append(
            Finding(
                policy_id="V_ADJ",
                device=adj.device,
                path=f"{adj.protocol}.neighbors.{adj.neighbor}",
                before=before,
                after=after,
                why=why,
                action=action,
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
                    why=f"prefix {rt.prefix} present but protocol is "
                    f"{after.get('protocol')}, intent {rt.protocol}",
                    action="check redistribution / protocol source in lab only",
                )
            )
    return out


def _iface(snap: dict[str, Any], device: str, name: str) -> dict[str, Any]:
    node = (snap.get("interface") or {}).get(device) or {}
    ifaces = node.get("interfaces") or {}
    rec = ifaces.get(name)
    return rec if isinstance(rec, dict) else {}


def _errors(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for lim in intent.interfaces:
        rec = _iface(post, lim.device, lim.name)
        before = {key: _iface(pre, lim.device, lim.name).get(key) for key in ("in_errors", "crc")}
        after = {key: rec.get(key) for key in ("in_errors", "crc")}
        missing = any(value is None for value in after.values())
        if missing or after["in_errors"] > lim.max_in_errors or after["crc"] > lim.max_crc:
            out.append(
                Finding(
                    policy_id="V_ERR",
                    device=lim.device,
                    path=f"interface.{lim.name}.counters",
                    before=before,
                    after=after,
                    why=(
                        f"{lim.name}: required counter evidence missing"
                        if missing
                        else f"{lim.name} errors in_errors={after['in_errors']} (max {lim.max_in_errors}), "
                        f"crc={after['crc']} (max {lim.max_crc})"
                    ),
                    action="inspect interface counters and cabling in the lab",
                )
            )
    return out


def _config_lines(snap: dict[str, Any], device: str) -> set[str] | None:
    running = snap.get("config", {}).get(device, {}).get("running")
    return {line.strip() for line in running.splitlines()} if isinstance(running, str) else None


def _drift(intent: Intent, pre: dict[str, Any], post: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    missing_devices: set[str] = set()
    # Split each device's running-config once per snapshot and reuse it across every
    # rule group in this evaluation. The caches are local, so a later evaluation of the
    # same snapshots re-reads them rather than trusting stale evidence.
    pre_lines: dict[str, set[str] | None] = {}
    post_lines: dict[str, set[str] | None] = {}

    def lines(snap: dict[str, Any], cache: dict[str, set[str] | None], device: str) -> set[str] | None:
        if device not in cache:
            cache[device] = _config_lines(snap, device)
        return cache[device]

    for kind, rules in (("must_include", intent.must_include), ("must_absent", intent.must_absent)):
        for rule in rules:
            before = lines(pre, pre_lines, rule.device)
            after = lines(post, post_lines, rule.device)
            if after is None:
                if rule.device not in missing_devices:
                    out.append(
                        Finding(
                            "V_DRIFT",
                            rule.device,
                            "config.running",
                            before is not None,
                            None,
                            "running-config evidence missing; config rules cannot be checked",
                            "capture running-config from the lab device and retry",
                        )
                    )
                    missing_devices.add(rule.device)
                continue
            for line in rule.lines:
                present = line in after
                if present == (kind == "must_include"):
                    continue
                out.append(
                    Finding(
                        "V_DRIFT",
                        rule.device,
                        f"config.running.{kind}",
                        None if before is None else line in before,
                        present,
                        f"required line missing: {line}"
                        if kind == "must_include"
                        else f"forbidden line present: {line}",
                        "review the intended configuration in the lab",
                    )
                )
    return out


def findings_to_dicts(findings: list[Finding]) -> list[dict[str, Any]]:
    return [asdict(f) for f in findings]
