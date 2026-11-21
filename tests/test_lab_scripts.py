"""The lab-side scripts: the sanitizer that produced the published evidence, and the BGP run.

scripts/lab/sanitize_capture.py is what removed the passwords and certificate bodies from
the captures under fixtures/lab-* before they were committed. The first tests pin its rules on
a synthetic config and check that every published config.json is its own fixed point, so the
evidence in the repository is exactly what those rules leave behind, then which stage
directories of a run it copies and that it refuses a run before creating anything.

scripts/lab/labctl.py reads router show output to know when a change has taken. The rest pin
its parsers on sample output, and the findings the BGP run's planned change was predicted to
produce, on synthetic snapshots shaped like the 2026-09-12 captures. That prediction was
written before the run; the 2026-09-18 run matched it, and tests/test_lab_evidence.py replays
the real captures. The OSPF dead-timer run, the iBGP run, and the BGP VRF run are prepared the
same way and have not run: their predictions are pinned here on synthetic snapshots built
through ncv's own adapter from Genie-shaped data, and the predicted change findings are read
from the scripts/lab/expect-<run>.txt file each run script checks its report against. The last
tests pin what `labctl.py reset` would send, on the published configs and on ones built here;
tests/test_labctl_commands.py runs the commands on a fake lab. Then come the SSH testbed
example, the read-only probe, and the order of the prepared SSH path run. The next ones
are the prepared second-platform run: R1's side of the R3 link, the three per-platform draft
intents, the prediction on synthetic snapshots whose R3 records are shaped as each platform's
Genie data writes them, the R3 testbed example, and the run script's order. After them, the
session script: every name it knows names a script that exists, and every prepared run is one
of its names, so a new run cannot be forgotten; and every script here has a row in the README.
The last ones hold the README to the code: the runs it says can capture over SSH, each prepared
run's prediction table against its expected file, and each configuration block against the
builder that sends it.
"""

from __future__ import annotations

import importlib.util
import json
import re

import pytest
import yaml

from ncv.cli import main
from ncv.intent import load_intent
from ncv.normalize import normalize_learn


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


# NX-OS's documented forms of the two lines an R3 capture will carry that hold the admin
# password or keys derived from it. Invented values; no NX-OS capture exists yet.
NXOS_SYNTHETIC = """hostname R3
username admin password 5 $5$KFLMEN$Lw3x7b3/2EHQ1qs8yaBLnT  role network-admin
snmp-server user admin network-admin auth md5 0x3f0a5e7c1b2d4f60 priv 0x3f0a5e7c1b2d4f60 localizedkey
snmp-server user ops auth sha 0x11aa22bb priv aes-128 0x33cc44dd localizedkey
feature bgp
"""
NXOS_EXPECTED = """hostname R3
username admin password 5 <removed>
snmp-server user admin network-admin auth <removed>
snmp-server user ops auth <removed>
feature bgp
"""


def test_sanitizer_replaces_the_nxos_admin_hash_and_the_snmp_keys_derived_from_it(root):
    sanitized, secrets, cert_lines = _load_script(root, "sanitize_capture.py").sanitize(NXOS_SYNTHETIC)
    assert sanitized == NXOS_EXPECTED
    assert (secrets, cert_lines) == (3, 0)


