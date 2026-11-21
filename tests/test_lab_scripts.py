"""The lab-side scripts: the sanitizer that produced the published evidence, and the BGP run.

scripts/lab/sanitize_capture.py is what removed the passwords and certificate bodies from
the captures under fixtures/lab-* before they were committed. The first tests pin its rules on
a synthetic config and check that every published config.json is its own fixed point, so the
evidence in the repository is exactly what those rules leave behind.

scripts/lab/labctl.py reads router show output to know when a change has taken. The rest pin
its parsers on sample output, and the findings the BGP run's planned change was predicted to
produce, on synthetic snapshots shaped like the 2026-09-12 captures. That prediction was
written before the run; the 2026-09-18 run matched it, and tests/test_lab_evidence.py replays
the real captures. The last tests pin what `labctl.py reset` would send, on the published
configs and on one built here; tests/test_labctl_commands.py runs the commands on a fake lab.
"""

from __future__ import annotations

import importlib.util
import json

from ncv.cli import main
from ncv.intent import load_intent


def _load_script(root, name):
    path = root / "scripts" / "lab" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNTHETIC = """hostname R1
enable password 0 lab-enable
enable secret 9 $9$abcdef
username admin privilege 15 password 0 lab-admin
username cisco secret 5 $1$xyz
ip ssh server algorithm authentication password
crypto pki certificate chain TP-self-signed-1
 certificate self-signed 01
  3082 0330 3082 0218
  A003 0201 0202 0101
  \tquit
line con 0
 password lab-console
line vty 0 4
 password 7 0822455D0A16
 login
end
"""

EXPECTED = """hostname R1
enable password 0 <removed>
enable secret 9 <removed>
username admin privilege 15 password 0 <removed>
username cisco secret 5 <removed>
ip ssh server algorithm authentication password
crypto pki certificate chain TP-self-signed-1
 certificate self-signed 01
  <certificate body removed>
  \tquit
line con 0
 password <removed>
line vty 0 4
 password 7 <removed>
 login
end
"""


def test_sanitizer_replaces_passwords_and_certificate_bodies_only(root):
    sanitized, secrets, cert_lines = _load_script(root, "sanitize_capture.py").sanitize(SYNTHETIC)
    assert sanitized == EXPECTED
    assert (secrets, cert_lines) == (6, 2)


def test_published_lab_configs_are_the_sanitizers_fixed_point(root):
    sanitize = _load_script(root, "sanitize_capture.py").sanitize
    configs = sorted((root / "fixtures").glob("lab-*/**/config.json"))
    assert len(configs) == 12
    for path in configs:
        for device, record in json.loads(path.read_text(encoding="utf-8")).items():
            sanitized, secrets, _ = sanitize(record["running"])
            assert sanitized == record["running"], f"{path}:{device} would change"
            assert secrets == 0, f"{path}:{device} still has a password line the rules replace"


OSPF_NEIGHBORS = """\
Neighbor ID     Pri   State           Dead Time   Address         Interface
2.2.2.2           1   FULL/DR         00:00:35    1.1.1.2         Ethernet0/1
3.3.3.3           1   EXSTART/BDR     00:00:31    1.1.1.3         Ethernet0/1
"""

BGP_SUMMARY = """\
BGP router identifier 1.1.1.1, local AS number 65001
Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
1.1.1.2         4        65002      15      15        3    0    0 00:10:12        1
1.1.1.3         4        65003       0       0        1    0    0 never    Idle (Admin)
1.1.1.4         4        65004       0       0        1    0    0 never    Active
"""


