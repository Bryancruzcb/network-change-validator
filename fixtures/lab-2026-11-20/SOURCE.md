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
  entered. Neither packet-capture pause was used, so this run has no pcap; a second run the
  same evening captured the link (see "Packet capture" below).

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

## Packet capture (`bgp-holdtimer-pcap/`), second run, 17:53 to 17:59 PT

A Windows browser cannot reach the CML web UI while the sandbox VPN runs inside WSL, so the
second run started and saved the capture through the CML API instead, with
`scripts/lab/cml_capture.py` (filter `tcp port 179` on the R1-R2 link). The run was otherwise
the same script against the same lab, and its ncv comparisons gave the same results: pre vs
pre 0 findings, pre vs post `V_ADJ` on R1 and R2 with both peers `Idle`, pre vs restored 0.
Only its pcap is published. `link.pcap` is CML's file as downloaded (classic pcap, Ethernet,
16,845 bytes), and `summary.txt` is `scripts/lab/bgp_pcap.py`'s reading of it. It holds only
BGP between 1.1.1.1 and 1.1.1.2; BGP here uses no authentication, so there was nothing to
remove.

What the link carried, in seconds from the first segment:

1. 0 to 6: keepalives every 3 s each way, each one ACKed. R2 had opened the TCP session
   (1.1.1.2:63953 to 1.1.1.1:179).
2. From about 6 s the ACL was on. The capture point is on the wire, outside R1, so it still
   sees what R2 sends; R1 drops it. R2's ACKs never reach R1, so R1 retransmits its own
   keepalives (7.1 s, 9.2 s), and R2's keepalives go unanswered, so R2 retransmits too.
3. 13.3 s: R1 sends `NOTIFICATION 4/0 Hold Timer Expired` and closes with FIN. The last
   keepalive from R2 that R1 could have received was at 3.6 s, so this is about 9.7 s later
   (an inference from the capture: the 9 s hold time plus timer granularity). R2 never
   sends a NOTIFICATION: it kept hearing R1 the whole time, so its own hold timer never ran
   out.
4. 21.2 s: R1 retransmits its unacknowledged data, the NOTIFICATION included, and R2 answers
   with RST.
5. From 22.6 s both routers try to reconnect. R2's SYNs to 1.1.1.1:179 are dropped; R1's
   SYNs reach R2, but R2's SYN-ACKs are dropped, so R1 retries at 2, 4, and 8 s intervals,
   TCP's exponential backoff.
6. 109.7 s, after the ACL came off: R1 opens a new TCP session, both send `OPEN` with hold
   time 9 (AS 65001 id 1.1.1.1, AS 65002 id 2.2.2.2), then UPDATEs and keepalives.

`tests/test_lab_evidence.py` replays the pcap: the summary matches `summary.txt`, both
NOTIFICATIONs are 4/0 from R1, none is a Cease, and both OPENs carry a 9 s hold time.

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
one peer stopped arriving. ncv saw the result, both sessions Idle; the cause, R1's hold timer
expiring, is shown by the packet capture, not by ncv. The pcap comes from the second run, not
the run whose snapshots are published. It says nothing about iBGP, other address families,
BGP in a non-default VRF, other platforms, or other Genie releases.
