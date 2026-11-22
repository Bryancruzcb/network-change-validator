"""The live lab captures, sanitized, replayed offline.

fixtures/lab-2026-09-12, fixtures/lab-2026-09-18, fixtures/lab-2026-11-20, and
fixtures/lab-2026-11-21 hold real captures from a Cisco DevNet CML sandbox (see each
SOURCE.md), and some runs also hold a capture of the R1-R2 link. These tests pin what those
runs showed, so an adapter or policy change that would have missed the real change fails
here first. They also pin each 2026-11-21 run's findings to the prediction file written
before it, and each link summary to the capture it was read from.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys

import pytest
from test_lab_scripts import _load_script

from ncv.cli import main


def _diff(root, tmp_path, run, before, after, intent, lab="lab-2026-09-12"):
    lab = root / "fixtures" / lab
    report = tmp_path / f"{run}-{before}-{after}"
    code = main(
        [
            "diff",
            str(lab / run / before),
            str(lab / run / after),
            "--intent",
            str(lab / intent),
            "--report",
            str(report),
        ]
    )
    findings = json.loads((report / "report.json").read_text(encoding="utf-8"))["findings"]
    return code, sorted((f["policy_id"], f["device"], f["path"]) for f in findings)


def test_route_run_catches_the_shut_link(root, tmp_path):
    code, findings = _diff(root, tmp_path, "routes", "pre", "post", "intent-routes.yaml")
    assert code == 1
    assert findings == [
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.1.1.1.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.20.20.20.0/24"),
    ]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_route_run_is_clean_without_the_change(root, tmp_path, after):
    code, findings = _diff(root, tmp_path, "routes", "pre", after, "intent-routes.yaml")
    assert code == 0
    assert findings == []


def test_ospf_run_catches_both_lost_adjacencies_and_routes(root, tmp_path):
    code, findings = _diff(root, tmp_path, "ospf", "pre", "post", "intent-ospf.yaml")
    assert code == 1
    assert findings == [
        ("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"),
        ("V_ADJ", "R2", "ospf.neighbors.1.1.1.1"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.1.1.1.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.20.20.20.0/24"),
    ]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_ospf_run_is_clean_without_the_change(root, tmp_path, after):
    code, findings = _diff(root, tmp_path, "ospf", "pre", after, "intent-ospf.yaml")
    assert code == 0
    assert findings == []


def test_bgp_run_catches_both_lost_sessions_and_the_shutdown_line(root, tmp_path):
    code, findings = _diff(root, tmp_path, "bgp", "pre", "post", "intent-bgp.yaml", lab="lab-2026-09-18")
    assert code == 1
    assert findings == [
        ("V_ADJ", "R1", "bgp.neighbors.1.1.1.2"),
        ("V_ADJ", "R2", "bgp.neighbors.1.1.1.1"),
        ("V_DRIFT", "R1", "config.running.must_absent"),
    ]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_bgp_run_is_clean_without_the_change(root, tmp_path, after):
    code, findings = _diff(root, tmp_path, "bgp", "pre", after, "intent-bgp.yaml", lab="lab-2026-09-18")
    assert code == 0
    assert findings == []


HOLDTIMER = {"run": "bgp-holdtimer", "intent": "intent-bgp-holdtimer.yaml", "lab": "lab-2026-11-20"}


def test_holdtimer_run_catches_both_lost_sessions_and_nothing_else(root, tmp_path):
    """No rule names the ACL that caused it, so only the adjacency rules fire."""
    h = HOLDTIMER
    code, findings = _diff(root, tmp_path, h["run"], "pre", "post", h["intent"], lab=h["lab"])
    assert code == 1
    assert findings == [("V_ADJ", "R1", "bgp.neighbors.1.1.1.2"), ("V_ADJ", "R2", "bgp.neighbors.1.1.1.1")]


@pytest.mark.parametrize("after", ["pre", "restored"])
def test_holdtimer_run_is_clean_without_the_change(root, tmp_path, after):
    h = HOLDTIMER
    code, findings = _diff(root, tmp_path, h["run"], "pre", after, h["intent"], lab=h["lab"])
    assert code == 0
    assert findings == []


def test_holdtimer_post_capture_holds_the_acl_and_idle_sessions(root):
    """The change is in the captured config, and both sessions were captured Idle."""
    post = root / "fixtures" / "lab-2026-11-20" / "bgp-holdtimer" / "post"
    running = json.loads((post / "config.json").read_text(encoding="utf-8"))["R1"]["running"]
    assert " ip access-group NCV-BLOCK-BGP in" in running.splitlines()
    bgp = json.loads((post / "bgp.json").read_text(encoding="utf-8"))
    assert {dev: next(iter(rec["neighbors"].values()))["state"] for dev, rec in bgp.items()} == {
        "R1": "Idle",
        "R2": "Idle",
    }


def _bgp_pcap(root, monkeypatch):
    path = root / "scripts" / "lab" / "bgp_pcap.py"
    spec = importlib.util.spec_from_file_location("bgp_pcap", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bgp_pcap", module)  # dataclasses looks the module up
    spec.loader.exec_module(module)
    return module


def test_holdtimer_pcap_shows_r1s_hold_timer_expiring(root, monkeypatch):
    """The second 2026-11-20 run captured the R1-R2 link: R1, which stopped hearing R2, sent
    NOTIFICATION 4/0 (and retransmitted it, since R2's ACKs were dropped too); R2 sent none;
    the reconnect after the ACL came off opened with a 9 s hold time on both sides."""
    pcap_dir = root / "fixtures" / "lab-2026-11-20" / "bgp-holdtimer-pcap"
    lines = _bgp_pcap(root, monkeypatch).summarize((pcap_dir / "link.pcap").read_bytes())
    assert lines == (pcap_dir / "summary.txt").read_text(encoding="utf-8").splitlines()
    notifications = [line for line in lines if "NOTIFICATION" in line]
    assert len(notifications) == 2
    assert all("1.1.1.1:179 -> 1.1.1.2:" in line for line in notifications)
    assert all(line.endswith("NOTIFICATION 4/0 Hold Timer Expired") for line in notifications)
    assert not any("Cease" in line for line in lines)
    opens = sorted(line.split("  OPEN ")[-1] for line in lines if "  OPEN " in line)
    assert opens == ["AS 65001 hold 9 id 1.1.1.1", "AS 65002 hold 9 id 2.2.2.2"]


LAB_1121 = "lab-2026-11-21"

# What each 2026-11-21 change comparison (pre vs post) gave, sorted as _diff sorts them. Each run
# keeps its intent and its prediction beside its evidence, as intent-<run>.yaml and expect-<run>.txt.
RUNS_1121 = {
    "ospf-deadtimer": [
        ("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"),
        ("V_ADJ", "R2", "ospf.neighbors.1.1.1.1"),
    ],
    "ibgp": [
        ("V_ADJ", "R1", "bgp.vrfs.default.neighbors.10.255.255.2"),
        ("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"),
        ("V_ADJ", "R2", "bgp.vrfs.default.neighbors.10.255.255.1"),
        ("V_ADJ", "R2", "ospf.neighbors.1.1.1.1"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.10.255.255.2/32"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.172.16.2.0/24"),
        ("V_ROUTE", "R2", "routing.vrfs.default.routes.10.255.255.1/32"),
        ("V_ROUTE", "R2", "routing.vrfs.default.routes.172.16.1.0/24"),
    ],
    "bgp-vrf": [
        ("V_ADJ", "R1", "bgp.vrfs.NCV.neighbors.1.1.1.2"),
        ("V_ADJ", "R2", "bgp.vrfs.NCV.neighbors.1.1.1.1"),
        ("V_ROUTE", "R1", "routing.vrfs.NCV.routes.1.1.1.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.NCV.routes.172.16.102.0/24"),
        ("V_ROUTE", "R2", "routing.vrfs.NCV.routes.172.16.101.0/24"),
    ],
    "second-platform-iosv": [
        ("V_ADJ", "R1", "bgp.vrfs.default.neighbors.10.1.3.3"),
        ("V_ADJ", "R1", "ospf.neighbors.3.3.3.3"),
        ("V_ADJ", "R3", "bgp.vrfs.default.neighbors.10.1.3.1"),
        ("V_ADJ", "R3", "ospf.neighbors.1.1.1.1"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.10.1.3.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.172.16.3.0/24"),
        ("V_ROUTE", "R1", "routing.vrfs.default.routes.3.3.3.3/32"),
        ("V_ROUTE", "R3", "routing.vrfs.default.routes.1.1.1.0/24"),
        ("V_ROUTE", "R3", "routing.vrfs.default.routes.10.10.10.0/24"),
    ],
}
SECTIONS = ["SOURCE.json", "bgp.json", "config.json", "interface.json", "ospf.json", "routing.json"]


@pytest.mark.parametrize("run", RUNS_1121)
def test_each_2026_11_21_run_catches_exactly_its_recorded_findings(root, tmp_path, run):
    code, findings = _diff(root, tmp_path, run, "pre", "post", f"intent-{run}.yaml", lab=LAB_1121)
    assert code == 1
    assert findings == RUNS_1121[run]


@pytest.mark.parametrize("after", ["pre", "restored"])
@pytest.mark.parametrize("run", RUNS_1121)
def test_each_2026_11_21_run_is_clean_without_the_change(root, tmp_path, run, after):
    """pre vs pre is the no-change check: the pre capture compared with itself, so 0 findings
    shows that capture met every rule. pre vs restored shows the restored capture met them too."""
    code, findings = _diff(root, tmp_path, run, "pre", after, f"intent-{run}.yaml", lab=LAB_1121)
    assert code == 0
    assert findings == []


@pytest.mark.parametrize("run", RUNS_1121)
def test_each_2026_11_21_runs_findings_are_the_ones_its_expect_file_predicted(root, run):
    """The expect file was written and merged before the run. The recorded findings above must be
    exactly its findings, so the prediction and the evidence cannot drift apart."""
    check = _load_script(root, "check_findings.py")
    path = root / "fixtures" / LAB_1121 / f"expect-{run}.txt"
    predicted = check.parse_expected(path.read_text(encoding="utf-8"), path.name)
    assert len(set(RUNS_1121[run])) == len(RUNS_1121[run])
    assert predicted == frozenset(RUNS_1121[run])


def _capture(root, run, capture, section):
    path = root / "fixtures" / LAB_1121 / run / capture / f"{section}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _running(root, run, capture, device="R1"):
    return _capture(root, run, capture, "config")[device]["running"].splitlines()


def _block(lines, header):
    """One config block: its header line up to the next '!' line."""
    start = lines.index(header)
    return lines[start : lines.index("!", start)]


def _routes(routing):
    return {
        (dev, vrf, prefix): route["protocol"]
        for dev, rec in routing.items()
        for vrf, table in rec["vrfs"].items()
        for prefix, route in table["routes"].items()
    }


def _lost_routes(root, run):
    """Routes in pre that are gone from post, with their pre protocol; post gained or changed none."""
    pre, post = (_routes(_capture(root, run, capture, "routing")) for capture in ("pre", "post"))
    assert post.items() <= pre.items()
    return {key: protocol for key, protocol in pre.items() if key not in post}


def _oper_status(root, run, capture, interface):
    interfaces = _capture(root, run, capture, "interface")
    return {
        dev: rec["interfaces"][interface]["oper_status"]
        for dev, rec in interfaces.items()
        if interface in rec["interfaces"]
    }


BLOCK_OSPF_ACL = [
    "ip access-list extended NCV-BLOCK-OSPF",
    " 10 deny ospf host 1.1.1.2 any",
    " 20 permit ip any any",
]


def _holds_the_ospf_acl(root, run):
    pre, post = _running(root, run, "pre"), _running(root, run, "post")
    assert " ip access-group NCV-BLOCK-OSPF in" in _block(post, "interface Ethernet0/1")
    start = post.index(BLOCK_OSPF_ACL[0])
    assert post[start : start + 3] == BLOCK_OSPF_ACL
    assert not any("NCV-BLOCK-OSPF" in line for line in pre)


def test_ospf_deadtimer_post_capture_holds_the_acl_and_the_one_sided_adjacency(root):
    """R1's post config binds NCV-BLOCK-OSPF inbound on Ethernet0/1, and pre has no such ACL. In
    post R1 lists no OSPF neighbor while R2 still holds 1.1.1.1, in init. Ethernet0/1 stayed up on
    both routers, and no route changed, which is why there is no route finding."""
    run = "ospf-deadtimer"
    _holds_the_ospf_acl(root, run)
    assert _capture(root, run, "post", "ospf") == {
        "R1": {"neighbors": {}},
        "R2": {"neighbors": {"1.1.1.1": {"state": "init", "interface": "Ethernet0/1"}}},
    }
    assert _oper_status(root, run, "post", "Ethernet0/1") == {"R1": "up", "R2": "up"}
    assert _lost_routes(root, run) == {}


def test_ibgp_post_capture_holds_idle_sessions_and_the_missing_loopback_routes(root):
    """The same ACL as the dead-timer run, the same one-sided OSPF state, both iBGP sessions captured
    Idle, and each router missing the peer's Loopback0 /32 (learned by OSPF in pre) and Loopback1
    /24 (learned by BGP in pre). Nothing else in the routing tables changed."""
    run = "ibgp"
    _holds_the_ospf_acl(root, run)
    assert _capture(root, run, "post", "ospf") == {
        "R1": {"neighbors": {}},
        "R2": {"neighbors": {"1.1.1.1": {"state": "init", "interface": "Ethernet0/1"}}},
    }
    assert _capture(root, run, "post", "bgp") == {
        "R1": {"vrfs": {"default": {"neighbors": {"10.255.255.2": {"state": "Idle", "remote_as": 65010}}}}},
        "R2": {"vrfs": {"default": {"neighbors": {"10.255.255.1": {"state": "Idle", "remote_as": 65010}}}}},
    }
    assert _lost_routes(root, run) == {
        ("R1", "default", "10.255.255.2/32"): "ospf",
        ("R1", "default", "172.16.2.0/24"): "bgp",
        ("R2", "default", "10.255.255.1/32"): "ospf",
        ("R2", "default", "172.16.1.0/24"): "bgp",
    }


def test_bgp_vrf_post_capture_holds_the_vrf_session_down_and_the_global_one_up(root):
    """BGP is keyed by VRF in a real capture: each router has a vrf NCV and a default neighbor at
    the same address. In post the NCV neighbor is Idle on R1 and Active on R2, the default
    neighbor is still Established on both, R1's Ethernet0/1.100 is shut and down while R2's is
    up, and only vrf NCV routes are missing."""
    run = "bgp-vrf"
    pre = _capture(root, run, "pre", "bgp")
    assert {dev: sorted(rec["vrfs"]) for dev, rec in pre.items()} == {
        "R1": ["NCV", "default"],
        "R2": ["NCV", "default"],
    }
    assert {
        (dev, vrf): neighbor["state"]
        for dev, rec in pre.items()
        for vrf, table in rec["vrfs"].items()
        for neighbor in table["neighbors"].values()
    } == dict.fromkeys([("R1", "NCV"), ("R1", "default"), ("R2", "NCV"), ("R2", "default")], "Established")
    assert _capture(root, run, "post", "bgp") == {
        "R1": {
            "vrfs": {
                "NCV": {"neighbors": {"1.1.1.2": {"state": "Idle", "remote_as": 65002}}},
                "default": {"neighbors": {"1.1.1.2": {"state": "Established", "remote_as": 65002}}},
            }
        },
        "R2": {
            "vrfs": {
                "NCV": {"neighbors": {"1.1.1.1": {"state": "Active", "remote_as": 65001}}},
                "default": {"neighbors": {"1.1.1.1": {"state": "Established", "remote_as": 65001}}},
            }
        },
    }
    assert " shutdown" in _block(_running(root, run, "post"), "interface Ethernet0/1.100")
    assert " shutdown" not in _block(_running(root, run, "pre"), "interface Ethernet0/1.100")
    assert _oper_status(root, run, "pre", "Ethernet0/1.100") == {"R1": "up", "R2": "up"}
    assert _oper_status(root, run, "post", "Ethernet0/1.100") == {"R1": "down", "R2": "up"}
    assert _oper_status(root, run, "post", "Ethernet0/1") == {"R1": "up", "R2": "up"}
    assert _lost_routes(root, run) == {
        ("R1", "NCV", "1.1.1.0/24"): "connected",
        ("R1", "NCV", "1.1.1.1/32"): "local",
        ("R1", "NCV", "172.16.102.0/24"): "bgp",
        ("R2", "NCV", "172.16.101.0/24"): "bgp",
    }


def test_second_platform_post_capture_holds_r3_and_the_shut_link(root):
    """R3, the IOSv router, is in every section file of every capture, and its config records
    'version 15.9' where R1's records 'version 17.15'. In post R1's Ethernet0/3 is shut and down,
    but R3's GigabitEthernet0/0 stayed up and R3 kept its connected 10.1.3.0/24: that is why there
    are nine findings and not ten. R2 kept its own OSPF and BGP neighbors but lost three routes it
    had learned through R1, with no finding, because the intent does not list R2."""
    run = "second-platform-iosv"
    for capture in ("pre", "post", "restored"):
        assert _capture(root, run, capture, "SOURCE")["devices"] == ["R1", "R2", "R3"]
        for section in ("ospf", "bgp", "routing", "interface", "config"):
            assert sorted(_capture(root, run, capture, section)) == ["R1", "R2", "R3"], (capture, section)
    assert "version 15.9" in _running(root, run, "post", "R3")
    assert "version 17.15" in _running(root, run, "post", "R1")
    assert " shutdown" in _block(_running(root, run, "post"), "interface Ethernet0/3")
    assert " shutdown" not in _block(_running(root, run, "pre"), "interface Ethernet0/3")
    assert _oper_status(root, run, "pre", "Ethernet0/3")["R1"] == "up"
    assert _oper_status(root, run, "post", "Ethernet0/3")["R1"] == "down"
    assert _oper_status(root, run, "post", "GigabitEthernet0/0")["R3"] == "up"
    routing = _capture(root, run, "post", "routing")
    assert routing["R3"]["vrfs"]["default"]["routes"]["10.1.3.0/24"] == {"protocol": "connected"}
    for section in ("ospf", "bgp"):
        assert _capture(root, run, "post", section)["R2"] == _capture(root, run, "pre", section)["R2"]
    lost = _lost_routes(root, run)
    assert {key: protocol for key, protocol in lost.items() if key[0] == "R2"} == {
        ("R2", "default", "10.1.3.0/24"): "ospf",
        ("R2", "default", "3.3.3.3/32"): "ospf",
        ("R2", "default", "172.16.3.0/24"): "bgp",
    }


def _config_body(running):
    """Config text without the two header lines IOS rewrites on every change, and without blank lines."""
    volatile = ("Current configuration : ", "! Last configuration change at ")
    return [line for line in running.splitlines() if line.strip() and not line.startswith(volatile)]


@pytest.mark.parametrize("run", RUNS_1121)
def test_each_2026_11_21_restored_capture_equals_pre_outside_the_config_text(root, run):
    """Every normalized section file of restored equals pre's, except config.json. The config text
    differs only in the 'Current configuration' and 'Last configuration change' lines and in blank
    lines. This is not a claim that the lab came back identical: ncv compares no OSPF DR/BDR role
    or TCP port, and the link captures show both changed (see the pcap tests below)."""
    lab = root / "fixtures" / LAB_1121 / run
    for capture in ("pre", "restored"):
        assert sorted(path.name for path in (lab / capture).iterdir()) == SECTIONS
    for name in SECTIONS:
        if name != "config.json":
            pre, restored = (
                json.loads((lab / c / name).read_text(encoding="utf-8")) for c in ("pre", "restored")
            )
            assert restored == pre, name
    pre, restored = (_capture(root, run, c, "config") for c in ("pre", "restored"))
    assert restored != pre
    assert {dev: _config_body(rec["running"]) for dev, rec in restored.items()} == {
        dev: _config_body(rec["running"]) for dev, rec in pre.items()
    }


def _link_pcap(root, monkeypatch):
    path = root / "scripts" / "lab" / "link_pcap.py"
    # the script puts its own directory on sys.path to import bgp_pcap; keep that to this test
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("link_pcap", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "link_pcap", module)
    spec.loader.exec_module(module)
    return module


PCAP_RUNS_1121 = ["ospf-deadtimer", "ibgp", "bgp-vrf"]


def _pcap_dir(root, run):
    return root / "fixtures" / LAB_1121 / f"{run}-pcap"


def _summary(root, run):
    return (_pcap_dir(root, run) / "summary.txt").read_text(encoding="utf-8").splitlines()


def _at(line):
    """The time of a summary line, in seconds from the capture's first packet."""
    return float(line.split()[0])


@pytest.mark.parametrize("run", PCAP_RUNS_1121)
def test_each_2026_11_21_link_summary_is_what_link_pcap_reads_from_the_capture(root, monkeypatch, run):
    """summary.txt is link_pcap.py's output as the run wrote it. The decoder must still read the
    capture the same way, line for line, or the facts pinned below would describe a stale text."""
    lines = _link_pcap(root, monkeypatch).summarize((_pcap_dir(root, run) / "link.pcap").read_bytes())
    assert lines == _summary(root, run)


def test_ospf_deadtimer_pcap_shows_r1s_hellos_drop_r2_while_r2s_still_list_r1(root):
    """On the wire: every Hello carries hello 1 and dead 4. R1's Hellos list 2.2.2.2 up to 9.206 s,
    list no neighbor from 10.134 s to 112.223 s, and list 2.2.2.2 again after that. Every Hello R2
    sends, before, during and after, lists 1.1.1.1. No other OSPF packet appears until 112.237 s,
    and from then on the DR and BDR are swapped (R2 DR, R1 BDR; the capture began with R1 DR).
    Inferred, not on the wire: R1 stopped accepting R2's Hellos (the ACL) and dropped R2 when its
    dead interval ran out. The capture is taken outside both routers and cannot show what R1
    accepted."""
    lines = _summary(root, "ospf-deadtimer")
    hellos = [line for line in lines if "OSPF Hello " in line]
    assert hellos and all(" hello 1 dead 4 " in line for line in hellos)
    r1 = [line for line in hellos if " rid 1.1.1.1 " in line]
    r2 = [line for line in hellos if " rid 2.2.2.2 " in line]
    assert len(r1) + len(r2) == len(hellos)
    assert all(line.endswith(" neighbors 1.1.1.1") for line in r2)
    empty = [_at(line) for line in r1 if line.endswith(" neighbors none")]
    assert (empty[0], empty[-1]) == (10.134, 112.223)
    assert [line for line in r1 if empty[0] <= _at(line) <= empty[-1]] == [
        line for line in r1 if line.endswith(" neighbors none")
    ]
    assert all(line.endswith(" neighbors 2.2.2.2") for line in r1 if not empty[0] <= _at(line) <= empty[-1])
    assert max(_at(line) for line in r1 if _at(line) < empty[0]) == 9.206
    assert min(_at(line) for line in lines if "OSPF" in line and "OSPF Hello " not in line) == 112.237
    assert " dr 1.1.1.1 bdr 1.1.1.2 " in hellos[0]
    assert all(" dr 1.1.1.2 bdr 1.1.1.1 " in line for line in hellos if _at(line) > 113)


def test_ibgp_pcap_shows_no_notification_during_the_outage_and_a_late_one_on_the_old_connection(root):
    """On the wire: the iBGP session runs on 10.255.255.1:64623 to 10.255.255.2:179, and its last
    segment before the gap is at 10.111 s. No port-179 segment of any kind follows until 160.533 s,
    so no NOTIFICATION was on the link during the outage, against the written packet prediction.
    Then R1 opens a new connection from port 65081, and both OPENs carry hold 9. The capture's one
    NOTIFICATION comes at 172.029 s, after those OPENs: 4/0 Hold Timer Expired from 10.255.255.2,
    on the old connection, and 10.255.255.1 answers it with a reset. Inferred, not on the wire:
    those bytes had waited in R2 since the outage. Nothing on the link shows how R1's side of the
    old session ended."""
    lines = _summary(root, "ibgp")
    bgp = [line for line in lines if ":179 " in line]
    resumed = next(n for n, line in enumerate(bgp) if _at(line) > 10.111)
    assert _at(bgp[resumed - 1]) == 10.111
    assert all("10.255.255.1:64623 " in line and "10.255.255.2:179 " in line for line in bgp[:resumed])
    assert not any("NOTIFICATION" in line for line in bgp[:resumed])
    assert _at(bgp[resumed]) == 160.533
    assert bgp[resumed].split()[1:] == ["10.255.255.1:65081", "->", "10.255.255.2:179", "[SYN]"]
    opens = [line for line in bgp if "  OPEN " in line]
    assert [line.split("  OPEN ")[-1] for line in opens] == [
        "AS 65010 hold 9 id 1.1.1.1",
        "AS 65010 hold 9 id 2.2.2.2",
    ]
    assert all("10.255.255.1:65081" in line for line in opens)
    notifications = [n for n, line in enumerate(lines) if "NOTIFICATION" in line]
    assert len(notifications) == 1
    late = lines[notifications[0]]
    assert _at(late) == 172.029 > max(_at(line) for line in opens)
    assert "10.255.255.2:179 -> 10.255.255.1:64623 " in late
    assert late.endswith("NOTIFICATION 4/0 Hold Timer Expired")
    assert lines[notifications[0] + 1].split()[1:] == [
        "10.255.255.1:64623",
        "->",
        "10.255.255.2:179",
        "[RST]",
    ]


def test_bgp_vrf_pcap_shows_r2s_notification_on_vlan_100_while_the_untagged_session_runs_on(
    root, monkeypatch
):
    """On the wire: the vrf NCV session rides 802.1Q VLAN 100 and the default-VRF session is
    untagged, between the same two addresses. R1 sends nothing on VLAN 100 from 3.709 s until it
    opens a new connection at 117.336 s, and both new VLAN-100 OPENs carry hold 9. R2 sends
    NOTIFICATION 4/0 Hold Timer Expired on VLAN 100 at 13.312 s. The summary shows a second
    NOTIFICATION line at 21.189 s, but that segment starts at the TCP sequence number of R2's
    unanswered keepalive at 6.144 s and ends with the 13.312 s NOTIFICATION's bytes: it is a
    retransmission the decoder does not mark, because it was repacketized. R2 sent one
    NOTIFICATION. Through the whole capture the untagged session carries only keepalives and
    ACKs, never more than 3.1 s apart either way. Inferred, not on the wire: R1 ended the VRF
    session when its subinterface went down; the capture cannot show what R1 never sent."""
    lines = _summary(root, "bgp-vrf")
    tagged = [line for line in lines if line.split()[1:3] == ["vlan", "100"]]
    untagged = [line for line in lines if "vlan" not in line]
    assert len(tagged) + len(untagged) == len(lines)
    notifications = [line for line in lines if "NOTIFICATION" in line]
    assert [_at(line) for line in notifications] == [13.312, 21.189]
    assert all(line in tagged and "  1.1.1.2:179 -> 1.1.1.1:41395  " in line for line in notifications)
    assert all(line.endswith("NOTIFICATION 4/0 Hold Timer Expired") for line in notifications)
    assert all(line.endswith(("[PSH,ACK]  KEEPALIVE", "[ACK]")) for line in untagged)
    for source in ("1.1.1.1:12085", "1.1.1.2:179"):
        keepalives = [
            _at(line) for line in untagged if line.split()[1] == source and line.endswith("KEEPALIVE")
        ]
        assert keepalives[0] < 3.709 and keepalives[-1] > 117.336
        assert max(b - a for a, b in itertools.pairwise(keepalives)) < 3.1
    r1_tagged = [_at(line) for line in tagged if line.split()[3].startswith("1.1.1.1:")]
    assert 3.709 in r1_tagged and 117.336 in r1_tagged
    assert not [t for t in r1_tagged if 3.709 < t < 117.336]
    opens = [line for line in tagged if "  OPEN " in line]
    assert [line.split("  OPEN ")[-1] for line in opens] == [
        "AS 65001 hold 9 id 1.1.1.1",
        "AS 65002 hold 9 id 2.2.2.2",
    ]
    assert all("1.1.1.1:62426" in line for line in opens)

    bgp_pcap = _link_pcap(root, monkeypatch).bgp_pcap
    frames = bgp_pcap.pcap_frames((_pcap_dir(root, "bgp-vrf") / "link.pcap").read_bytes())
    start = frames[0][0]
    r2_data = [
        segment
        for segment in (bgp_pcap.tcp_segment(time, frame) for time, frame in frames)
        if segment
        and segment.vlan == 100
        and segment.src == "1.1.1.2"
        and segment.dport == 41395
        and segment.payload
    ]

    def sent_at(when):
        (segment,) = [s for s in r2_data if abs(s.time - start - when) < 0.0005]
        return segment

    keepalive, notification, again = sent_at(6.144), sent_at(13.312), sent_at(21.189)
    assert again.seq == keepalive.seq
    assert again.payload.endswith(notification.payload)
    assert notification.seq == again.seq + len(again.payload) - len(notification.payload)


NUMBERS = {"Two": 2, "Three": 3, "Four": 4, "Five": 5, "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9}


def test_the_readme_counts_the_live_runs_its_table_lists(root):
    """The live-lab section opens with how many runs there were, above a table with one row per
    run; a new run adds a row, and the count in the sentence has to follow it."""
    readme = (root / "README.md").read_text(encoding="utf-8")
    section = readme[readme.index("### Live lab") :]
    count = re.match(r"### Live lab[^\n]*\n\n(\w+) runs,", section)
    assert count, "the live-lab section no longer opens with its run count"
    table = section[section.index("| Date | Change |") :].split("\n\n")[0]
    rows = [line for line in table.splitlines() if re.match(r"\| \d{4}-\d{2}-\d{2} ", line)]
    assert NUMBERS[count.group(1)] == len(rows)
