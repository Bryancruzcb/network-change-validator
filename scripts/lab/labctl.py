"""Operator-side actions on the DevNet CML default-lab, deliberately outside ncv.

ncv never pushes configuration. These are the hands that make the one planned change in
the lab, so the captures around it have something to catch. Isolated lab only.

Usage, with the logins in the NCV_* environment (the run-*.sh scripts prompt for them):
  labctl.py setup-ospf                router ospf 1 on R1 and R2, area 0 on the R1-R2 link
  labctl.py shut | noshut             shutdown / no shutdown on R1 Ethernet0/1
  labctl.py wait-full [seconds]       poll until both OSPF neighbors are FULL (default 120)
  labctl.py wait-gone [seconds]       poll until both OSPF neighbor entries are gone
  labctl.py setup-bgp                 eBGP R1 (AS 65001) to R2 (AS 65002) over the 1.1.1.0/24 link
  labctl.py bgp-shut | bgp-noshut     neighbor 1.1.1.2 shutdown / no shutdown on R1
  labctl.py wait-bgp-up [seconds]     poll until both BGP sessions are Established
  labctl.py wait-bgp-down [seconds]   poll until neither BGP session is Established

The testbed is testbeds/lab.yaml under the repository root, wherever this is run from.
Genie is imported only when a command runs, so the show-output parsers here can be tested
without the lab extra installed.
"""

import sys
import time
from pathlib import Path

TESTBED = Path(__file__).resolve().parents[2] / "testbeds" / "lab.yaml"
ROUTER_IDS = {"R1": "1.1.1.1", "R2": "2.2.2.2"}
OSPF_PEERS = {"R1": "2.2.2.2", "R2": "1.1.1.1"}
# eBGP over the direct link, each router advertising its own LAN. The static routes the lab
# ships with outrank the learned prefixes, so the routing table does not change with the session.
BGP = {
    "R1": {"asn": 65001, "peer": "1.1.1.2", "peer_asn": 65002, "network": "10.10.10.0"},
    "R2": {"asn": 65002, "peer": "1.1.1.1", "peer_asn": 65001, "network": "20.20.20.0"},
}
USAGE = (
    "usage: labctl.py setup-ospf | shut | noshut | wait-full [seconds] | wait-gone [seconds]"
    " | setup-bgp | bgp-shut | bgp-noshut | wait-bgp-up [seconds] | wait-bgp-down [seconds]"
)


def ospf_neighbor_state(output: str, peer: str):
    """From `show ip ospf neighbor`: True if the peer is FULL, False if listed but not FULL,
    None if not listed."""
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == peer:
            return "FULL" in line
    return None


def bgp_session_state(output: str, peer: str):
    """From `show bgp ipv4 unicast summary`: True if the session is Established (the last
    column is then a prefix count), False if listed in any other state such as Idle, Active,
    or Idle (Admin), None if not listed."""
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == peer:
            return fields[-1].isdigit()
    return None


def ospf_check(dev, name):
    return ospf_neighbor_state(dev.execute("show ip ospf neighbor"), OSPF_PEERS[name])


def bgp_check(dev, name):
    return bgp_session_state(dev.execute("show bgp ipv4 unicast summary"), BGP[name]["peer"])


def connect(tb, name):
    dev = tb.devices[name]
    dev.connect(log_stdout=False, init_exec_commands=[], init_config_commands=[])
    return dev


def configure(tb, name, lines, show=None):
    dev = connect(tb, name)
    try:
        dev.configure(lines)
        print(f"{name}: " + "; ".join(lines))
        if show:
            print(dev.execute(show))
    finally:
        dev.disconnect()


def wait(tb, names, check, want, seconds, label) -> int:
    """Poll `check` on every named device every 5 s until all results satisfy `want`."""
    devs = {}
    try:
        for name in names:
            devs[name] = connect(tb, name)
        deadline = time.time() + seconds
        while True:
            states = {name: check(dev, name) for name, dev in devs.items()}
            print(time.strftime("%H:%M:%S"), states, flush=True)
            if all(want(s) for s in states.values()):
                return 0
            if time.time() > deadline:
                print(f"timed out waiting for {label}")
                return 1
            time.sleep(5)
    finally:
        for dev in devs.values():
            dev.disconnect()


def main() -> int:
    if len(sys.argv) < 2:
        print(USAGE)
        return 2
    cmd = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    from genie.testbed import load  # the lab extra, needed only past this point

    tb = load(str(TESTBED))
    if cmd == "setup-ospf":
        for name, rid in ROUTER_IDS.items():
            configure(tb, name, ["router ospf 1", f"router-id {rid}", "network 1.1.1.0 0.0.0.255 area 0"])
        return 0
    if cmd in ("shut", "noshut"):
        line = "shutdown" if cmd == "shut" else "no shutdown"
        configure(tb, "R1", ["interface Ethernet0/1", line], show="show ip interface brief")
        return 0
    if cmd == "wait-full":
        return wait(tb, OSPF_PEERS, ospf_check, lambda s: s is True, seconds, "both OSPF neighbors FULL")
    if cmd == "wait-gone":
        return wait(tb, OSPF_PEERS, ospf_check, lambda s: s is None, seconds, "the OSPF neighbors to clear")
    if cmd == "setup-bgp":
        for name, cfg in BGP.items():
            configure(
                tb,
                name,
                [
                    f"router bgp {cfg['asn']}",
                    f"bgp router-id {ROUTER_IDS[name]}",
                    "bgp log-neighbor-changes",
                    f"neighbor {cfg['peer']} remote-as {cfg['peer_asn']}",
                    "address-family ipv4",
                    f"network {cfg['network']} mask 255.255.255.0",
                    f"neighbor {cfg['peer']} activate",
                    # lets Genie's learn read received-routes instead of an error line
                    f"neighbor {cfg['peer']} soft-reconfiguration inbound",
                    "exit-address-family",
                ],
            )
        return 0
    if cmd in ("bgp-shut", "bgp-noshut"):
        line = ("" if cmd == "bgp-shut" else "no ") + f"neighbor {BGP['R1']['peer']} shutdown"
        configure(tb, "R1", [f"router bgp {BGP['R1']['asn']}", line], show="show bgp ipv4 unicast summary")
        return 0
    if cmd == "wait-bgp-up":
        return wait(tb, BGP, bgp_check, lambda s: s is True, seconds, "both BGP sessions Established")
    if cmd == "wait-bgp-down":
        return wait(
            tb, BGP, bgp_check, lambda s: s is not True, seconds, "both BGP sessions to leave Established"
        )
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
