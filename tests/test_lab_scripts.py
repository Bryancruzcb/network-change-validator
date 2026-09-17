"""The lab-side scripts: the sanitizer that produced the published evidence, and the BGP run
that is prepared but not yet run.

scripts/lab/sanitize_capture.py is what removed the passwords and certificate bodies from
fixtures/lab-2026-09-12 before it was committed. The first tests pin its rules on a synthetic
config and check that every published config.json is its own fixed point, so the evidence
in the repository is exactly what those rules leave behind.

scripts/lab/labctl.py reads router show output to know when a change has taken, and
scripts/lab/intent-bgp.yaml is the intent the BGP run will check against. The rest pin the
parsers on sample output and the findings the planned change should produce on synthetic
snapshots shaped like the recorded captures. That is a prediction, not evidence: no BGP
capture exists until the run happens and is recorded.
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
    configs = sorted((root / "fixtures" / "lab-2026-09-12").rglob("config.json"))
    assert len(configs) == 6
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


def test_bgp_draft_intent_names_both_peers(root):
    intent = load_intent(root / "scripts" / "lab" / "intent-bgp.yaml")
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


def _write_snapshot(path, states, r1_extra=()):
    """A snapshot shaped like the recorded captures, with the BGP states and R1 config given."""
    path.mkdir()
    routes = {
        "R1": {"20.20.20.0/24": {"protocol": "static"}, "1.1.1.0/24": {"protocol": "connected"}},
        "R2": {"10.10.10.0/24": {"protocol": "static"}, "1.1.1.0/24": {"protocol": "connected"}},
    }
    peers = {"R1": ("1.1.1.2", 65002), "R2": ("1.1.1.1", 65001)}
    configs = {"R1": R1_CONFIG + list(r1_extra), "R2": R2_CONFIG}
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


def _bgp_diff(root, tmp_path, before, after, label):
    report = tmp_path / f"report-{label}"
    intent = root / "scripts" / "lab" / "intent-bgp.yaml"
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