def _capture(run, stages):
    """A run directory as a capture leaves it: each stage with the six section files, its
    running configs holding SYNTHETIC, and a raw/ the sanitizer leaves behind."""
    sections = ("SOURCE.json", "bgp.json", "interface.json", "ospf.json", "routing.json")
    for stage in stages:
        (run / stage / "raw").mkdir(parents=True)
        (run / stage / "raw" / "R1_config.txt").write_text(SYNTHETIC, encoding="utf-8")
        for name in sections:
            (run / stage / name).write_text(json.dumps({"stage": stage}), encoding="utf-8")
        config = {name: {"running": SYNTHETIC} for name in ("R1", "R2")}
        (run / stage / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return run


@pytest.mark.parametrize(
    "stages",
    [("pre", "post", "restored"), ("console", "ssh")],
    ids=["change run", "ssh-path run"],
)
def test_sanitizer_copies_each_stage_directory_the_run_holds(root, tmp_path, capsys, stages):
    sanitizer = _load_script(root, "sanitize_capture.py")
    run = _capture(tmp_path / "run", stages)
    (run / "notes").mkdir()  # no config.json: not a stage
    dst = tmp_path / "published"
    assert sanitizer.main(["sanitize_capture.py", str(run), str(dst)]) == 0
    assert sorted(child.name for child in dst.iterdir()) == sorted(stages)
    for stage in stages:
        assert sorted(child.name for child in (dst / stage).iterdir()) == sorted(sanitizer.SECTIONS)
        config = json.loads((dst / stage / "config.json").read_text(encoding="utf-8"))
        assert config == {name: {"running": EXPECTED} for name in ("R1", "R2")}
        assert (dst / stage / "ospf.json").read_bytes() == (run / stage / "ospf.json").read_bytes()
    # A change run reports in run order, as it always did.
    assert capsys.readouterr().out.splitlines() == [
        f"{stage}/{name}: 6 password lines replaced, 2 certificate lines removed"
        for stage in stages
        for name in ("R1", "R2")
    ]


def test_sanitizer_exits_2_with_the_usage_when_the_run_holds_no_stage(root, tmp_path, capsys):
    sanitizer = _load_script(root, "sanitize_capture.py")
    empty = tmp_path / "run"
    (empty / "raw").mkdir(parents=True)
    for source in (empty, tmp_path / "absent"):
        assert sanitizer.main(["sanitize_capture.py", str(source), str(tmp_path / "published")]) == 2
        assert capsys.readouterr().out == sanitizer.USAGE + "\n"
    assert not (tmp_path / "published").exists()
    assert "console/ ssh/" in sanitizer.USAGE


def test_sanitizer_refuses_before_creating_anything(root, tmp_path, capsys):
    sanitizer = _load_script(root, "sanitize_capture.py")
    run = _capture(tmp_path / "run", ("pre", "post", "restored"))
    (run / "restored" / "bgp.json").unlink()  # a later stage short of a file
    dst = tmp_path / "published"
    assert sanitizer.main(["sanitize_capture.py", str(run), str(dst)]) == 2
    assert capsys.readouterr().out == f"sanitize_capture.py: {run / 'restored' / 'bgp.json'} is missing\n"
    assert not dst.exists()
    (run / "restored" / "bgp.json").write_text("{}", encoding="utf-8")
    (dst / "post").mkdir(parents=True)  # a stage published before
    assert sanitizer.main(["sanitize_capture.py", str(run), str(dst)]) == 2
    assert capsys.readouterr().out == f"sanitize_capture.py: {dst / 'post'} already exists\n"
    assert [child.name for child in dst.iterdir()] == ["post"]


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


LAB_ROUTES = {
    "R1": {"20.20.20.0/24": {"protocol": "static"}, "1.1.1.0/24": {"protocol": "connected"}},
    "R2": {"10.10.10.0/24": {"protocol": "static"}, "1.1.1.0/24": {"protocol": "connected"}},
}


def _write_lab_snapshot(path, ospf, bgp, configs, routes=None, other_vrfs=None):
    """A snapshot shaped like the recorded captures: the OSPF and BGP sections and the config
    lines given, around the link counters every lab run keeps unchanged and the routes given,
    by default the static and connected ones every earlier run kept unchanged. `routes` is the
    default VRF's table per router; `other_vrfs` adds {vrf: table} per router beside it."""
    path.mkdir()
    routes = LAB_ROUTES if routes is None else routes
    other_vrfs = other_vrfs or {}
    sections = {
        "ospf.json": ospf,
        "bgp.json": bgp,
        "routing.json": {
            dev: {
                "vrfs": {
                    "default": {"routes": table},
                    **{vrf: {"routes": rest} for vrf, rest in other_vrfs.get(dev, {}).items()},
                }
            }
            for dev, table in routes.items()
        },
        "interface.json": {
            dev: {"interfaces": {"Ethernet0/1": {"oper_status": "up", "in_errors": 0, "crc": 0}}}
            for dev in routes
        },
        "config.json": {dev: {"running": "\n".join(lines) + "\n"} for dev, lines in configs.items()},
    }
    for name, data in sections.items():
        (path / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_snapshot(path, states, r1_extra=(), r2_extra=()):
    """A snapshot shaped like the recorded captures, with the BGP states and extra config given."""
    peers = {"R1": ("1.1.1.2", 65002), "R2": ("1.1.1.1", 65001)}
    bgp = {
        dev: {"neighbors": {peer: {"state": states[dev], "vrf": "default", "remote_as": asn}}}
        for dev, (peer, asn) in peers.items()
    }
    configs = {"R1": R1_CONFIG + list(r1_extra), "R2": R2_CONFIG + list(r2_extra)}
    _write_lab_snapshot(path, {}, bgp, configs)


R1_OSPF_CONFIG = [
    "hostname R1",
    "router ospf 1",
    " router-id 1.1.1.1",
    " network 1.1.1.0 0.0.0.255 area 0",
    "ip route 20.20.20.0 255.255.255.0 1.1.1.2",
]
R2_OSPF_CONFIG = [
    "hostname R2",
    "router ospf 1",
    " router-id 2.2.2.2",
    " network 1.1.1.0 0.0.0.255 area 0",
    "ip route 10.10.10.0 255.255.255.0 1.1.1.1",
]


def _genie_ospf(neighbors):
    """`learn ospf` as Genie shapes it: neighbors {router id: state} on Ethernet0/1 of area 0."""
    interface = {"neighbors": {nbr: {"state": state} for nbr, state in neighbors.items()}}
    area = {"interfaces": {"Ethernet0/1": interface}}
    return {
        "vrf": {"default": {"address_family": {"ipv4": {"instance": {"1": {"areas": {"0.0.0.0": area}}}}}}}
    }


def _write_ospf_snapshot(path, neighbors, r1_extra=(), r2_extra=()):
    """The OSPF twin of _write_snapshot. `neighbors` maps each router to {neighbor: state} as
    Genie's learn reports them (lowercase states, on Ethernet0/1), and the section goes through
    ncv's own adapter, so a neighbor the adapter filed under the wrong key fails the
    prediction. A router left out of `neighbors`, or given {}, lists no neighbor at all."""
    ospf = {}
    for dev in ("R1", "R2"):
        ospf.update(normalize_learn(dev, "ospf", _genie_ospf(neighbors.get(dev, {}))))
    configs = {"R1": R1_OSPF_CONFIG + list(r1_extra), "R2": R2_OSPF_CONFIG + list(r2_extra)}
    _write_lab_snapshot(path, ospf, {}, configs)


def _bgp_diff(root, tmp_path, before, after, label, intent=None):
    report = tmp_path / f"report-{label}"
    intent = intent or root / "fixtures" / "lab-2026-09-18" / "intent-bgp.yaml"
    code = main(["diff", str(before), str(after), "--intent", str(intent), "--report", str(report)])
    findings = json.loads((report / "report.json").read_text(encoding="utf-8"))["findings"]
    return code, sorted((f["policy_id"], f["device"], f["path"]) for f in findings)


def _expected(root, name):
    """A prepared run's predicted change findings, read from scripts/lab/<name> with the parser
    the run script's check uses, so the test and the run compare against one file."""
    check = _load_script(root, "check_findings.py")
    path = root / "scripts" / "lab" / name
    return sorted(check.parse_expected(path.read_text(encoding="utf-8"), str(path)))


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


# The OSPF dead-timer run, prepared and not run yet: OSPF on the link with a 1 s hello (so a
# 4 s dead interval), and an inbound ACL on R1 that drops OSPF from R2 as the planned change.

# Synthetic `show ip ospf interface Ethernet0/1` output; the timers line follows the format
# Genie's IOS XE parser documents. No real output of this command has been captured yet.
OSPF_INTERFACE_FAST = """\
Ethernet0/1 is up, line protocol is up
  Internet Address 1.1.1.1/24, Interface ID 3, Area 0
  Attached via Network Statement
  Process ID 1, Router ID 1.1.1.1, Network Type BROADCAST, Cost: 10
  Transmit Delay is 1 sec, State BDR, Priority 1
  Designated Router (ID) 2.2.2.2, Interface address 1.1.1.2
  Backup Designated router (ID) 1.1.1.1, Interface address 1.1.1.1
  Timer intervals configured, Hello 1, Dead 4, Wait 4, Retransmit 5
    Hello due in 00:00:00
  Neighbor Count is 1, Adjacent neighbor count is 1
"""
OSPF_INTERFACE_DEFAULT = OSPF_INTERFACE_FAST.replace("Hello 1, Dead 4, Wait 4", "Hello 10, Dead 40, Wait 40")
OSPF_NOT_ENABLED = "%OSPF: OSPF not enabled on Ethernet0/1\n"


def test_labctl_reads_the_ospf_interface_timers(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.ospf_interface_timers(OSPF_INTERFACE_FAST) == (1, 4)
    assert labctl.ospf_interface_timers(OSPF_INTERFACE_DEFAULT) == (10, 40)
    assert labctl.ospf_interface_timers(OSPF_NOT_ENABLED) is None
    assert labctl.ospf_interface_timers("") is None


def test_labctl_reads_the_ospf_timers_on_their_line_whatever_follows_them(root):
    """Some IOS XE trains append more timers to the line; only the two numbers on it count, and
    a Hello/Dead pair on any other line is not the configured timers."""
    labctl = _load_script(root, "labctl.py")
    longer = OSPF_INTERFACE_FAST.replace("Retransmit 5", "Retransmit 5, oob-resync timeout 40")
    assert "Retransmit 5, oob-resync timeout 40\n" in longer
    assert labctl.ospf_interface_timers(longer) == (1, 4)
    elsewhere = "  Last seen Hello 10, Dead 40 from a neighbor\n"
    assert labctl.ospf_interface_timers(elsewhere + OSPF_INTERFACE_FAST) == (1, 4)
    assert labctl.ospf_interface_timers(elsewhere) is None


def test_labctl_setup_ospf_fast_sets_the_hello_before_router_ospf(root):
    labctl = _load_script(root, "labctl.py")
    fast = labctl.ospf_setup_lines("R1", labctl.OSPF_FAST_HELLO)
    assert fast[:2] == ["interface Ethernet0/1", "ip ospf hello-interval 1"]
    assert fast.index("ip ospf hello-interval 1") < fast.index("router ospf 1")
    assert fast[2:] == labctl.ospf_setup_lines("R1")
    assert not any("dead-interval" in line for line in fast)
    assert labctl.ospf_setup_lines("R2", 1)[2:] == labctl.ospf_setup_lines("R2")


def test_labctl_ospf_block_drops_ospf_from_r2_and_nothing_else(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.ospf_block_lines() == [
        "ip access-list extended NCV-BLOCK-OSPF",
        "deny ospf host 1.1.1.2 any",
        "permit ip any any",
        "exit",
        "interface Ethernet0/1",
        "ip access-group NCV-BLOCK-OSPF in",
    ]
    assert labctl.ospf_unblock_lines() == [
        "interface Ethernet0/1",
        "no ip access-group NCV-BLOCK-OSPF in",
        "exit",
        "no ip access-list extended NCV-BLOCK-OSPF",
    ]


DEADTIMER_INTENT = ("scripts", "lab", "intent-ospf-deadtimer.yaml")


def test_deadtimer_intent_names_both_adjacencies_and_requires_the_fast_hello(root):
    intent = load_intent(root.joinpath(*DEADTIMER_INTENT))
    assert intent.intent_id == "devnet-default-lab-ospf-deadtimer"
    peers = [(a.device, a.protocol, a.neighbor, a.interface) for a in intent.adjacencies]
    assert peers == [("R1", "ospf", "2.2.2.2", "Ethernet0/1"), ("R2", "ospf", "1.1.1.1", "Ethernet0/1")]
    required = {rule.device: rule.lines for rule in intent.must_include}
    assert "ip ospf hello-interval 1" in required["R1"]
    assert "ip ospf hello-interval 1" in required["R2"]
    assert not any("NCV-BLOCK" in line for lines in required.values() for line in lines)


FAST_HELLO = ["interface Ethernet0/1", " ip ospf hello-interval 1"]
OSPF_ACL_ON_R1 = [
    "ip access-list extended NCV-BLOCK-OSPF",
    " 10 deny ospf host 1.1.1.2 any",
    " 20 permit ip any any",
    "interface Ethernet0/1",
    " ip access-group NCV-BLOCK-OSPF in",
]


def test_deadtimer_run_prediction_on_synthetic_snapshots(root, tmp_path):
    """R1 deletes its neighbor when the dead timer runs out; R2 still hears R1 and holds its
    neighbor in INIT. The two sides differ, both are caught, and nothing else moves. The
    findings are the ones in expect-ospf-deadtimer.txt, which the run script checks too."""
    intent = root.joinpath(*DEADTIMER_INTENT)
    pre, post = tmp_path / "pre", tmp_path / "post"
    full = {"R1": {"2.2.2.2": "full"}, "R2": {"1.1.1.1": "full"}}
    _write_ospf_snapshot(pre, full, FAST_HELLO, FAST_HELLO)
    _write_ospf_snapshot(post, {"R1": {}, "R2": {"1.1.1.1": "init"}}, FAST_HELLO + OSPF_ACL_ON_R1, FAST_HELLO)
    expected = _expected(root, "expect-ospf-deadtimer.txt")
    assert len(expected) == 2
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (0, [])
    assert _bgp_diff(root, tmp_path, pre, post, "change", intent) == (1, expected)
    # The two sides differ in the evidence, not only in the paths: one router has no record,
    # the other has one in the wrong state.
    report = json.loads((tmp_path / "report-change" / "report.json").read_text(encoding="utf-8"))
    after = {(f["device"], f["path"]): f["after"] for f in report["findings"]}
    assert after == {
        ("R1", "ospf.neighbors.2.2.2.2"): None,
        ("R2", "ospf.neighbors.1.1.1.1"): {"state": "init", "interface": "Ethernet0/1"},
    }


def test_deadtimer_intent_refuses_a_capture_without_the_fast_hello(root, tmp_path):
    """The no-change check is what proves the 1 s hello is configured before the change."""
    intent = root.joinpath(*DEADTIMER_INTENT)
    pre = tmp_path / "pre"
    _write_ospf_snapshot(pre, {"R1": {"2.2.2.2": "full"}, "R2": {"1.1.1.1": "full"}})
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (
        1,
        [("V_DRIFT", "R1", "config.running.must_include"), ("V_DRIFT", "R2", "config.running.must_include")],
    )


# The iBGP run, prepared and not run yet: iBGP in AS 65010 between the routers' loopbacks, which
# reach each other only over OSPF, and the dead-timer run's ACL on R1 as the planned change.

IBGP_SUMMARY = """\
BGP router identifier 1.1.1.1, local AS number 65010
Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.255.255.2    4        65010      49      50        3    0    0 00:02:19        1
10.255.255.3    4        65010      12      12        1    0    0 00:00:30        0
10.255.255.4    4        65010       0       0        1    0    0 00:00:05 Idle
10.255.255.5    4        65010       0       0        1    0    0 00:00:02 Active
"""


def test_labctl_reads_the_prefix_count_only_from_an_established_session(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.bgp_prefixes_received(IBGP_SUMMARY, "10.255.255.2") == 1
    assert labctl.bgp_prefixes_received(IBGP_SUMMARY, "10.255.255.3") == 0
    assert labctl.bgp_prefixes_received(IBGP_SUMMARY, "10.255.255.4") is None
    assert labctl.bgp_prefixes_received(IBGP_SUMMARY, "10.255.255.5") is None
    assert labctl.bgp_prefixes_received(IBGP_SUMMARY, "10.255.255.6") is None
    assert labctl.bgp_prefixes_received(BGP_SUMMARY, "1.1.1.3") is None  # Idle (Admin)
    assert labctl.bgp_prefixes_received("", "10.255.255.2") is None
    # Why the count is needed: a session that has learned nothing yet already reads as up.
    assert labctl.bgp_session_state(IBGP_SUMMARY, "10.255.255.3") is True


def test_labctl_setup_ibgp_lines_for_r1(root):
    labctl = _load_script(root, "labctl.py")
    r1 = labctl.ibgp_setup_lines("R1")
    assert r1 == [
        "interface Loopback0",
        "ip address 10.255.255.1 255.255.255.255",
        "interface Loopback1",
        "ip address 172.16.1.1 255.255.255.0",
        "interface Ethernet0/1",
        "ip ospf hello-interval 1",
        "router ospf 1",
        "router-id 1.1.1.1",
        "network 1.1.1.0 0.0.0.255 area 0",
        "network 10.255.255.1 0.0.0.0 area 0",
        "router bgp 65010",
        "bgp router-id 1.1.1.1",
        "bgp log-neighbor-changes",
        "neighbor 10.255.255.2 remote-as 65010",
        "neighbor 10.255.255.2 update-source Loopback0",
        "neighbor 10.255.255.2 timers 3 9",
        "address-family ipv4",
        "network 172.16.1.0 mask 255.255.255.0",
        "neighbor 10.255.255.2 activate",
        "neighbor 10.255.255.2 soft-reconfiguration inbound",
        "exit-address-family",
    ]
    # setup-ospf-fast's lines, reused, with Loopback0 added to area 0; Loopback1 is not in OSPF.
    assert r1[4:9] == labctl.ospf_setup_lines("R1", labctl.OSPF_FAST_HELLO)
    assert [line for line in r1 if line.endswith(" area 0")] == r1[8:10]


# R1's values and R2's, both ways round: Loopback0, Loopback1, and the router id.
_MIRROR = {
    "10.255.255.1": "10.255.255.2",
    "10.255.255.2": "10.255.255.1",
    "172.16.1.": "172.16.2.",
    "1.1.1.1": "2.2.2.2",
}


def _mirrored(line):
    return re.sub("|".join(map(re.escape, _MIRROR)), lambda m: _MIRROR[m.group(0)], line)


def test_labctl_setup_ibgp_lines_for_r2_differ_only_in_the_mirrored_values(root):
    labctl = _load_script(root, "labctl.py")
    r1, r2 = labctl.ibgp_setup_lines("R1"), labctl.ibgp_setup_lines("R2")
    assert [_mirrored(line) for line in r1] == r2
    assert sum(a != b for a, b in zip(r1, r2, strict=True)) == 11


IBGP_INTENT = ("scripts", "lab", "intent-ibgp.yaml")


def test_ibgp_intent_names_four_adjacencies_the_learned_routes_and_the_required_lines(root):
    intent = load_intent(root.joinpath(*IBGP_INTENT))
    assert intent.intent_id == "devnet-default-lab-ibgp"
    adjacencies = [
        (a.device, a.protocol, a.neighbor, a.interface, a.vrf, a.remote_as) for a in intent.adjacencies
    ]
    assert adjacencies == [
        ("R1", "ospf", "2.2.2.2", "Ethernet0/1", "", None),
        ("R2", "ospf", "1.1.1.1", "Ethernet0/1", "", None),
        ("R1", "bgp", "10.255.255.2", "", "default", 65010),
        ("R2", "bgp", "10.255.255.1", "", "default", 65010),
    ]
    learned = {(r.device, r.prefix, r.protocol) for r in intent.routes if r.protocol in ("ospf", "bgp")}
    assert learned == {
        ("R1", "10.255.255.2/32", "ospf"),
        ("R1", "172.16.2.0/24", "bgp"),
        ("R2", "10.255.255.1/32", "ospf"),
        ("R2", "172.16.1.0/24", "bgp"),
    }
    assert {r.vrf for r in intent.routes} == {"default"}
    required = {rule.device: rule.lines for rule in intent.must_include}
    for device, peer, static in (
        ("R1", "10.255.255.2", "ip route 20.20.20.0 255.255.255.0 1.1.1.2"),
        ("R2", "10.255.255.1", "ip route 10.10.10.0 255.255.255.0 1.1.1.1"),
    ):
        assert set(required[device]) == {
            "router ospf 1",
            "ip ospf hello-interval 1",
            "router bgp 65010",
            f"neighbor {peer} remote-as 65010",
            f"neighbor {peer} update-source Loopback0",
            f"neighbor {peer} timers 3 9",
            static,
        }
    assert not any("NCV-BLOCK" in line for lines in required.values() for line in lines)
    assert intent.must_absent == ()


# Each router's iBGP peer (the other's Loopback0) and the prefix it learns from it, its own
# router id, and its static route.
IBGP_PEER = {"R1": ("10.255.255.2", "172.16.2.0/24"), "R2": ("10.255.255.1", "172.16.1.0/24")}
OWN_ID = {"R1": "1.1.1.1", "R2": "2.2.2.2"}
STATIC = {"R1": R1_CONFIG[-1], "R2": R2_CONFIG[-1]}


def _genie_bgp_by_vrf(peer, remote_as, states):
    """`learn bgp` as Genie shapes it: one peer address in each VRF of `states` ({vrf: session
    state}), all in the default instance, as Genie's IOS XE test data files 2.2.2.2 in both
    `default` and `VRF1`."""
    record = {"remote_as": remote_as}
    vrfs = {vrf: {"neighbor": {peer: {**record, "session_state": state}}} for vrf, state in states.items()}
    return {"instance": {"default": {"vrf": vrfs}}}


def _genie_bgp(peer, state):
    """`learn bgp` as Genie shapes it: one peer in the default VRF of the default instance."""
    return _genie_bgp_by_vrf(peer, 65010, {"default": state})


def _ibgp_config(device, extra=()):
    peer, _ = IBGP_PEER[device]
    return [
        f"hostname {device}",
        "interface Ethernet0/1",
        " ip ospf hello-interval 1",
        "router ospf 1",
        f" router-id {OWN_ID[device]}",
        "router bgp 65010",
        f" neighbor {peer} remote-as 65010",
        f" neighbor {peer} update-source Loopback0",
        f" neighbor {peer} timers 3 9",
        STATIC[device],
        *extra,
    ]


def _write_ibgp_snapshot(path, ospf, bgp, missing=(), r1_extra=()):
    """The iBGP run's capture. `ospf` maps each router to {router id: state} and `bgp` to its
    session state; both go through ncv's adapter from Genie's shapes, so a neighbor filed under
    the wrong key fails the prediction. The routes are the lab's plus each router's two learned
    ones, less the (router, prefix) pairs in `missing`."""
    ospf_section, bgp_section, routes = {}, {}, {}
    for device, (peer, prefix) in IBGP_PEER.items():
        ospf_section.update(normalize_learn(device, "ospf", _genie_ospf(ospf[device])))
        bgp_section.update(normalize_learn(device, "bgp", _genie_bgp(peer, bgp[device])))
        learned = {f"{peer}/32": {"protocol": "ospf"}, prefix: {"protocol": "bgp"}}
        table = {**learned, **LAB_ROUTES[device]}
        routes[device] = {p: rec for p, rec in table.items() if (device, p) not in missing}
    configs = {"R1": _ibgp_config("R1", r1_extra), "R2": _ibgp_config("R2")}
    _write_lab_snapshot(path, ospf_section, bgp_section, configs, routes)


IBGP_UP = {"R1": {"2.2.2.2": "full"}, "R2": {"1.1.1.1": "full"}}
ESTABLISHED = {"R1": "Established", "R2": "Established"}


def test_ibgp_run_prediction_on_synthetic_snapshots(root, tmp_path):
    """One cause, three layers: the ACL ends OSPF, so each router loses the route to its peer's
    loopback, the iBGP session over it, and the prefix learned through that session. Both
    routers, the eight findings in expect-ibgp.txt, and still no V_DRIFT: no rule names the
    ACL."""
    intent = root.joinpath(*IBGP_INTENT)
    pre, post = tmp_path / "pre", tmp_path / "post"
    _write_ibgp_snapshot(pre, IBGP_UP, ESTABLISHED)
    lost = [
        (device, route) for device, (peer, prefix) in IBGP_PEER.items() for route in (f"{peer}/32", prefix)
    ]
    ospf_after = {"R1": {}, "R2": {"1.1.1.1": "init"}}
    _write_ibgp_snapshot(post, ospf_after, {"R1": "Idle", "R2": "Idle"}, lost, OSPF_ACL_ON_R1)
    expected = _expected(root, "expect-ibgp.txt")
    assert len(expected) == 8
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (0, [])
    assert _bgp_diff(root, tmp_path, pre, post, "change", intent) == (1, expected)
    report = json.loads((tmp_path / "report-change" / "report.json").read_text(encoding="utf-8"))
    after = {(f["device"], f["path"]): f["after"] for f in report["findings"]}
    assert after[("R1", "ospf.neighbors.2.2.2.2")] is None
    assert after[("R2", "ospf.neighbors.1.1.1.1")]["state"] == "init"
    assert after[("R1", "bgp.vrfs.default.neighbors.10.255.255.2")] == {"state": "Idle", "remote_as": 65010}
    assert after[("R2", "routing.vrfs.default.routes.172.16.1.0/24")] is None


def test_ibgp_intent_refuses_a_setup_that_never_learned_the_bgp_prefix(root, tmp_path):
    """The no-change check is what proves the design: with a `network` statement forgotten, the
    sessions are Established with nothing learned, and the missing prefix stops the run."""
    intent = root.joinpath(*IBGP_INTENT)
    pre = tmp_path / "pre"
    missing = [(device, prefix) for device, (_, prefix) in IBGP_PEER.items()]
    _write_ibgp_snapshot(pre, IBGP_UP, ESTABLISHED, missing)
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (
        1,
        [
            ("V_ROUTE", "R1", "routing.vrfs.default.routes.172.16.2.0/24"),
            ("V_ROUTE", "R2", "routing.vrfs.default.routes.172.16.1.0/24"),
        ],
    )


# The BGP VRF run, prepared and not run yet: the hold-timer run's eBGP session in the global
# table plus a second one to the same peer address in vrf NCV on Ethernet0/1.100, and
# `shutdown` on R1's subinterface as the planned change.


def test_labctl_setup_vrf_lines_for_r1_in_the_order_ios_needs(root):
    labctl = _load_script(root, "labctl.py")
    r1 = labctl.vrf_setup_lines("R1")
    assert r1 == [
        "vrf definition NCV",
        "rd 65001:100",
        "address-family ipv4",
        "exit-address-family",
        "interface Ethernet0/1.100",
        "encapsulation dot1Q 100",
        "vrf forwarding NCV",
        "ip address 1.1.1.1 255.255.255.0",
        "no shutdown",
        "interface Loopback100",
        "vrf forwarding NCV",
        "ip address 172.16.101.1 255.255.255.0",
        "router bgp 65001",
        "address-family ipv4 vrf NCV",
        "neighbor 1.1.1.2 remote-as 65002",
        "neighbor 1.1.1.2 timers 3 9",
        "neighbor 1.1.1.2 activate",
        "neighbor 1.1.1.2 soft-reconfiguration inbound",
        "network 172.16.101.0 mask 255.255.255.0",
        "exit-address-family",
    ]
    # The order is the point: the tag before any address on the subinterface, `vrf forwarding`
    # before the address it would strip, and the route distinguisher before BGP's VRF family.
    # `no shutdown` last: a subinterface IOS brings back after a reset deleted it shut stays down.
    subinterface = r1[r1.index("interface Ethernet0/1.100") : r1.index("interface Loopback100")]
    assert (
        subinterface.index("encapsulation dot1Q 100")
        < subinterface.index("vrf forwarding NCV")
        < subinterface.index("ip address 1.1.1.1 255.255.255.0")
    )
    assert subinterface[-1] == "no shutdown"
    assert r1.index("rd 65001:100") < r1.index("router bgp 65001")
    # Each router's VRF address is its own global one, which the other router names as its peer.
    for name, other in (("R1", "R2"), ("R2", "R1")):
        assert labctl.VRF_ADDRESSES[name] == labctl.BGP[other]["peer"]


def test_labctl_setup_vrf_lines_for_r2_differ_only_in_the_mirrored_values(root):
    labctl = _load_script(root, "labctl.py")
    mirror = {
        "65001": "65002",
        "65002": "65001",
        "1.1.1.1": "1.1.1.2",
        "1.1.1.2": "1.1.1.1",
        "172.16.101.": "172.16.102.",
    }

    def mirrored(line):
        return re.sub("|".join(map(re.escape, mirror)), lambda m: mirror[m.group(0)], line)

    r1, r2 = labctl.vrf_setup_lines("R1"), labctl.vrf_setup_lines("R2")
    assert [mirrored(line) for line in r1] == r2
    assert "rd 65002:100" in r2 and "network 172.16.102.0 mask 255.255.255.0" in r2


def test_labctl_vrf_change_shuts_only_the_subinterface(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.vrf_shut_lines() == ["interface Ethernet0/1.100", "shutdown"]
    assert labctl.vrf_noshut_lines() == ["interface Ethernet0/1.100", "no shutdown"]


# Synthetic VRF output, in the format the global commands printed on 2026-11-20; Genie's IOS XE
# parser test data prints VRF neighbors the same way. No VRF output has been captured.
VRF_SUMMARY = """\
BGP router identifier 1.1.1.1, local AS number 65001
BGP table version is 3, main routing table version 3
Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
1.1.1.2         4        65002      12      12        3    0    0 00:00:31        1
"""
VRF_NEIGHBOR = """\
BGP neighbor is 1.1.1.2,  vrf NCV,  remote AS 65002, external link
  BGP version 4, remote router ID 2.2.2.2
  BGP state = Established, up for 00:00:31
  Last read 00:00:01, last write 00:00:02, hold time is 9, keepalive interval is 3 seconds
  Configured hold time is 9, keepalive interval is 3 seconds
"""


def test_labctl_reads_the_vrf_table_with_the_global_parsers(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.bgp_session_state(VRF_SUMMARY, "1.1.1.2") is True
    assert labctl.bgp_prefixes_received(VRF_SUMMARY, "1.1.1.2") == 1
    assert labctl.bgp_prefixes_received(VRF_SUMMARY.replace("        1\n", " Idle\n"), "1.1.1.2") is None
    assert labctl.bgp_negotiated_timers(VRF_NEIGHBOR) == (9, 3)
    assert labctl.VRF_BGP_SUMMARY == "show bgp vpnv4 unicast vrf NCV summary"
    assert labctl.VRF_BGP_NEIGHBORS == "show bgp vpnv4 unicast vrf NCV neighbors"


# Synthetic `show vrf` output, in the column format Genie's IOS XE ShowVrf parser documents: a
# VRF with several interfaces continues on lines holding only interface names.
SHOW_VRF = """\
  Name                             Default RD            Protocols   Interfaces
  Mgmt-intf                        <not set>             ipv4        Et0/2
  NCV                              65001:100             ipv4        Et0/1.100
                                                                     Lo100
  NCV-OTHER                        65001:200             ipv4
"""


def test_labctl_reads_whether_show_vrf_still_lists_a_vrf(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.vrf_listed(SHOW_VRF, "NCV") is True
    assert labctl.vrf_listed(SHOW_VRF, "Mgmt-intf") is True
    without = "\n".join(line for line in SHOW_VRF.splitlines() if not line.strip().startswith("NCV "))
    assert labctl.vrf_listed(without, "NCV") is False  # NCV-OTHER is another VRF
    assert labctl.vrf_listed(SHOW_VRF, "Lo100") is False  # a continuation line is not a VRF row
    assert labctl.vrf_listed("", "NCV") is False
    # The two rows Genie's IOS XE parser documents for a VRF that IOS is still deleting.
    assert labctl.vrf_listed("  * NCV                            65001:100             ipv4", "NCV") is True
    assert labctl.vrf_listed("  NCV        <being deleted>       ipv4        Et0/1.100", "NCV") is True
    assert labctl.vrf_listed("  * NCV-OTHER                      65001:200             ipv4", "NCV") is False
    assert labctl.vrf_listed("  *", "NCV") is False


BGP_VRF_INTENT = ("scripts", "lab", "intent-bgp-vrf.yaml")


def test_bgp_vrf_intent_names_four_bgp_adjacencies_two_per_router_one_per_vrf(root):
    intent = load_intent(root.joinpath(*BGP_VRF_INTENT))
    assert intent.intent_id == "devnet-default-lab-bgp-vrf"
    adjacencies = [(a.device, a.protocol, a.neighbor, a.vrf, a.remote_as) for a in intent.adjacencies]
    assert sorted(adjacencies) == [
        ("R1", "bgp", "1.1.1.2", "NCV", 65002),
        ("R1", "bgp", "1.1.1.2", "default", 65002),
        ("R2", "bgp", "1.1.1.1", "NCV", 65001),
        ("R2", "bgp", "1.1.1.1", "default", 65001),
    ]
    in_vrf = {(r.device, r.prefix, r.protocol) for r in intent.routes if r.vrf == "NCV"}
    assert in_vrf == {
        ("R1", "1.1.1.0/24", "connected"),
        ("R1", "172.16.102.0/24", "bgp"),
        ("R2", "1.1.1.0/24", "connected"),
        ("R2", "172.16.101.0/24", "bgp"),
    }
    assert [(i.device, i.name) for i in intent.interfaces] == [("R1", "Ethernet0/1"), ("R2", "Ethernet0/1")]
    required = {rule.device: rule.lines for rule in intent.must_include}
    holdtimer = load_intent(root / "fixtures" / "lab-2026-11-20" / "intent-bgp-holdtimer.yaml")
    added = ("vrf definition NCV", "encapsulation dot1Q 100", "address-family ipv4 vrf NCV")
    for rule in holdtimer.must_include:
        assert required[rule.device] == (*rule.lines, *added)
    assert intent.must_absent == ()


# Each router's peer address (the same in both tables), its remote AS, and the prefix it learns
# in vrf NCV: the other router's Loopback100 network.
VRF_PEER = {"R1": ("1.1.1.2", 65002, "172.16.102.0/24"), "R2": ("1.1.1.1", 65001, "172.16.101.0/24")}


def _vrf_run_config(device, subinterface_extra=()):
    """One router's running config with the run's setup in place, as IOS would list it: the
    global session's lines appear twice, once under router bgp and once in the VRF family."""
    hostname, router_bgp, router_id, remote_as, static = R1_CONFIG if device == "R1" else R2_CONFIG
    peer, _, _ = VRF_PEER[device]
    own = VRF_PEER["R2" if device == "R1" else "R1"][0]
    timers = f" neighbor {peer} timers 3 9"
    return [
        hostname,
        "vrf definition NCV",
        f" rd {router_bgp.split()[-1]}:100",
        " address-family ipv4",
        " exit-address-family",
        "interface Ethernet0/1.100",
        " encapsulation dot1Q 100",
        " vrf forwarding NCV",
        f" ip address {own} 255.255.255.0",
        *subinterface_extra,
        router_bgp,
        router_id,
        remote_as,
        timers,
        " address-family ipv4 vrf NCV",
        f" {remote_as}",
        f" {timers}",
        f"  neighbor {peer} activate",
        " exit-address-family",
        static,
    ]


def _write_vrf_snapshot(path, states, lost=(), r1_subinterface=()):
    """The BGP VRF run's capture. `states` maps each router to {vrf: session state}; the BGP
    section goes through ncv's adapter from Genie's shape, with the same peer address under
    `default` and `NCV`, so an adapter that merged or dropped the VRF neighbor fails the
    prediction. Each router's vrf NCV table holds the link's connected route and the prefix it
    learns, less the (router, prefix) pairs in `lost`; the default table is the lab's."""
    bgp_section, in_vrf = {}, {}
    for device, (peer, remote_as, learned) in VRF_PEER.items():
        bgp_section.update(normalize_learn(device, "bgp", _genie_bgp_by_vrf(peer, remote_as, states[device])))
        table = {"1.1.1.0/24": {"protocol": "connected"}, learned: {"protocol": "bgp"}}
        in_vrf[device] = {"NCV": {p: rec for p, rec in table.items() if (device, p) not in lost}}
    configs = {"R1": _vrf_run_config("R1", r1_subinterface), "R2": _vrf_run_config("R2")}
    _write_lab_snapshot(path, {}, bgp_section, configs, other_vrfs=in_vrf)


BOTH_UP = {"default": "Established", "NCV": "Established"}


def test_bgp_vrf_run_prediction_on_synthetic_snapshots(root, tmp_path):
    """The same neighbor address in two VRFs on each router, and only the VRF session broken:
    R1 resets it at once and loses the VRF's connected route with its subinterface, R2 loses it
    on its hold timer and with it the prefix it learned. The five findings in
    expect-bgp-vrf.txt, all in vrf NCV; the default VRF's session to the same address and its
    1.1.1.0/24 stay compliant."""
    intent = root.joinpath(*BGP_VRF_INTENT)
    pre, post = tmp_path / "pre", tmp_path / "post"
    _write_vrf_snapshot(pre, {"R1": BOTH_UP, "R2": BOTH_UP})
    after = {"R1": {**BOTH_UP, "NCV": "Idle"}, "R2": {**BOTH_UP, "NCV": "Active"}}
    lost = [("R1", "1.1.1.0/24"), ("R1", "172.16.102.0/24"), ("R2", "172.16.101.0/24")]
    _write_vrf_snapshot(post, after, lost, [" shutdown"])
    # The adapter kept both records: one address, two VRFs, two neighbors.
    captured = json.loads((post / "bgp.json").read_text(encoding="utf-8"))
    assert {dev: sorted(node["vrfs"]) for dev, node in captured.items()} == {
        "R1": ["NCV", "default"],
        "R2": ["NCV", "default"],
    }
    expected = _expected(root, "expect-bgp-vrf.txt")
    assert len(expected) == 5
    assert all(path.split(".")[1:3] == ["vrfs", "NCV"] for _, _, path in expected)
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (0, [])
    assert _bgp_diff(root, tmp_path, pre, post, "change", intent) == (1, expected)
    report = json.loads((tmp_path / "report-change" / "report.json").read_text(encoding="utf-8"))
    evidence = {(f["device"], f["path"]): (f["before"], f["after"]) for f in report["findings"]}
    assert evidence[("R1", "bgp.vrfs.NCV.neighbors.1.1.1.2")] == (
        {"state": "Established", "remote_as": 65002},
        {"state": "Idle", "remote_as": 65002},
    )
    assert evidence[("R2", "routing.vrfs.NCV.routes.172.16.101.0/24")][1] is None
    restored = tmp_path / "restored"
    _write_vrf_snapshot(restored, {"R1": BOTH_UP, "R2": BOTH_UP})
    assert _bgp_diff(root, tmp_path, pre, restored, "restored", intent) == (0, [])


def test_bgp_vrf_mirror_case_the_global_session_down_is_reported_for_the_default_vrf_only(root, tmp_path):
    """The other way round, to show the VRF key is what separates the two: the global sessions
    down and the VRF ones up give findings at bgp.vrfs.default only. The default VRF's routes
    are static and connected, which the global session never carried."""
    intent = root.joinpath(*BGP_VRF_INTENT)
    pre, post = tmp_path / "pre", tmp_path / "post"
    _write_vrf_snapshot(pre, {"R1": BOTH_UP, "R2": BOTH_UP})
    _write_vrf_snapshot(post, {"R1": {**BOTH_UP, "default": "Idle"}, "R2": {**BOTH_UP, "default": "Active"}})
    assert _bgp_diff(root, tmp_path, pre, post, "change", intent) == (
        1,
        [
            ("V_ADJ", "R1", "bgp.vrfs.default.neighbors.1.1.1.2"),
            ("V_ADJ", "R2", "bgp.vrfs.default.neighbors.1.1.1.1"),
        ],
    )


def test_bgp_vrf_intent_refuses_a_vrf_session_that_never_learned_its_prefix(root, tmp_path):
    """Both sessions Established in both tables, but a VRF `network` statement forgotten: the
    missing prefixes stop the run at the no-change check."""
    intent = root.joinpath(*BGP_VRF_INTENT)
    pre = tmp_path / "pre"
    lost = [("R1", "172.16.102.0/24"), ("R2", "172.16.101.0/24")]
    _write_vrf_snapshot(pre, {"R1": BOTH_UP, "R2": BOTH_UP}, lost)
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (
        1,
        [
            ("V_ROUTE", "R1", "routing.vrfs.NCV.routes.172.16.102.0/24"),
            ("V_ROUTE", "R2", "routing.vrfs.NCV.routes.172.16.101.0/24"),
        ],
    )


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
    """Only NCV- ACLs, OSPF process 1, the BGP processes and interfaces the scripts name, and
    vrf NCV are the scripts' own, and the spare port in either order is still what ships."""
    labctl = _load_script(root, "labctl.py")
    config = "\n".join(
        [
            "interface Loopback7",
            " ip address 7.7.7.7 255.255.255.255",
            "interface Ethernet0/1",
            " ip address 1.1.1.1 255.255.255.0",
            " ip access-group OPERATOR in",
            "interface Ethernet0/1.200",
            " encapsulation dot1Q 200",
            "interface Ethernet0/3",
            " shutdown",
            " no ip address",
            "router ospf 2",
            "router bgp 64512",
            " bgp log-neighbor-changes",
            "ip access-list extended OPERATOR",
            " permit ip any any",
            "vrf definition NCV-OTHER",
        ]
    )
    assert labctl.reset_lines(config) == []


def test_reset_after_the_deadtimer_run_removes_the_acl_ospf_and_the_hello(root):
    """Both routers as IOS would list them with this run's setup in place, R1 also with its
    change: one Ethernet0/1 block carrying the hello line and, on R1, the ACL binding."""
    labctl = _load_script(root, "labctl.py")
    link = ["interface Ethernet0/1", " ip address 1.1.1.{} 255.255.255.0"]
    r1 = "\n".join(
        [R1_OSPF_CONFIG[0], *link, " ip access-group NCV-BLOCK-OSPF in", " ip ospf hello-interval 1"]
        + R1_OSPF_CONFIG[1:]
        + OSPF_ACL_ON_R1[:3]
    ).format(1)
    r2 = "\n".join([R2_OSPF_CONFIG[0], *link, " ip ospf hello-interval 1", *R2_OSPF_CONFIG[1:]]).format(2)
    assert labctl.reset_lines(r1) == [
        "interface Ethernet0/1",
        "no ip access-group NCV-BLOCK-OSPF in",
        "no ip access-list extended NCV-BLOCK-OSPF",
        "no router ospf 1",
        "interface Ethernet0/1",
        "no ip ospf hello-interval",
    ]
    assert labctl.reset_lines(r2) == [
        "no router ospf 1",
        "interface Ethernet0/1",
        "no ip ospf hello-interval",
    ]


def test_reset_after_the_ibgp_run_removes_bgp_ospf_the_hello_and_both_loopbacks(root):
    """Both routers as IOS would list them with this run's whole setup in place, R1 also with its
    change: two loopbacks, the hello line, OSPF with Loopback0 in area 0, and router bgp 65010."""
    labctl = _load_script(root, "labctl.py")

    def running(device, binding=(), acl=()):
        peer, _ = IBGP_PEER[device]
        n = 1 if device == "R1" else 2
        return "\n".join(
            [
                f"hostname {device}",
                "interface Loopback0",
                f" ip address 10.255.255.{n} 255.255.255.255",
                "interface Loopback1",
                f" ip address 172.16.{n}.1 255.255.255.0",
                "interface Ethernet0/1",
                f" ip address 1.1.1.{n} 255.255.255.0",
                *binding,
                " ip ospf hello-interval 1",
                "router ospf 1",
                f" router-id {OWN_ID[device]}",
                " network 1.1.1.0 0.0.0.255 area 0",
                f" network 10.255.255.{n} 0.0.0.0 area 0",
                "router bgp 65010",
                f" bgp router-id {OWN_ID[device]}",
                f" neighbor {peer} remote-as 65010",
                f" neighbor {peer} update-source Loopback0",
                f" neighbor {peer} timers 3 9",
                " address-family ipv4",
                f"  network 172.16.{n}.0 mask 255.255.255.0",
                " exit-address-family",
                STATIC[device],
                *acl,
            ]
        )

    setup_undo = [
        "no router bgp 65010",
        "no router ospf 1",
        "interface Ethernet0/1",
        "no ip ospf hello-interval",
        "no interface Loopback0",
        "no interface Loopback1",
    ]
    r1 = running("R1", [" ip access-group NCV-BLOCK-OSPF in"], OSPF_ACL_ON_R1[:3])
    assert labctl.reset_lines(r1) == [
        "interface Ethernet0/1",
        "no ip access-group NCV-BLOCK-OSPF in",
        "no ip access-list extended NCV-BLOCK-OSPF",
        *setup_undo,
    ]
    assert labctl.reset_lines(running("R2")) == setup_undo


def test_reset_after_the_bgp_vrf_run_removes_bgp_then_the_subinterface_and_loopback_then_the_vrf(root):
    """Both routers as IOS would list them with this run's whole setup in place, R1 also with its
    change (the subinterface shut down). BGP goes first, with its VRF address family inside it,
    then the two interfaces in vrf NCV, and the VRF definition last, once nothing uses it."""
    labctl = _load_script(root, "labctl.py")

    def running(device, subinterface_extra=()):
        n = 1 if device == "R1" else 2
        config = _vrf_run_config(device, subinterface_extra)
        loopback = [
            "interface Loopback100",
            " vrf forwarding NCV",
            f" ip address 172.16.10{n}.1 255.255.255.0",
        ]
        # IOS lists the VRF definitions first, then the interfaces (loopbacks before Ethernet).
        return "\n".join(config[:5] + loopback + config[5:])

    for device, asn, extra in (("R1", 65001, [" shutdown"]), ("R2", 65002, [])):
        assert labctl.reset_lines(running(device, extra)) == [
            f"no router bgp {asn}",
            "no interface Loopback100",
            "no interface Ethernet0/1.100",
            "no vrf definition NCV",
        ]


def _r3_run_config(ethernet0_3_extra=()):
    """R1's running config with the second-platform run's setup in place (setup-ospf, setup-bgp,
    setup-r3-link), as IOS would list it: the R3 peer inside the one BGP process."""
    return [
        "hostname R1",
        "interface Ethernet0/1",
        " ip address 1.1.1.1 255.255.255.0",
        "interface Ethernet0/3",
        " ip address 10.1.3.1 255.255.255.0",
        " ip ospf hello-interval 1",
        *ethernet0_3_extra,
        "router ospf 1",
        " router-id 1.1.1.1",
        " network 1.1.1.0 0.0.0.255 area 0",
        " network 10.1.3.0 0.0.0.255 area 0",
        "router bgp 65001",
        " bgp router-id 1.1.1.1",
        " bgp log-neighbor-changes",
        " neighbor 1.1.1.2 remote-as 65002",
        " neighbor 10.1.3.3 remote-as 65003",
        " neighbor 10.1.3.3 timers 3 9",
        " address-family ipv4",
        "  network 10.10.10.0 mask 255.255.255.0",
        "  neighbor 1.1.1.2 activate",
        "  neighbor 1.1.1.2 soft-reconfiguration inbound",
        "  neighbor 10.1.3.3 activate",
        "  neighbor 10.1.3.3 soft-reconfiguration inbound",
        " exit-address-family",
        R1_CONFIG[-1],
    ]


def test_reset_after_the_second_platform_run_removes_bgp_ospf_and_returns_ethernet0_3_to_what_ships(root):
    """With R3's link up, and with it shut by the run's change: one BGP process carries both peers
    and goes whole, and Ethernet0/3, with its address and hello, is defaulted and shut again.
    Nothing on R3 is reset: labctl.py never configures it, and cml_lab.py remove-r3 removes it."""
    labctl = _load_script(root, "labctl.py")
    undo = [
        "no router bgp 65001",
        "no router ospf 1",
        "default interface Ethernet0/3",
        "interface Ethernet0/3",
        "shutdown",
    ]
    assert labctl.reset_lines("\n".join(_r3_run_config())) == undo
    assert labctl.reset_lines("\n".join(_r3_run_config([" shutdown"]))) == undo


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("run-ospf-deadtimer.sh", "expect-ospf-deadtimer.txt"),
        ("run-ibgp.sh", "expect-ibgp.txt"),
        ("run-bgp-vrf.sh", "expect-bgp-vrf.txt"),
    ],
)
def test_each_prepared_run_checks_its_change_findings_against_its_expected_file(root, script, expected):
    """The run script and the prediction test read one file, and the shared helpers do the
    reset and the packet capture, so an early exit stops the capture and a failed reset stops
    the run."""
    text = (root / "scripts" / "lab" / script).read_text(encoding="utf-8")
    assert f'expect_findings change "$out-change" scripts/lab/{expected}\n' in text
    assert text.index('compare pre post change; expect_exit change 1 "$?"') < text.index("expect_findings")
    assert "\nlab_reset\n" in text
    assert "ctl reset" not in text
    assert "cap_start " in text and "\ncap_stop\nlab_finish\n" in text
    assert "cap start" not in text and "cap stop" not in text


def _credential_values(node):
    """Every username and password value anywhere in a parsed testbed."""
    if isinstance(node, dict):
        found = [v for k, v in node.items() if k in ("username", "password")]
        return found + [v for item in node.values() for v in _credential_values(item)]
    if isinstance(node, list):
        return [v for item in node for v in _credential_values(item)]
    return []


def test_the_ssh_testbed_example_names_both_routers_by_management_address_and_holds_no_password(root):
    text = (root / "testbeds" / "cml-ssh.yaml.example").read_text(encoding="utf-8")
    testbed = yaml.safe_load(text)
    devices = testbed["devices"]
    assert {name: device["connections"]["cli"]["ip"] for name, device in devices.items()} == {
        "R1": "10.10.20.171",
        "R2": "10.10.20.172",
    }
    for device in devices.values():
        cli = device["connections"]["cli"]
        assert (device["os"], cli["protocol"], cli["port"]) == ("iosxe", "ssh", 22)
        assert cli["ssh_options"].split() == [
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "UserKnownHostsFile=output/lab/known_hosts",
            "-o",
            "ConnectTimeout=10",
        ]
        assert cli["arguments"] == {"learn_hostname": True, "connection_timeout": 60}
    assert testbed["testbed"]["credentials"] == {
        "default": {"username": "%ENV{NCV_SSH_USER}", "password": "%ENV{NCV_SSH_PASS}"},
        "enable": {"password": "%ENV{NCV_LAB_PASS}"},
    }
    values = _credential_values(testbed)
    assert len(values) == 3
    assert all(re.fullmatch(r"%ENV\{NCV_\w+\}", value) for value in values)
    assert "NCV_SSH_PASS" in text  # what makes _lib.sh ask for the SSH login


def test_the_probe_only_reads(root):
    text = (root / "scripts" / "lab" / "probe.sh").read_text(encoding="utf-8")
    assert "Read-only." in text.splitlines()[1]
    assert "\nlab_init probe\n" in text
    assert re.findall(r"\bctl (\S+)", text) == ["probe"]
    assert '"$here/cml_lab.py" inspect "$out-cml"' in text
    for action in ("snap ", "compare ", "cap ", "cap_start", "lab_reset", "configure", "change.sh"):
        assert action not in text
    assert 'exit "$failed"' in text


def test_the_ssh_path_run_checks_the_port_before_it_resets_and_captures_both_paths_in_order(root):
    text = (root / "scripts" / "lab" / "run-ssh-path.sh").read_text(encoding="utf-8")
    assert "Prepared, not run yet." in text.splitlines()[1]
    steps = [
        '. "$here/_lib.sh"\nlab_takes_no_arguments "$@"\n',
        "ssh_testbed=testbeds/lab-ssh.yaml",
        "export NCV_TESTBED=testbeds/lab.yaml",
        "lab_init ssh-path",
        "lab_ssh_login",
        'lab_tcp "$address" 22',
        "lab_not_reachable ",
        "\nlab_reset\n",
        "snap console",
        "rm -f output/lab/known_hosts",
        "testbed=$ssh_testbed",
        "snap ssh",
        '"$here/compare_captures.py" "$run/console" "$run/ssh"',
        "expect_exit same-data 0",
        'compare console ssh access-path; expect_exit access-path 0 "$?"',
        "\nlab_finish\n",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "intent=fixtures/lab-2026-09-12/intent-routes.yaml\n" in text
    assert "features=routing,interface\n" in text
    assert re.findall(r"\bctl ", text) == []  # nothing but lab_reset touches the routers' configuration
    # step N in the log is step N in the header and in scripts/lab/README.md: the reset is 3
    labels = re.findall(r'^step "([^ ]+) (\S+)', text, re.M)
    assert labels == [
        ("1/7", "the"),
        ("2/7", "port"),
        ("3/7", "reset"),
        ("4/7", "capture"),
        ("5/7", "capture"),
        ("6/7", "compare_captures.py"),
        ("7/7", "ncv"),
    ]
    assert '\nstep "finish"\nlab_finish\n' in text
    header = [line[4:6] for line in text.splitlines() if re.match(r"^#   \d\. ", line)]
    assert header == ["1.", "2.", "3.", "4.", "5.", "6.", "7."]
    assert "#   3. labctl.py reset" in text


# The second-platform run, prepared and not run yet: R3, a router of another platform that
# cml_lab.py adds and links to R1 Ethernet0/3, peering with R1 over OSPF and eBGP, and `shutdown`
# on R1 Ethernet0/3 as the planned change.

PLATFORMS = ("nxosv9000", "cat8000v", "iosv")


def _second_platform_intent(root, platform):
    return root / "scripts" / "lab" / f"intent-second-platform-{platform}.yaml"


def test_labctl_r3_link_lines_for_r1(root):
    labctl = _load_script(root, "labctl.py")
    assert labctl.R3_LINK == {"interface": "Ethernet0/3", "R1": "10.1.3.1/24", "R3": "10.1.3.3"}
    assert (labctl.R3_RID, labctl.R3_ASN) == ("3.3.3.3", 65003)
    assert labctl.r3_link_lines() == [
        "interface Ethernet0/3",
        "ip address 10.1.3.1 255.255.255.0",
        "ip ospf hello-interval 1",
        "no shutdown",
        "router ospf 1",
        "network 10.1.3.0 0.0.0.255 area 0",
        "router bgp 65001",
        "neighbor 10.1.3.3 remote-as 65003",
        "neighbor 10.1.3.3 timers 3 9",
        "address-family ipv4",
        "neighbor 10.1.3.3 activate",
        "neighbor 10.1.3.3 soft-reconfiguration inbound",
        "exit-address-family",
    ]


def test_second_platform_nxos_intent_names_both_ends_of_the_link_in_nxos_strings(root):
    intent = load_intent(_second_platform_intent(root, "nxosv9000"))
    assert intent.intent_id == "devnet-default-lab-second-platform"
    assert intent.devices == ("R1", "R3")
    adjacencies = [
        (a.device, a.protocol, a.neighbor, a.interface, a.vrf, a.remote_as) for a in intent.adjacencies
    ]
    assert adjacencies == [
        ("R1", "ospf", "3.3.3.3", "Ethernet0/3", "", None),
        ("R3", "ospf", "1.1.1.1", "Ethernet1/1", "", None),
        ("R1", "bgp", "10.1.3.3", "", "default", 65003),
        ("R3", "bgp", "10.1.3.1", "", "default", 65001),
    ]
    assert [(r.device, r.vrf, r.prefix, r.protocol) for r in intent.routes] == [
        ("R1", "default", "10.1.3.0/24", "connected"),
        ("R1", "default", "3.3.3.3/32", "ospf"),
        ("R1", "default", "172.16.3.0/24", "bgp"),
        ("R3", "default", "10.1.3.0/24", "direct"),
        ("R3", "default", "1.1.1.0/24", "ospf"),
        ("R3", "default", "10.10.10.0/24", "bgp"),
    ]
    assert [(i.device, i.name) for i in intent.interfaces] == [("R1", "Ethernet0/3"), ("R3", "Ethernet1/1")]
    required = {rule.device: rule.lines for rule in intent.must_include}
    # IOS writes no `no shutdown` line, so the rules never require one.
    assert required == {
        "R1": (
            "ip address 10.1.3.1 255.255.255.0",
            "network 10.1.3.0 0.0.0.255 area 0",
            "neighbor 10.1.3.3 remote-as 65003",
            "neighbor 10.1.3.3 timers 3 9",
        ),
        "R3": ("router bgp 65003",),
    }
    assert intent.must_absent == ()
    # R1's required lines are what setup-r3-link sends, as IOS lists them.
    labctl = _load_script(root, "labctl.py")
    assert set(required["R1"]) <= set(labctl.r3_link_lines())


def test_the_three_draft_intents_differ_only_in_r3s_interface_and_its_connected_route_string(root):
    """One draft per platform, R3's first data interface taken from cml_lab.py's platform table:
    NX-OS writes a connected route as `direct`, IOS as `connected`."""
    table = _load_script(root, "cml_lab.py").PLATFORM_TABLE
    assert tuple(table) == PLATFORMS
    nxos = yaml.safe_load(_second_platform_intent(root, "nxosv9000").read_text(encoding="utf-8"))
    assert table["nxosv9000"].first_interface == "Ethernet1/1"
    for platform in ("cat8000v", "iosv"):
        other = yaml.safe_load(_second_platform_intent(root, platform).read_text(encoding="utf-8"))
        interface = table[platform].first_interface
        assert other != nxos
        as_ios = (
            json.dumps(nxos).replace('"Ethernet1/1"', f'"{interface}"').replace('"direct"', '"connected"')
        )
        assert json.loads(as_ios) == other
        load_intent(_second_platform_intent(root, platform))  # and it is a valid intent


# How each platform's capture writes R3's records, as the prediction below builds them through
# ncv's adapter: NX-OS as Genie's NX-OS test data does (lowercase BGP states, `direct`, and
# interface records that carry no status), IOS as the IOS XE captures do.
R3_FORMS = {
    "nxosv9000": {
        "established": "established",
        "down": "active",
        "connected": "direct",
        "more_interfaces": {
            "Ethernet1/2": {"vrf": "default"},
            "Ethernet1/3": {"switchport_enable": True, "switchport_mode": "access", "access_vlan": 1},
            "Mgmt0": {"oper_status": "up", "enabled": True, "vrf": "management", "counters": {"in_pkts": 9}},
            "Null0": {"vrf": "default"},
        },
    },
    "cat8000v": {
        "established": "Established",
        "down": "Active",
        "connected": "connected",
        "more_interfaces": {},
    },
    "iosv": {"established": "Established", "down": "Active", "connected": "connected", "more_interfaces": {}},
}


def _genie_ospf_on(interfaces):
    """`learn ospf` as Genie shapes it on IOS XE and NX-OS alike: {interface: {router id: state}}
    in area 0 of instance 1."""
    area = {
        "interfaces": {
            name: {"neighbors": {nbr: {"state": state} for nbr, state in neighbors.items()}}
            for name, neighbors in interfaces.items()
        }
    }
    return {
        "vrf": {"default": {"address_family": {"ipv4": {"instance": {"1": {"areas": {"0.0.0.0": area}}}}}}}
    }


def _genie_bgp_peers(peers):
    """`learn bgp` as Genie shapes it: {peer: (remote AS, session state)} in the default VRF."""
    neighbors = {peer: {"remote_as": asn, "session_state": state} for peer, (asn, state) in peers.items()}
    return {"instance": {"default": {"vrf": {"default": {"neighbor": neighbors}}}}}


def _genie_routes(table):
    """`learn routing` as Genie shapes it: {prefix: source protocol} in the default VRF."""
    routes = {prefix: {"source_protocol": protocol} for prefix, protocol in table.items()}
    return {"vrf": {"default": {"address_family": {"ipv4": {"routes": routes}}}}}


def _port(status):
    return {"oper_status": status, "enabled": True, "counters": {"in_errors": 0, "in_crc_errors": 0}}


def _write_r3_snapshot(path, platform, interface, linked=True, r3_connected=None):
    """The second-platform run's capture of R1 and R3 (R3's first data interface `interface`),
    every section built through ncv's adapter from Genie's shapes. `linked` False is the post
    state: R1 Ethernet0/3 shut, so R1 has dropped R3 and R3 has given up on R1, each losing what
    it learned; R3's own interface stays up and keeps its connected route. `r3_connected`
    overrides the protocol string R3 reports for that route."""
    form = R3_FORMS[platform]
    r1_ospf = {"Ethernet0/1": {"2.2.2.2": "full"}, "Ethernet0/3": {"3.3.3.3": "full"} if linked else {}}
    r3_ospf = {interface: {"1.1.1.1": "full"} if linked else {}}
    r1_bgp = {"1.1.1.2": (65002, "Established"), "10.1.3.3": (65003, "Established" if linked else "Idle")}
    r3_bgp = {"10.1.3.1": (65001, form["established"] if linked else form["down"])}
    r1_routes = {"1.1.1.0/24": "connected", "20.20.20.0/24": "static"}
    r3_routes = {
        "10.1.3.0/24": r3_connected or form["connected"],
        "3.3.3.3/32": form["connected"],
        "172.16.3.0/24": form["connected"],
    }
    if linked:
        r1_routes.update({"10.1.3.0/24": "connected", "3.3.3.3/32": "ospf", "172.16.3.0/24": "bgp"})
        r3_routes.update({"1.1.1.0/24": "ospf", "10.10.10.0/24": "bgp"})
    r1_ports = {"Ethernet0/1": _port("up"), "Ethernet0/3": _port("up" if linked else "administratively down")}
    r3_ports = {interface: _port("up"), **form["more_interfaces"]}
    learned = {
        "R1": {"ospf": r1_ospf, "bgp": r1_bgp, "routing": r1_routes, "interface": r1_ports},
        "R3": {"ospf": r3_ospf, "bgp": r3_bgp, "routing": r3_routes, "interface": r3_ports},
    }
    shapes = {"ospf": _genie_ospf_on, "bgp": _genie_bgp_peers, "routing": _genie_routes, "interface": dict}
    sections = {feature: {} for feature in shapes}
    for device, features in learned.items():
        for feature, data in features.items():
            sections[feature].update(normalize_learn(device, feature, shapes[feature](data)))
    r1_config = _r3_run_config([] if linked else [" shutdown"])
    sections["config"] = {
        "R1": {"running": "\n".join(r1_config) + "\n"},
        "R3": {"running": "hostname R3\nfeature bgp\nrouter bgp 65003\n  router-id 3.3.3.3\n"},
    }
    path.mkdir()
    for name, data in sections.items():
        (path / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.mark.parametrize("platform", PLATFORMS)
def test_second_platform_run_prediction_on_synthetic_snapshots(root, tmp_path, platform):
    """One link shut from R1's end, seen from both: R1 drops OSPF and BGP with its interface and
    loses the link's connected route with what it learned from R3; R3, whose interface stays up,
    gives up on R1 on its own timers and loses what it learned from R1, but keeps its connected
    route. The nine findings in expect-second-platform-<platform>.txt, the same for every
    platform; the restored capture is compliant again."""
    intent = _second_platform_intent(root, platform)
    interface = _load_script(root, "cml_lab.py").PLATFORM_TABLE[platform].first_interface
    pre, post, restored = tmp_path / "pre", tmp_path / "post", tmp_path / "restored"
    _write_r3_snapshot(pre, platform, interface)
    _write_r3_snapshot(post, platform, interface, linked=False)
    _write_r3_snapshot(restored, platform, interface)
    expected = _expected(root, f"expect-second-platform-{platform}.txt")
    assert len(expected) == 9
    assert _expected(root, "expect-second-platform-nxosv9000.txt") == expected
    assert _bgp_diff(root, tmp_path, pre, pre, "baseline", intent) == (0, [])
    assert _bgp_diff(root, tmp_path, pre, post, "change", intent) == (1, expected)
    report = json.loads((tmp_path / "report-change" / "report.json").read_text(encoding="utf-8"))
    after = {(f["device"], f["path"]): f["after"] for f in report["findings"]}
    assert after[("R1", "ospf.neighbors.3.3.3.3")] is None
    assert after[("R3", "bgp.vrfs.default.neighbors.10.1.3.1")] == {
        "state": R3_FORMS[platform]["down"],
        "remote_as": 65001,
    }
    assert _bgp_diff(root, tmp_path, pre, restored, "restored", intent) == (0, [])
    if platform == "nxosv9000":  # the records with no status are kept, as unknown
        captured = json.loads((pre / "interface.json").read_text(encoding="utf-8"))["R3"]["interfaces"]
        assert captured["Ethernet1/2"] == {"oper_status": None, "in_errors": None, "crc": None}
        assert captured["Ethernet1/1"] == {"oper_status": "up", "in_errors": 0, "crc": 0}


def test_a_capture_whose_r3_says_connected_fails_the_nxos_intents_no_change_check(root, tmp_path):
    """The platform's own strings are part of the intent: an R3 reporting its connected route as
    IOS does gives one V_ROUTE against the NX-OS draft, which is how a wrong draft shows up."""
    intent = _second_platform_intent(root, "nxosv9000")
    pre = tmp_path / "pre"
    _write_r3_snapshot(pre, "nxosv9000", "Ethernet1/1", r3_connected="connected")
    code, findings = _bgp_diff(root, tmp_path, pre, pre, "baseline", intent)
    assert (code, findings) == (1, [("V_ROUTE", "R3", "routing.vrfs.default.routes.10.1.3.0/24.protocol")])
    report = json.loads((tmp_path / "report-baseline" / "report.json").read_text(encoding="utf-8"))
    assert "protocol is connected, intent direct" in report["findings"][0]["why"]


def _password_values(node):
    """Every password value anywhere in a parsed testbed."""
    if isinstance(node, dict):
        found = [v for k, v in node.items() if k == "password"]
        return found + [v for item in node.values() for v in _password_values(item)]
    if isinstance(node, list):
        return [v for item in node for v in _password_values(item)]
    return []


def test_the_r3_testbed_example_adds_r3_through_the_console_server_and_holds_no_password(root):
    text = (root / "testbeds" / "cml-console-r3.yaml.example").read_text(encoding="utf-8")
    testbed = yaml.safe_load(text)
    console = yaml.safe_load((root / "testbeds" / "cml-console.yaml.example").read_text(encoding="utf-8"))
    devices = testbed["devices"]
    assert list(devices) == ["R1", "R2", "R3"]
    assert {name: devices[name] for name in ("R1", "R2")} == console["devices"]
    assert testbed["testbed"]["credentials"] == console["testbed"]["credentials"]
    r3 = devices["R3"]
    cli = r3["connections"]["cli"]
    assert (r3["os"], r3["platform"]) == ("nxos", "n9k")
    assert r3["os"] == _load_script(root, "cml_lab.py").PLATFORM_TABLE["nxosv9000"].os
    assert cli["command"].endswith('10.10.20.161 "open /default-lab/R3/0"')
    # Next to `command`, where Unicon reads it; under `arguments` it is silently ignored.
    assert cli["login_creds"] == ["default", "nxos"]
    assert cli["settings"] == {"SENDLINE_AFTER_CRED": "default"}
    header = text.split("\ntestbed:")[0]
    assert "`SENDLINE_AFTER_CRED: default`" in header  # every setting R3 adds is explained there
    assert cli["arguments"] == {"learn_hostname": True, "prompt_recovery": True, "connection_timeout": 120}
    assert r3["credentials"] == {"nxos": {"username": "admin", "password": "%ENV{NCV_LAB_PASS}"}}
    passwords = _password_values(testbed)
    assert len(passwords) == 3
    assert all(re.fullmatch(r"%ENV\{NCV_\w+\}", value) for value in passwords)
    assert "NCV_SSH_PASS" not in text


def test_the_second_platform_run_checks_its_platform_first_and_adds_r3_after_the_reset(root):
    text = (root / "scripts" / "lab" / "run-second-platform.sh").read_text(encoding="utf-8")
    assert "Prepared, not run yet." in text.splitlines()[1]
    steps = [
        '. "$here/_lib.sh"',
        "case ${1:-} in -h | --help) lab_print_header; exit 0 ;; esac",
        'platform-os "$platform"',
        'export NCV_TESTBED="${NCV_TESTBED:-testbeds/lab-r3.yaml}"',
        'lab_r3_testbed_fits "$platform" "$r3_os" || exit 2',
        "lab_init second-platform",
        "\nlab_reset\n",
        'cml add-r3 "$platform"',
        "ctl setup-ospf ",
        "ctl setup-bgp ",
        "ctl setup-r3-link ",
        "ctl wait-r3-up 600 ",
        "snap pre ",
        'compare pre pre baseline; rc=$?\nexpect_exit baseline 0 "$rc"',
        "ctl r3-shut ",
        "ctl wait-r3-down 60 ",
        "sleep 15\n",
        "snap post ",
        'compare pre post change; expect_exit change 1 "$?"',
        'expect_findings change "$out-change" "scripts/lab/expect-second-platform-$platform.txt"',
        "ctl r3-noshut ",
        "ctl wait-r3-up 300 ",
        "snap restored ",
        'compare pre restored restored; expect_exit restored 0 "$?"',
        "\nlab_finish\n",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "features=ospf,bgp,routing,interface\n" in text
    assert "intent=scripts/lab/intent-second-platform-$platform.yaml\n" in text
    assert "correct $intent from $run/pre" in text
    assert "cml_lab.py remove-r3" in text
    assert 'remove-r3"' not in text and "cml remove-r3" not in text  # it leaves R3 in the lab
    assert "cap_start" not in text  # cml_capture.py captures the R1-R2 link only
    for platform in PLATFORMS:
        assert _second_platform_intent(root, platform).is_file()
        assert (root / "scripts" / "lab" / f"expect-second-platform-{platform}.txt").is_file()


# run-session.sh runs the prepared runs after asking for the logins once. Its `case` is the one
# place a session name meets its script, so a run added here and forgotten there would never run.

BRANCH_RUNS = (
    "probe.sh",
    "run-ospf-deadtimer.sh",
    "run-ibgp.sh",
    "run-bgp-vrf.sh",
    "run-ssh-path.sh",
    "run-second-platform.sh",
)


def _session_map(root):
    """{session name pattern: script} from session_script's case in run-session.sh."""
    text = (root / "scripts" / "lab" / "run-session.sh").read_text(encoding="utf-8")
    body = text[text.index("session_script() {") :]
    body = body[: body.index("\n}\n")]
    return dict(re.findall(r'^\s+([\w:*-]+)\) echo "([\w.-]+)', body, re.M))


def test_every_session_name_names_a_script_that_exists_and_every_prepared_run_has_a_name(root):
    lab = root / "scripts" / "lab"
    names = _session_map(root)
    assert set(names) == {
        "probe",
        "ospf-deadtimer",
        "ibgp",
        "bgp-vrf",
        "ssh-path",
        "second-platform:*",
        "reset",
        "remove-r3",
    }
    assert (names["reset"], names["remove-r3"]) == ("labctl.py", "cml_lab.py")
    for script in names.values():
        assert (lab / script).is_file(), script
    sourcing = {
        path.name for path in lab.glob("*.sh") if '\n. "$here/_lib.sh"\n' in path.read_text(encoding="utf-8")
    }
    assert sourcing - {"run-session.sh"} == set(BRANCH_RUNS)  # a new run script must be added here too
    assert set(BRANCH_RUNS) <= set(names.values())
    for name, script in names.items():
        if script.endswith(".sh"):  # the session finds each run's log by the name it gives lab_init
            run_name = name.removesuffix(":*")
            assert f"\nlab_init {run_name}\n" in (lab / script).read_text(encoding="utf-8"), script


def test_each_run_script_that_takes_no_arguments_says_so_before_anything_else(root):
    """So `-h` prints the header instead of asking for the logins and resetting the routers."""
    lab = root / "scripts" / "lab"
    start = '\nset -uo pipefail\nhere=$(cd "$(dirname "$0")" && pwd)\n. "$here/_lib.sh"\n'
    start += 'lab_takes_no_arguments "$@"\n'
    for script in ("probe.sh", "run-ospf-deadtimer.sh", "run-ibgp.sh", "run-bgp-vrf.sh", "run-ssh-path.sh"):
        text = (lab / script).read_text(encoding="utf-8")
        assert text[text.index("\nset -uo pipefail\n") :].startswith(start), script


def test_the_session_defaults_to_the_runs_that_need_only_the_three_logins_and_never_traces(root):
    text = (root / "scripts" / "lab" / "run-session.sh").read_text(encoding="utf-8")
    assert "names=(probe ospf-deadtimer ibgp bgp-vrf reset)\n" in text
    assert "set -x" not in text
    order = [
        'session_script "$name" >/dev/null',
        '"$here/cml_lab.py" platform-os',
        "\nlab_vpn_up\n",
        "\nlab_logins\n",
        "lab_ssh_login",
        '"$here/cml_lab.py" check-login',
        "trap on_interrupt INT",
        'NCV_STAMP="$stamp-$n" bash "$here/$script"',
    ]
    positions = [text.index(step) for step in order]
    assert positions == sorted(positions)
    assert re.findall(r"\$\{?NCV_\w+_PASS", text) == []  # no line ever expands a password


def test_every_lab_script_has_a_readme_row_and_every_row_names_a_file(root):
    lab = root / "scripts" / "lab"
    readme = (lab / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("| Script | What it does |") :].split("\n\n")[0]
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    named = [name for row in rows for name in re.findall(r"`([^`]+)`", row.split(" | ")[0])]
    for name in named:
        assert list(lab.glob(name.replace("<platform>", "*"))), name
    scripts = {path.name for path in lab.iterdir() if path.suffix in (".sh", ".py")}
    assert scripts <= set(named), sorted(scripts - set(named))


def _capturing_scripts(lab):
    """Every shell script here that takes a capture, by name: through _lib.sh's `snap`, through a
    `snap` of its own, or with `ncv snapshot` directly."""
    texts = {path.name: path.read_text(encoding="utf-8") for path in lab.glob("*.sh")}
    texts.pop("_lib.sh")
    return {name: text for name, text in texts.items() if re.search(r"^snap |ncv snapshot", text, re.M)}


def test_the_readme_names_the_runs_that_can_be_pointed_at_the_ssh_testbed(root):
    """Only _lib.sh's `snap` captures through NCV_TESTBED, so only a run that sources _lib.sh and
    never sets NCV_TESTBED itself can capture over SSH. The SSH section names exactly those, and
    names every other capturing script as one that keeps its own testbed."""
    lab = root / "scripts" / "lab"
    scripts = _capturing_scripts(lab)
    through_lib = {
        name for name, text in scripts.items() if '. "$here/_lib.sh"' in text and "NCV_TESTBED=" not in text
    }
    assert through_lib == {"run-ospf-deadtimer.sh", "run-ibgp.sh", "run-bgp-vrf.sh"}
    readme = (lab / "README.md").read_text(encoding="utf-8")
    section = " ".join(readme[readme.index("## The SSH path") :].split("\nThe steps:")[0].split())
    pointable = section[section.index("With that file in place") : section.index("No run has gone over SSH")]
    others = section[section.index("The others use their own testbed") :]
    assert set(re.findall(r"`(run-[\w-]+\.sh)`", pointable)) == through_lib
    assert set(re.findall(r"`([\w-]+\.sh)`", others)) == set(scripts) - through_lib
    for name in set(scripts) - through_lib:
        text = scripts[name]
        assert "NCV_TESTBED=" in text or "--testbed testbeds/lab.yaml" in text, name


PREDICTED_TABLES = [
    ("## The OSPF dead-timer run", "expect-ospf-deadtimer.txt"),
    ("## The iBGP run", "expect-ibgp.txt"),
    ("## The BGP VRF run", "expect-bgp-vrf.txt"),
    ("## The second-platform run", "expect-second-platform-iosv.txt"),
]
COUNT_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
ADDRESS = r"\d+\.\d+\.\d+\.\d+(?:/\d+)?"


@pytest.mark.parametrize(("title", "name"), PREDICTED_TABLES)
def test_each_readme_prediction_table_names_the_findings_in_its_expect_file(root, title, name):
    """The README's table of a prepared run is the same prediction as the expected file the run
    checks its report against: the change row names every policy, device, and address in the
    file and no other address, its count is the file's, and the other two rows are clean."""
    readme = (root / "scripts" / "lab" / "README.md").read_text(encoding="utf-8")
    section = readme[readme.index(title) :]
    section = section[: section.index("\n## ", 1)]
    table = section[section.index("Predicted findings, pinned on synthetic snapshots") :]
    rows = {
        line.split(" | ")[0]: line.split(" | ")[1:]
        for line in table.splitlines()
        if line.startswith("| pre vs")
    }
    assert rows["| pre vs pre"] == ["0", "none |"]
    assert rows["| pre vs restored"] == ["0", "none |"]
    ((exit_code, cell),) = [value for key, value in rows.items() if key.startswith("| pre vs post")]
    assert exit_code == "1"
    expected = _expected(root, name)
    assert set(re.findall(ADDRESS, cell)) == {
        re.search(ADDRESS + "$", path).group() for _, _, path in expected
    }
    for policy, device, _ in expected:
        assert f"`{policy}`" in cell and device in cell, (policy, device)
    count = re.match(r"(\w+)[:,]", cell)  # "nine: ...", "five, all in vrf NCV: ..."
    if count:
        assert COUNT_WORDS.get(count.group(1)) == len(expected), count.group(1)


def _indented_blocks(text):
    """The README's indented code blocks, each as its lines with the four-space indent removed."""
    blocks, current = [], []
    for line in [*text.splitlines(), ""]:
        if line.startswith("    ") and line.strip():
            current.append(line[4:])
        elif current:
            blocks.append(current)
            current = []
    return blocks


def test_each_configuration_block_in_the_readme_is_what_its_builder_sends(root):
    """Each block that shows what a command sends is the builder's output, indented the way IOS
    shows it (less the `exit` that only leaves the ACL's mode); R3's NX-OS day-0 configuration is
    exactly what add-r3 echoes."""
    labctl = _load_script(root, "labctl.py")
    cml = _load_script(root, "cml_lab.py")
    blocks = _indented_blocks((root / "scripts" / "lab" / "README.md").read_text(encoding="utf-8"))
    stripped = [[line.strip() for line in block] for block in blocks]
    for lines in (
        labctl.bgp_block_lines(),
        labctl.ospf_block_lines(),
        labctl.ibgp_setup_lines("R1"),
        labctl.vrf_setup_lines("R1"),
        labctl.r3_link_lines(),
    ):
        assert [line for line in lines if line != "exit"] in stripped, lines[0]
    day0 = cml.redact(cml.day0_config("nxosv9000", "not-a-real-password"), "not-a-real-password")
    assert day0.splitlines() in blocks
