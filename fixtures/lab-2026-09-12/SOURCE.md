# Lab evidence, 2026-09-12

Real captures from a Cisco DevNet sandbox, sanitized for publishing. The synthetic
fixtures in `fixtures/pre` and `fixtures/post` are unchanged and remain the demo.

## Environment

- Cisco DevNet "Cisco Modeling Labs" reservable sandbox: CML 2.7.2 with its preloaded
  `default-lab` topology.
- Captured devices: R1 and R2, both IOL XE running IOS XE 17.15, joined by a direct link
  (R1 Ethernet0/1 1.1.1.1/24 to R2 Ethernet0/1 1.1.1.2/24). Each has a static route to
  the other's LAN: R1 to 20.20.20.0/24, R2 to 10.10.10.0/24.
- Collector: `ncv snapshot --testbed ... --i-am-in-a-lab` from WSL Ubuntu with pyATS and
  Genie 26.8 on Python 3.12, running ncv at commit `36fac86` (on `main` through PR #5).
- Access path: the routers' management addresses did not answer over the sandbox VPN, so
  each router was reached through the CML console server with
  `ssh -tt <cml user>@<cml> "open /default-lab/<node>/0"`. docs/LIVE.md describes the
  testbed for that path.

## Route run (`routes/`), 22:55 to 22:58 PT

1. `pre`, then `ncv diff pre pre` against `intent-routes.yaml`: exit 0, no findings.
2. The one change, applied by an operator script outside ncv (kept as
   `scripts/lab/run-lab.sh`): `shutdown` on R1 Ethernet0/1.
3. `post`, then `ncv diff pre post`: exit 1 with two findings, both on R1, for the missing
   routes 1.1.1.0/24 and 20.20.20.0/24. R2's end of the link stayed up in the simulation,
   so R2's route and interface rules stayed compliant.
4. `no shutdown` on the same interface, then `restored` and `ncv diff pre restored`:
   exit 0, no findings.

`tests/test_lab_evidence.py` replays these comparisons on every commit.

## OSPF run (`ospf/`), 23:26 to 23:33 PT

The same lab, with OSPF added so the adjacency check had something to watch.

1. Operator setup outside ncv (`scripts/lab/labctl.py setup-ospf`, driven by
   `scripts/lab/run-ospf.sh`): `router ospf 1` on R1 and R2 with router IDs pinned to
   1.1.1.1 and 2.2.2.2, and `network 1.1.1.0 0.0.0.255 area 0`. Both neighbors reached
   FULL about 30 seconds later.
2. `pre` with `--features ospf,routing,interface`, then `ncv diff pre pre` against
   `intent-ospf.yaml`: exit 0, no findings.
3. `shutdown` on R1 Ethernet0/1. R1 dropped its neighbor at once, while R2 kept 1.1.1.1
   until its dead timer expired about 35 seconds later, so the post capture waited for
   both entries to clear.
4. `post`, then `ncv diff pre post`: exit 1 with four findings, `V_ADJ` on R1 for neighbor
   2.2.2.2 and on R2 for neighbor 1.1.1.1, plus the same two missing R1 routes as the
   route run.
5. `no shutdown`, both neighbors FULL again, then `restored` and `ncv diff pre restored`:
   exit 0, no findings.

The tests replay these comparisons too.

## What was sanitized

Only `config.json` was edited. In each running config, the values after `enable
password`, `username ... password 0`, and the console and vty `password` lines were
replaced with `<removed>`, and the self-signed certificate body was replaced with
`<certificate body removed>`. Addresses, interface names, and routes are as captured.
The `raw/` directory the collector writes, which holds Genie's learned objects and the
unedited configs, is not included. The script that did this is
`scripts/lab/sanitize_capture.py`, and `tests/test_lab_scripts.py` checks that these
configs are its fixed point.

## What this does not establish

This is one image, IOS XE 17.15 on IOL, in one simulated lab, reached through a console
server. It says nothing about other platforms, other Genie releases, or the management
SSH and telnet path, which the sandbox did not route.
The adjacency evidence is a single broadcast link in OSPF area 0, and BGP was not
exercised.
