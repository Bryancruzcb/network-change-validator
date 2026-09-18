# Lab evidence, 2026-09-18

Real captures from a Cisco DevNet sandbox, sanitized for publishing. This is the third live
run, and the first with BGP; the 2026-09-12 runs are in `fixtures/lab-2026-09-12`. The
synthetic fixtures in `fixtures/pre` and `fixtures/post` are unchanged and remain the demo.

## Environment

- Cisco DevNet "Cisco Modeling Labs" reservable sandbox: CML 2.7.2 with its preloaded
  `default-lab` topology, a fresh reservation.
- Captured devices: R1 and R2, both IOL XE running IOS XE 17.15, joined by a direct link
  (R1 Ethernet0/1 1.1.1.1/24 to R2 Ethernet0/1 1.1.1.2/24). Each has a static route to
  the other's LAN: R1 to 20.20.20.0/24, R2 to 10.10.10.0/24.
- Collector: `ncv snapshot --testbed ... --features bgp,routing,interface --i-am-in-a-lab`
  from WSL Ubuntu with pyATS and Genie 26.8 on Python 3.12, running ncv at commit `5aac142`.
- Access path: the CML console server, as on 2026-09-12
  (`testbeds/cml-console.yaml.example`).
- Driver: `scripts/lab/run-bgp.sh` at that commit, unattended from start to finish.

## BGP run (`bgp/`), 16:44 to 16:50 PT

The intent, the script, and the expected findings were written and merged the day before
the run (PR #9), from the 2026-09-12 captures. The run matched that prediction.

1. Operator setup outside ncv (`scripts/lab/labctl.py setup-bgp`): eBGP between R1
   (AS 65001, router-id 1.1.1.1) and R2 (AS 65002, router-id 2.2.2.2) over the 1.1.1.0/24
   link, each advertising its own LAN, with inbound soft reconfiguration. Both sessions
   showed Established about 40 seconds later.
2. `pre`, then `ncv diff pre pre` against `intent-bgp.yaml`: exit 0, no findings. Genie's
   learn normalized with no adapter change: both peers `Established`, vrf `default`, and
   the remote AS the intent names.
3. The one change: `neighbor 1.1.1.2 shutdown` under `router bgp 65001` on R1. An
   administrative peer shutdown, not a link shutdown, so both routers dropped the session
   within ten seconds and nothing else moved.
4. `post`, then `ncv diff pre post`: exit 1 with three findings. `V_ADJ` on R1 for neighbor
   1.1.1.2 and on R2 for neighbor 1.1.1.1, both captured as `Idle`, and `V_DRIFT` on R1
   because the running config now held the line the intent forbids. The static routes
   outrank the learned prefixes, so the routing table was identical in all three captures
   and the route and interface rules stayed compliant.
5. `no neighbor 1.1.1.2 shutdown`, both sessions Established again about 25 seconds later,
   then `restored` and `ncv diff pre restored`: exit 0, no findings.

`tests/test_lab_evidence.py` replays these comparisons on every commit.

## What was sanitized

`scripts/lab/sanitize_capture.py` made these copies. Only `config.json` was edited: in each
running config the values after `enable password`, `username ... password 0`, and the
console and vty `password` lines were replaced with `<removed>` (five lines on R1, four on
R2), and the self-signed certificate body was replaced with `<certificate body removed>`.
Addresses, interface names, routes, and the BGP configuration are as captured. The `raw/`
directory the collector writes is not included. `tests/test_lab_scripts.py` checks that
these configs are the sanitizer's fixed point.

## What this does not establish

One image, IOS XE 17.15 on IOL, in one simulated lab, reached through a console server. The
BGP evidence is a single eBGP IPv4 unicast session in the default VRF between two routers,
lost to an administrative shutdown. It says nothing about iBGP, other address families,
BGP in a non-default VRF, a session lost to a hold-timer expiry, other platforms, or other
Genie releases.
