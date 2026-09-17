"""Operator-side actions on the DevNet CML default-lab, deliberately outside ncv.

ncv never pushes configuration. These are the hands that make the one planned change in
the lab, so the captures around it have something to catch. Isolated lab only.

Usage, with the logins in the NCV_* environment (the run-*.sh scripts prompt for them):
  labctl.py setup-ospf              router ospf 1 on R1 and R2, area 0 on the R1-R2 link
  labctl.py shut | noshut           shutdown / no shutdown on R1 Ethernet0/1
  labctl.py wait-full [seconds]     poll until both OSPF neighbors are FULL (default 120)
  labctl.py wait-gone [seconds]     poll until both neighbor entries are gone (default 120)

The testbed is testbeds/lab.yaml under the repository root, wherever this is run from.
"""

import sys
import time
from pathlib import Path

from genie.testbed import load

TESTBED = Path(__file__).resolve().parents[2] / "testbeds" / "lab.yaml"
ROUTER_IDS = {"R1": "1.1.1.1", "R2": "2.2.2.2"}
PEERS = {"R1": "2.2.2.2", "R2": "1.1.1.1"}
USAGE = "usage: labctl.py setup-ospf | shut | noshut | wait-full [seconds] | wait-gone [seconds]"


def connect(tb, name):
    dev = tb.devices[name]
    dev.connect(log_stdout=False, init_exec_commands=[], init_config_commands=[])
    return dev


def neighbor_state(dev, peer):
    """True if the peer is FULL, False if listed but not FULL, None if not listed."""
    for line in dev.execute("show ip ospf neighbor").splitlines():
        fields = line.split()
        if fields and fields[0] == peer:
            return "FULL" in line
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(USAGE)
        return 2
    cmd = sys.argv[1]
    tb = load(str(TESTBED))
    if cmd == "setup-ospf":
        for name, rid in ROUTER_IDS.items():
            dev = connect(tb, name)
            try:
                dev.configure(["router ospf 1", f"router-id {rid}", "network 1.1.1.0 0.0.0.255 area 0"])
                print(f"{name}: router ospf 1, router-id {rid}, network 1.1.1.0/24 area 0")
            finally:
                dev.disconnect()
        return 0
    if cmd in ("shut", "noshut"):
        line = "shutdown" if cmd == "shut" else "no shutdown"
        dev = connect(tb, "R1")
        try:
            dev.configure(["interface Ethernet0/1", line])
            print(f"R1 Ethernet0/1: {line}")
            print(dev.execute("show ip interface brief"))
        finally:
            dev.disconnect()
        return 0
    if cmd in ("wait-full", "wait-gone"):
        want_full = cmd == "wait-full"
        seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        deadline = time.time() + seconds
        devs = {}
        try:
            for name in PEERS:
                devs[name] = connect(tb, name)
            while True:
                states = {name: neighbor_state(dev, PEERS[name]) for name, dev in devs.items()}
                print(time.strftime("%H:%M:%S"), states, flush=True)
                if want_full and all(s is True for s in states.values()):
                    return 0
                if not want_full and all(s is None for s in states.values()):
                    return 0
                if time.time() > deadline:
                    print("timed out waiting for", "FULL" if want_full else "the neighbors to clear")
                    return 1
                time.sleep(5)
        finally:
            for dev in devs.values():
                dev.disconnect()
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
