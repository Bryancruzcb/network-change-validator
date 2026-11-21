# Lab evidence, 2026-11-20

Real captures from a Cisco DevNet sandbox, sanitized for publishing. This is the fourth live
run, and the first where a BGP session was lost to a hold-timer expiry instead of a command;
the earlier runs are in `fixtures/lab-2026-09-12` and `fixtures/lab-2026-09-18`. The
synthetic fixtures in `fixtures/pre` and `fixtures/post` are unchanged and remain the demo.

## Environment

- Cisco DevNet "Cisco Modeling Labs" reservable sandbox: CML 2.7.2 with its preloaded
  `default-lab` topology, a fresh reservation. The sandbox now issues its own login per
  reservation for the VPN; the CML login is still `developer`, with its own password, under
  Access Details on the reservation page.
- Captured devices: R1 and R2, both IOL XE running IOS XE 17.15, joined by a direct link
  (R1 Ethernet0/1 1.1.1.1/24 to R2 Ethernet0/1 1.1.1.2/24). Each has a static route to
  the other's LAN: R1 to 20.20.20.0/24, R2 to 10.10.10.0/24.
- Collector: `ncv snapshot --testbed ... --features bgp,routing,interface --i-am-in-a-lab`
  from WSL Ubuntu with pyATS and Genie 26.8 on Python 3.12, running ncv at commit `ee58e95`.
- Access path: the CML console server, as on the earlier runs
  (`testbeds/cml-console.yaml.example`).
- Driver: `scripts/lab/run-bgp-holdtimer.sh` at that commit, unattended once the logins were
  entered. Neither packet-capture pause was used, so there is no pcap of this run.

## Hold-timer run (`bgp-holdtimer/`), 16:58 to 17:04 PT

The intent, the script, and the expected findings were written and merged before the run
(PR #13). The run matched that prediction.

1. Operator setup outside ncv (`scripts/lab/labctl.py setup-bgp-fast`): the same eBGP session
   as the 2026-09-18 run, plus `neighbor <peer> timers 3 9` on both routers. Both sessions
   showed Established at the first poll, about 10 seconds after the setup finished.
2. `labctl.py check-hold-time` read the negotiated timers from `show bgp ipv4 unicast
   neighbors`: hold 9 s and keepalive 3 s on both routers. The parser, written from sample
   output before the run, read this IOS version as expected.
3. `pre`, then `ncv diff pre pre` against `intent-bgp-holdtimer.yaml`: exit 0, no findings.
   IOS wrote the timers line exactly as `neighbor 1.1.1.2 timers 3 9`, so the intent's
   `must_include` rule matched.
4. The one change, on R1 between 17:00:52 and 17:01:10 PT: an inbound extended ACL, `NCV-BLOCK-BGP`, on
   Ethernet0/1, denying TCP port 179 from 1.1.1.2 in both directions and permitting
   everything else. IOS stored it with sequence numbers (`10 deny ...`, `20 deny ...`,
   `30 permit ip any any`). Nothing was shut down. Both routers reported the session out of
   Established at the first poll, about ten seconds after the ACL was in place, which fits
   the 9 s hold time.
5. `post`, then `ncv diff pre post`: exit 1 with two findings, `V_ADJ` on R1 for neighbor
   1.1.1.2 and on R2 for neighbor 1.1.1.1, both captured as `Idle`. No rule names the ACL, so
   there was no `V_DRIFT`: the config rules stayed compliant, and only the adjacency rules
   caught the outage. The routing table and interface counters were unchanged.
6. The ACL unbound and deleted; both sessions Established again about 30 seconds later, then
   `restored` and `ncv diff pre restored`: exit 0, no findings.

`tests/test_lab_evidence.py` replays these comparisons on every commit.

## What was sanitized

`scripts/lab/sanitize_capture.py` made these copies. Only `config.json` was edited: in each
running config the values after `enable password`, `username ... password 0`, and the
console and vty `password` lines were replaced with `<removed>` (five lines on R1, four on
R2), and the self-signed certificate body was replaced with `<certificate body removed>`.
Addresses, interface names, routes, the ACL, and the BGP configuration are as captured. The
`raw/` directory the collector writes is not included. `tests/test_lab_scripts.py` checks
that these configs are the sanitizer's fixed point.

## What this does not establish

One image, IOS XE 17.15 on IOL, in one simulated lab, reached through a console server. The
evidence is the same single eBGP IPv4 unicast session as 2026-09-18, lost because BGP from
one peer stopped arriving. ncv saw the result, both sessions Idle; it did not see the cause.
Nothing here shows which router's hold timer expired or what NOTIFICATION was sent; that
needs a packet capture of the link, which this run did not take. It says nothing about iBGP,
other address families, BGP in a non-default VRF, other platforms, or other Genie releases.