def test_labctl_parsers_read_the_show_output(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.ospf_neighbor_state(OSPF_NEIGHBORS, "2.2.2.2") is True
    assert labctl.ospf_neighbor_state(OSPF_NEIGHBORS, "3.3.3.3") is False
    assert labctl.ospf_neighbor_state(OSPF_NEIGHBORS, "4.4.4.4") is None
    assert labctl.bgp_session_state(BGP_SUMMARY, "1.1.1.2") is True
    assert labctl.bgp_session_state(BGP_SUMMARY, "1.1.1.3") is False
    assert labctl.bgp_session_state(BGP_SUMMARY, "1.1.1.4") is False
    assert labctl.bgp_session_state(BGP_SUMMARY, "1.1.1.5") is None


def test_bgp_intent_names_both_peers(root):
    intent = load_intent(root / "fixtures" / "lab-2026-09-18" / "intent-bgp.yaml")
    peers = [(a.device, a.protocol, a.neighbor, a.vrf, a.remote_as) for a in intent.adjacencies]
    assert peers == [("R1", "bgp", "1.1.1.2", "default", 65002), ("R2", "bgp", "1.1.1.1", "default", 65001)]


R1_CONFIG = [
    "hostname R1",
    "router bgp 65001",
    " bgp router-id 1.1.1.1",
    " neighbor 1.1.1.2 remote-as 65002",
    "ip route 20.20.20.0 255.255.255.0 1.1.1.2",
]
R2_CONFIG = [
    "hostname R2",
    "router bgp 65002",
    " bgp router-id 2.2.2.2",
    " neighbor 1.1.1.1 remote-as 65001",
    "ip route 10.10.10.0 255.255.255.0 1.1.1.1",
]


def _write_snapshot(path, states, r1_extra=(), r2_extra=()):
    """A snapshot shaped like the recorded captures, with the BGP states and extra config given."""
    path.mkdir()
    routes = {
        "R1": {"20.20.20.0/24": {"protocol": "static"}, "1.1.1.0/24": {"protocol": "connected"}},
        "R2": {"10.10.10.0/24": {"protocol": "static"}, "1.1.1.0/24": {"protocol": "connected"}},
    }
    peers = {"R1": ("1.1.1.2", 65002), "R2": ("1.1.1.1", 65001)}
    configs = {"R1": R1_CONFIG + list(r1_extra), "R2": R2_CONFIG + list(r2_extra)}
    sections = {
        "ospf.json": {},
        "bgp.json": {
            dev: {"neighbors": {peer: {"state": states[dev], "vrf": "default", "remote_as": asn}}}
            for dev, (peer, asn) in peers.items()
        },
        "routing.json": {dev: {"vrfs": {"default": {"routes": table}}} for dev, table in routes.items()},
        "interface.json": {
            dev: {"interfaces": {"Ethernet0/1": {"oper_status": "up", "in_errors": 0, "crc": 0}}}
            for dev in peers
        },
        "config.json": {dev: {"running": "\n".join(lines) + "\n"} for dev, lines in configs.items()},
    }
    for name, data in sections.items():
        (path / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _bgp_diff(root, tmp_path, before, after, label, intent=None):
    report = tmp_path / f"report-{label}"
    intent = intent or root / "fixtures" / "lab-2026-09-18" / "intent-bgp.yaml"
    code = main(["diff", str(before), str(after), "--intent", str(intent), "--report", str(report)])
    findings = json.loads((report / "report.json").read_text(encoding="utf-8"))["findings"]
    return code, sorted((f["policy_id"], f["device"], f["path"]) for f in findings)


def test_bgp_run_prediction_on_synthetic_snapshots(root, tmp_path):
    pre, post = tmp_path / "pre", tmp_path / "post"
    _write_snapshot(pre, {"R1": "Established", "R2": "Established"})
    _write_snapshot(post, {"R1": "Idle", "R2": "Active"}, r1_extra=[" neighbor 1.1.1.2 shutdown"])
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline") == (0, [])
    assert _bgp_diff(root, tmp_path, pre, post, "change") == (
        1,
        [
            ("V_ADJ", "R1", "bgp.neighbors.1.1.1.2"),
            ("V_ADJ", "R2", "bgp.neighbors.1.1.1.1"),
            ("V_DRIFT", "R1", "config.running.must_absent"),
        ],
    )


# The hold-timer run, prepared before it ran on 2026-11-20: the same eBGP session with a
# 9 s hold time, and an inbound ACL on R1 that drops BGP from R2 as the planned change.

NEIGHBOR_STALE_TIMERS = """\
BGP neighbor is 1.1.1.2,  remote AS 65002, external link
  BGP version 4, remote router ID 2.2.2.2
  BGP state = Established, up for 00:01:12
  Last read 00:00:21, last write 00:00:40, hold time is 180, keepalive interval is 60 seconds
  Configured hold time is 9, keepalive interval is 3 seconds
  Minimum holdtime from neighbor is 0 seconds
"""

NEIGHBOR_FAST_TIMERS = """\
BGP neighbor is 1.1.1.1,  remote AS 65001, external link
  BGP version 4, remote router ID 1.1.1.1
  BGP state = Established, up for 00:00:41
  Last read 00:00:01, last write 00:00:02, hold time is 9, keepalive interval is 3 seconds
  Configured hold time is 9, keepalive interval is 3 seconds
"""


def test_labctl_reads_the_negotiated_timers_not_the_configured_ones(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.bgp_negotiated_timers(NEIGHBOR_FAST_TIMERS) == (9, 3)
    # Timers configured on a session that was already up take effect only at its next start.
    assert labctl.bgp_negotiated_timers(NEIGHBOR_STALE_TIMERS) == (180, 60)
    assert labctl.bgp_negotiated_timers("% No such neighbor or address family") is None


def test_labctl_setup_bgp_lines_are_unchanged_and_fast_adds_only_the_timers(root):
    labctl = _load_script(root, "labctl.py")
    recorded = [  # what setup-bgp sent to R1 for the 2026-09-18 run
        "router bgp 65001",
        "bgp router-id 1.1.1.1",
        "bgp log-neighbor-changes",
        "neighbor 1.1.1.2 remote-as 65002",
        "address-family ipv4",
        "network 10.10.10.0 mask 255.255.255.0",
        "neighbor 1.1.1.2 activate",
        "neighbor 1.1.1.2 soft-reconfiguration inbound",
        "exit-address-family",
    ]
    assert labctl.bgp_setup_lines("R1") == recorded
    fast = labctl.bgp_setup_lines("R2", labctl.FAST_TIMERS)
    assert "neighbor 1.1.1.1 timers 3 9" in fast
    assert fast.index("neighbor 1.1.1.1 timers 3 9") < fast.index("address-family ipv4")
    assert [line for line in fast if "timers" not in line] == labctl.bgp_setup_lines("R2")


def test_labctl_setup_ospf_lines_are_unchanged(root):
    labctl = _load_script(root, "labctl.py")
    area0 = "network 1.1.1.0 0.0.0.255 area 0"
    # what setup-ospf sent for the 2026-09-12 run
    assert labctl.ospf_setup_lines("R1") == ["router ospf 1", "router-id 1.1.1.1", area0]
    assert labctl.ospf_setup_lines("R2") == ["router ospf 1", "router-id 2.2.2.2", area0]


def test_labctl_block_drops_bgp_from_r2_in_both_directions_and_nothing_else(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.bgp_block_lines() == [
        "ip access-list extended NCV-BLOCK-BGP",
        "deny tcp host 1.1.1.2 host 1.1.1.1 eq bgp",
        "deny tcp host 1.1.1.2 eq bgp host 1.1.1.1",
        "permit ip any any",
        "exit",
        "interface Ethernet0/1",
        "ip access-group NCV-BLOCK-BGP in",
    ]
    assert labctl.bgp_unblock_lines() == [
        "interface Ethernet0/1",
        "no ip access-group NCV-BLOCK-BGP in",
        "exit",
        "no ip access-list extended NCV-BLOCK-BGP",
    ]


def test_holdtimer_intent_requires_the_fast_timers_on_both_routers(root):
    intent = load_intent(root / "fixtures" / "lab-2026-11-20" / "intent-bgp-holdtimer.yaml")
    peers = [(a.device, a.protocol, a.neighbor, a.vrf, a.remote_as) for a in intent.adjacencies]
    assert peers == [("R1", "bgp", "1.1.1.2", "default", 65002), ("R2", "bgp", "1.1.1.1", "default", 65001)]
    required = {rule.device: rule.lines for rule in intent.must_include}
    assert "neighbor 1.1.1.2 timers 3 9" in required["R1"]
    assert "neighbor 1.1.1.1 timers 3 9" in required["R2"]


ACL_ON_R1 = [
    "ip access-list extended NCV-BLOCK-BGP",
    " deny   tcp host 1.1.1.2 host 1.1.1.1 eq bgp",
    " deny   tcp host 1.1.1.2 eq bgp host 1.1.1.1",
    " permit ip any any",
    "interface Ethernet0/1",
    " ip access-group NCV-BLOCK-BGP in",
]


def test_holdtimer_run_prediction_on_synthetic_snapshots(root, tmp_path):
    """Both adjacencies fail and nothing else does: no rule names the ACL, and the routes,
    interface counters, and required lines do not move."""
    intent = root / "fixtures" / "lab-2026-11-20" / "intent-bgp-holdtimer.yaml"
    r1_timers, r2_timers = [" neighbor 1.1.1.2 timers 3 9"], [" neighbor 1.1.1.1 timers 3 9"]
    pre, post = tmp_path / "pre", tmp_path / "post"
    _write_snapshot(pre, {"R1": "Established", "R2": "Established"}, r1_timers, r2_timers)
    _write_snapshot(post, {"R1": "Active", "R2": "Active"}, r1_timers + ACL_ON_R1, r2_timers)
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (0, [])
    assert _bgp_diff(root, tmp_path, pre, post, "change", intent) == (
        1,
        [("V_ADJ", "R1", "bgp.neighbors.1.1.1.2"), ("V_ADJ", "R2", "bgp.neighbors.1.1.1.1")],
    )


def test_holdtimer_intent_refuses_a_session_without_the_fast_timers(root, tmp_path):
    """The no-change check is what proves the timers are configured before the change."""
    intent = root / "fixtures" / "lab-2026-11-20" / "intent-bgp-holdtimer.yaml"
    pre = tmp_path / "pre"
    _write_snapshot(pre, {"R1": "Established", "R2": "Established"})
    code, findings = _bgp_diff(root, tmp_path, pre, pre, "baseline", intent)
    assert code == 1
    assert findings == [
        ("V_DRIFT", "R1", "config.running.must_include"),
        ("V_DRIFT", "R2", "config.running.must_include"),
    ]


# labctl.py reset: what it would send to undo the lab scripts' work, read from a running config.


def _running(root, path, device):
    configs = json.loads((root / "fixtures" / path / "config.json").read_text(encoding="utf-8"))
    return configs[device]["running"]


def test_reset_needs_nothing_on_the_shipped_configuration(root):
    labctl = _load_script(root, "labctl.py")
    for device in ("R1", "R2"):
        assert labctl.reset_lines(_running(root, "lab-2026-09-12/routes/pre", device)) == []


# Everything the planned runs may add, in the order IOS lists it, around what the sandbox ships.
EVERYTHING_ON_R1 = """hostname R1
!
vrf definition Mgmt-intf
 !
 address-family ipv4
 exit-address-family
!
vrf definition NCV
 rd 65001:1
 !
 address-family ipv4
 exit-address-family
!
interface Loopback0
 ip address 1.1.1.11 255.255.255.255
!
interface Loopback100
 ip address 100.100.100.1 255.255.255.255
!
interface Ethernet0/0
 ip address 10.10.10.100 255.255.255.0
!
interface Ethernet0/1
 ip address 1.1.1.1 255.255.255.0
 ip access-group NCV-TEST in
 ip ospf hello-interval 1
!
interface Ethernet0/1.100
 encapsulation dot1Q 100
 vrf forwarding NCV
 ip address 100.1.1.1 255.255.255.0
!
interface Ethernet0/2
 description to port1.sandbox-backend
 vrf forwarding Mgmt-intf
 ip address 10.10.20.171 255.255.255.0
!
interface Ethernet0/3
 ip address 3.3.3.1 255.255.255.0
!
router ospf 1
 router-id 1.1.1.1
 network 1.1.1.0 0.0.0.255 area 0
!
router bgp 65001
 bgp router-id 1.1.1.1
 neighbor 1.1.1.2 remote-as 65002
!
ip route 20.20.20.0 255.255.255.0 1.1.1.2
ip route vrf Mgmt-intf 0.0.0.0 0.0.0.0 10.10.20.254
!
ip access-list extended NCV-TEST
 10 permit ip any any
!
line vty 0 4
 login local
end
"""


def test_reset_undoes_everything_the_scripts_add_unbinding_before_deleting(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.reset_lines(EVERYTHING_ON_R1) == [
        "interface Ethernet0/1",
        "no ip access-group NCV-TEST in",
        "no ip access-list extended NCV-TEST",
        "no router bgp 65001",
        "no router ospf 1",
        "interface Ethernet0/1",
        "no ip ospf hello-interval",
        "no interface Loopback0",
        "no interface Loopback100",
        "no interface Ethernet0/1.100",
        "default interface Ethernet0/3",
        "interface Ethernet0/3",
        "shutdown",
        "no vrf definition NCV",
    ]


def test_reset_after_the_holdtimer_run_removes_the_acl_and_bgp_only(root):
    labctl = _load_script(root, "labctl.py")
    post = "lab-2026-11-20/bgp-holdtimer/post"
    assert labctl.reset_lines(_running(root, post, "R1")) == [
        "interface Ethernet0/1",
        "no ip access-group NCV-BLOCK-BGP in",
        "no ip access-list extended NCV-BLOCK-BGP",
        "no router bgp 65001",
    ]
    assert labctl.reset_lines(_running(root, post, "R2")) == ["no router bgp 65002"]


def test_reset_brings_a_shut_link_back(root):
    labctl = _load_script(root, "labctl.py")
    r1 = _running(root, "lab-2026-09-12/routes/post", "R1")
    assert labctl.reset_lines(r1) == ["interface Ethernet0/1", "no shutdown"]


def test_reset_never_touches_the_management_path_or_the_static_routes(root):
    labctl = _load_script(root, "labctl.py")
    configs = [EVERYTHING_ON_R1]
    for path in sorted((root / "fixtures").glob("lab-*/**/config.json")):
        configs += [record["running"] for record in json.loads(path.read_text(encoding="utf-8")).values()]
    assert len(configs) == 25
    for config in configs:
        for line in labctl.reset_lines(config):
            assert "Mgmt-intf" not in line
            assert "Ethernet0/0" not in line
            assert "Ethernet0/2" not in line
            assert "ip route" not in line


def test_reset_leaves_what_the_scripts_did_not_add(root):
    """Only NCV- ACLs, OSPF process 1, and the named interfaces are the scripts' own, and the
    spare port in either order is still what ships."""
    labctl = _load_script(root, "labctl.py")
    config = "\n".join(
        [
            "interface Ethernet0/1",
            " ip address 1.1.1.1 255.255.255.0",
            " ip access-group OPERATOR in",
            "interface Ethernet0/3",
            " shutdown",
            " no ip address",
            "router ospf 2",
            "ip access-list extended OPERATOR",
            " permit ip any any",
            "vrf definition NCV-OTHER",
        ]
    )
    assert labctl.reset_lines(config) == []
