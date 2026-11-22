# Lab evidence, 2026-11-21

Real captures from a Cisco DevNet sandbox, sanitized for publishing. These are the fifth to
eighth live runs with published snapshots; the earlier four are in `fixtures/lab-2026-09-12`,
`fixtures/lab-2026-09-18`, and `fixtures/lab-2026-11-20`. What each run adds:

- OSPF dead timer (`ospf-deadtimer/`): the first OSPF adjacency lost with both ends of the
  link up. An inbound ACL on R1 denied OSPF from R2; nothing was shut down.
- iBGP over OSPF (`ibgp/`): the first iBGP session, and the first intent that requires routes
  learned through BGP and through OSPF. It is also the first capture written in ncv's by-VRF
  BGP layout (`bgp.<device>.vrfs.<vrf>.neighbors`), for the default VRF.
- BGP in vrf NCV (`bgp-vrf/`): the first BGP session in a non-default VRF, beside a global
  session to the same address, and the first real capture with peers in two VRFs of that
  layout.
- Second platform (`second-platform-iosv/`): the first capture of a router that is not
  IOS XE on IOL (an IOSv R3 added to the lab for the run), and the first capture of three
  devices.

Each run's intent and predicted findings were written and merged before the run (PR #16), and
sit next to the evidence as `intent-<run>.yaml` and `expect-<run>.txt`. All four change
comparisons matched the prediction: each gave exactly the findings of its expect file. The
match is on the findings only. The comments in the expect files are the prediction's reasons
as written before the runs; this note says which of them a capture shows. The synthetic
fixtures in `fixtures/pre` and `fixtures/post` are unchanged and remain the demo.

## Environment

- Cisco DevNet "Cisco Modeling Labs" reservable sandbox: CML 2.7.2 (`2.7.2+build.26`) with
  its preloaded `default-lab` topology, on the same reservation as the 2026-11-20 runs. The
  day's first reset removed the eBGP configuration those runs left behind
  (`no router bgp 65001` on R1, `no router bgp 65002` on R2).
- R1 and R2: both IOL XE running IOS XE 17.15, joined by a direct link (R1 Ethernet0/1
  1.1.1.1/24 to R2 Ethernet0/1 1.1.1.2/24). Each has a static route to the other's LAN: R1 to
  20.20.20.0/24, R2 to 10.10.10.0/24.
- R3, for the second-platform run only: an IOSv node (CML node definition `iosv`, image
  `iosv-159-3-m9`). `scripts/lab/cml_lab.py add-r3 iosv` created it through the CML API with a
  day-0 configuration, and CML kept that configuration. The same command linked R1 Ethernet0/3 to
  R3 GigabitEthernet0/0 while R1 was running, then started R3. `add-r3`'s poll, every 15 s, first
  saw R3 BOOTED at 181 s. CML's lab events, read that evening, put BOOTED 177 s after STARTED and
  181 s after QUEUED (QUEUED 21:35:03, STARTED 21:35:07, BOOTED 21:38:04 UTC, that is 13:35 to
  13:38 PT). The `iosv` node definition's boot timeout is 180 s. The NX-OS R3 later reached BOOTED
  at its own timeout with an empty console (478 s after STARTED, against 480 s), so this BOOTED
  most likely came from the timeout too. That is inferred from the timing only: this R3's console
  log was not read before the node was deleted (see "R3 after the NX-OS attempt"). What showed this
  R3 was really up is that R1 saw it as its OSPF neighbor and BGP peer, and ncv captured it. The
  node definition asks for 512 MiB; the controller reported 29783 MiB free. R3's captured config
  says `version 15.9`; the fuller `15.9(3)M9` comes only from the image name.
- Collector: `ncv snapshot --testbed ... --features <per run> --i-am-in-a-lab` from WSL with
  pyATS, Genie, and Unicon 26.8 on Python 3.12.14, running ncv 0.1.0 at commit `630402c` on
  `main`.
- Access path: the CML console server, as on every earlier run
  (`testbeds/cml-console.yaml.example`). R3 was reached through the same console server with
  the CML login alone (the IOS entry in `testbeds/cml-console-r3.yaml.example`).
  `second-platform-iosv/*/SOURCE.json` names `testbeds/lab-r3.yaml`, a local file that is not
  published. The run script refuses to start unless that file gives R3 the os its platform
  needs, `ios` for iosv. The file was edited later for the NX-OS attempt.
- Driver: `scripts/lab/run-session.sh`, which asks for the lab logins once and then runs its
  named steps unattended. Each step is one script: `probe.sh`, `run-ospf-deadtimer.sh`,
  `run-ibgp.sh`, `run-bgp-vrf.sh`, `run-second-platform.sh iosv`, or `labctl.py reset`. Each
  run script resets R1 and R2 first, applies its setup, and checks its change comparison
  against its expect file.
- Sessions, in Pacific time from the collector's clock (the routers' clocks run on UTC):
  the first ran from 12:58:57 to 13:27:03 (the probe, the three R1-R2 runs, a reset), and the
  second from 13:34:25 to 13:49:46 (the second-platform run, a reset). Every step exited 0. A
  third session that evening tried NX-OS; see "The NX-OS attempt".

## The probe, 12:58 to 13:00 PT

`scripts/lab/probe.sh` is read-only. It answered three questions.

1. Do the management addresses answer? No. From the collector over the sandbox VPN,
   10.10.20.171 (R1) and 10.10.20.172 (R2) gave no answer on port 22 or port 23 within 3 s,
   and two pings to each got no reply. On the routers, `show ip ssh` reports SSH disabled,
   with no RSA or EC host keys. So the SSH path run (`run-ssh-path.sh`) was not started, and
   every capture here went through the console server.
2. Is R1 Ethernet0/3 free? Yes. CML lists it as not connected, and R1 shows it
   administratively down with no address.
3. Which images exist? CML has node definitions for `iosv` (image `iosv-159-3-m9`, 512 MiB),
   `cat8000v` (`cat8000v-17-15-01a`, 4096 MiB), and `nxosv9000` (`nxosv9300-10-5-1-f`,
   12288 MiB).

## OSPF dead-timer run (`ospf-deadtimer/`), 13:00 to 13:07 PT

1. Operator setup outside ncv (`scripts/lab/labctl.py setup-ospf-fast`): `router ospf 1` on
   R1 and R2 with router IDs 1.1.1.1 and 2.2.2.2, `network 1.1.1.0 0.0.0.255 area 0`, and
   `ip ospf hello-interval 1` on Ethernet0/1. Both neighbors were FULL at the poll at
   13:01:25. `labctl.py check-dead-time` then read `Hello 1, Dead 4` on both routers. IOS
   derives the 4 s dead interval from the hello and writes no line for it.
2. `pre`, then the no-change check against `intent-ospf-deadtimer.yaml`: exit 0, no findings.
   That check compares the pre capture with itself, so it shows the pre capture met every
   rule, the hello line on both routers included.
3. The one change, on R1 between 13:03:19 and 13:03:36 PT: an inbound extended ACL,
   `NCV-BLOCK-OSPF`, on Ethernet0/1, denying OSPF from 1.1.1.2 and permitting everything else.
   IOS stored it as `10 deny ospf host 1.1.1.2 any` and `20 permit ip any any`. Nothing was
   shut down.
4. At the poll at 13:03:46, R1 listed no OSPF neighbor, and R2 still listed R1 but not as
   FULL.
5. `post`, then `ncv diff pre post`: exit 1 with two findings, both `V_ADJ`. R1's neighbor
   2.2.2.2, FULL on Ethernet0/1 before, is gone. R2 still lists neighbor 1.1.1.1 on
   Ethernet0/1, but as `init`. The ACL lines appear in R1's post config only.
6. What gave no finding, and why. Every interface kept its status, and every error counter
   stayed 0. ncv's interface rules check error counters only, never up/down. The routing
   tables were identical in all three captures: OSPF here advertises only 1.1.1.0/24, which
   is connected on both routers, so no capture holds an OSPF route, and the intent's route
   rules (static and connected routes) could not react. No rule names the ACL, so there was
   no `V_DRIFT`.
7. The ACL unbound and deleted in the step that began at 13:05:04; both neighbors FULL again by the
   poll at 13:05:33. Then `restored` and `ncv diff pre restored`: exit 0, no findings. The
   normalized JSON of restored equals pre, and R1's config differs only in its `Last configuration
   change` stamp. The lab did not return to an identical state, though: the packet capture shows
   the DR and BDR roles swapped after recovery, and ncv does not compare roles.

## iBGP run (`ibgp/`), 13:07 to 13:17 PT

1. Operator setup outside ncv (`labctl.py setup-ibgp`): Loopback0 10.255.255.1/32 on R1 and
   10.255.255.2/32 on R2, advertised in OSPF area 0 with the link; Loopback1 172.16.1.1/24 on
   R1 and 172.16.2.1/24 on R2; the 1 s hello on Ethernet0/1; and iBGP in AS 65010 between the
   Loopback0 addresses (`update-source Loopback0`, `timers 3 9`), each router advertising its
   Loopback1 network. OSPF was FULL at the poll at 13:08:21, and each router had learned a
   prefix from its peer at the poll at 13:09:25. The checks read Hello 1, Dead 4 for OSPF and
   a negotiated hold time of 9 s with keepalive 3 s for BGP, on both routers.
2. `pre`, then the no-change check against `intent-ibgp.yaml`: exit 0, no findings. Each
   router held the peer's Loopback0 as an `ospf` route and the peer's Loopback1 network as a
   `bgp` route, as the intent requires.
3. The one change, on R1 between 13:11:51 and 13:12:09 PT: the same ACL as the dead-timer
   run. Nothing about BGP was touched.
4. R1 had lost its OSPF neighbor by the poll at 13:12:19. Neither iBGP session was
   Established at the poll at 13:12:50. That gap is the poll cycle and the console logins,
   not a measured time to effect.
5. `post`, then `ncv diff pre post`: exit 1 with eight findings.
   - `V_ADJ` for the OSPF neighbors: R1's 2.2.2.2 is gone, and R2 lists 1.1.1.1 as `init`.
   - `V_ADJ` for both iBGP peers: `Established` before, `Idle` after, on both routers.
   - `V_ROUTE` for four missing routes: on R1, 10.255.255.2/32 (was `ospf`) and
     172.16.2.0/24 (was `bgp`); on R2, 10.255.255.1/32 (was `ospf`) and 172.16.1.0/24 (was
     `bgp`).

   One ACL on OSPF reached through three layers: the adjacency, the loopback routes, and
   the BGP session that ran over them.
6. What gave no finding: the ACL lines in R1's config, which no rule names, on purpose. Every
   other change between pre and post in the normalized JSON produced a finding. Interfaces
   kept their status and zero error counters. The snapshots show both sessions `Idle`, not
   how either session ended; the packet capture shows part of that (below).
7. The ACL removed in the step that began at 13:14:24; OSPF FULL by the poll at 13:14:51, and the
   peers' prefixes learned again by the poll at 13:15:22. Then `restored` and `ncv diff pre
   restored`: exit 0, no findings. The normalized JSON of restored equals pre, and R1's config
   differs only in its stamp. As in the dead-timer run, the capture shows the DR and BDR roles
   swapped, and the iBGP session came back on a new TCP connection. ncv compares neither.

## BGP VRF run (`bgp-vrf/`), 13:17 to 13:26 PT

1. The reset removed the iBGP run's OSPF, BGP, and loopbacks. The script then waited until
   neither router listed vrf NCV (poll at 13:17:54).
2. Operator setup outside ncv (`labctl.py setup-bgp-fast`, then `setup-vrf`):
   - The 2026-11-20 global eBGP session: R1 AS 65001 and R2 AS 65002 over 1.1.1.0/24, with
     `timers 3 9`, each advertising its LAN.
   - vrf NCV (rd 65001:100 on R1, 65002:100 on R2) on a dot1Q subinterface,
     Ethernet0/1.100 on VLAN 100, with the same addresses 1.1.1.1/24 and 1.1.1.2/24.
   - A Loopback100 in the VRF: 172.16.101.1/24 on R1, 172.16.102.1/24 on R2.
   - An eBGP session in `address-family ipv4 vrf NCV`, with `timers 3 9`, each router
     advertising its Loopback100 network.

   Both global sessions were Established at the poll at 13:19:36, and both VRF sessions had
   learned a prefix at the poll at 13:20:07. The hold-time checks passed for both sessions.
3. `pre`, then the no-change check against `intent-bgp-vrf.yaml`: exit 0, no findings. Each
   router lists its peer's address twice, once under vrf `default` and once under `NCV`.
4. The one change, on R1 between 13:22:41 and 13:22:58 PT: `shutdown` on Ethernet0/1.100. The
   parent Ethernet0/1 and the global session were not touched. Both VRF sessions were out of
   Established at the poll at 13:23:09.
5. `post`, then `ncv diff pre post`: exit 1 with five findings, all in vrf NCV.
   - `V_ADJ` on R1 for peer 1.1.1.2: `Established` before, `Idle` after.
   - `V_ADJ` on R2 for peer 1.1.1.1: `Established` before, `Active` after.
   - `V_ROUTE` on R1 for 1.1.1.0/24 (was `connected`) and 172.16.102.0/24 (was `bgp`).
   - `V_ROUTE` on R2 for 172.16.101.0/24 (was `bgp`).

   No finding names the default VRF.
6. What gave no finding, and why.
   - The global session stayed Established on both routers in all three captures, and the
     default routing table did not change. That table holds no BGP-learned route in any
     capture: the static routes cover what each peer advertises. So the default-VRF route
     rules test static and connected routes only, and only the adjacency rules test the
     global session.
   - R1's Ethernet0/1.100 went down while R2's stayed up. No rule checks status, and the
     intent leaves the subinterface out because IOS XE reports no error counters for it (its
     counters are empty in every capture).
   - R2 kept 1.1.1.0/24 as connected in vrf NCV, since its own subinterface stayed up. R1's
     local 1.1.1.1/32 in vrf NCV disappeared; no rule names it.
7. `no shutdown` in the step that began at 13:24:32; both VRF sessions had learned a prefix again
   by the poll at 13:24:59. Then `restored` and `ncv diff pre restored`: exit 0, no findings. The
   normalized JSON of restored equals pre. After sanitizing, R1's config differs only in its stamp
   (the one blank line the console added in the restored capture sat inside the certificate body,
   which the sanitizer removed; see "What was sanitized"). The VRF session came back on a new TCP
   connection.

## Second-platform run (`second-platform-iosv/`), 13:34 to 13:49 PT

1. The reset found nothing to reset on R1 or R2.
2. `cml_lab.py add-r3 iosv` added R3, from 13:35:01 to 13:38:05 (see "Environment"). Its
   day-0 configuration gave R3 Loopback0 3.3.3.3/32, Loopback1 172.16.3.1/24, and
   GigabitEthernet0/0 10.1.3.3/24 with the 1 s hello; OSPF area 0 on the link and Loopback0,
   router ID 3.3.3.3; eBGP from AS 65003 to 10.1.3.1 in AS 65001 with `timers 3 9`,
   advertising 172.16.3.0/24; and a local `admin` user.
3. Operator setup outside ncv (`labctl.py setup-ospf`, `setup-bgp`, `setup-r3-link`): OSPF
   and eBGP between R1 and R2 on default timers, then R1 Ethernet0/3 as 10.1.3.1/24 with the
   1 s hello, in OSPF, with an eBGP peer 10.1.3.3 in AS 65003 and `timers 3 9`. At the poll
   at 13:39:35, R1 saw R3 as its OSPF neighbor FULL and its BGP peer with a prefix learned.
4. `pre` of R1, R2, and R3, then the no-change check against
   `intent-second-platform-iosv.yaml`: exit 0, no findings. R3's strings in that intent were
   written from Genie's IOS parsers and the platform's documentation before any capture, and
   none needed correcting.
   - Genie's output for classic IOS normalized into the same snapshot layout as IOS XE, with
     no adapter change: R3's OSPF, BGP, routing, and interface records have the same keys as
     R1's.
   - ncv connected to R3's console with the CML login alone and captured it three times with
     no connect error. That is the only evidence here about a first-boot dialog on IOSv.
5. The one change, on R1 between 13:42:32 and 13:42:50 PT: `shutdown` on Ethernet0/3. At the
   poll at 13:42:55, R1 saw R3 neither as an OSPF neighbor FULL nor as a BGP peer with a
   prefix. The script then waited 15 s more before the post capture.
6. `post`, then `ncv diff pre post`: exit 1 with nine findings.
   - On R1: `V_ADJ` for OSPF neighbor 3.3.3.3 (gone) and BGP peer 10.1.3.3 (`Established`
     before, `Idle` after); `V_ROUTE` for 10.1.3.0/24 (was `connected`), 3.3.3.3/32 (was
     `ospf`), and 172.16.3.0/24 (was `bgp`).
   - On R3: `V_ADJ` for OSPF neighbor 1.1.1.1 (gone) and BGP peer 10.1.3.1 (`Established`
     before, `Active` after); `V_ROUTE` for 1.1.1.0/24 (was `ospf`) and 10.10.10.0/24 (was
     `bgp`).

   R3's snapshot shows its OSPF neighbor gone and its BGP peer `Active`. This run has no
   packet capture, so nothing shows how R3's side ended.
7. Why nine and not ten: R3's GigabitEthernet0/0 stayed up, and R3 kept 10.1.3.0/24 as a
   connected route. The prediction counted on that.
8. What gave no finding, and why.
   - R2 was not unaffected. Its own OSPF neighbor and BGP peer held, but it lost three routes
     it had learned through R1: 10.1.3.0/24 and 3.3.3.3/32 (`ospf`) and 172.16.3.0/24
     (`bgp`). There is no finding because the intent lists only R1 and R3, so ncv checked
     nothing on R2.
   - R3 lost 20.20.20.0/24 (`bgp`). The intent lists only 10.10.10.0/24 for R3.
   - R1 lost its local 10.1.3.1/32, which no rule names.
   - R1's Ethernet0/3 went down with error counters still 0. Interface rules check counters
     only.
9. `no shutdown` in the step that began at 13:45:53; R1 saw R3 FULL and Established with a prefix
   again by the poll at 13:46:16. Then `restored` and `ncv diff pre restored`: exit 0, no findings.
   The normalized JSON of restored equals pre. R1's config differs only in its stamp, and R3's
   config has three fewer blank lines, which the console capture inserts.
10. Left over from the VRF run: R1's and R2's interface tables list Ethernet0/1.100 as down,
    with empty counters, in all three captures. The reset after the VRF run deleted that
    subinterface, and R1 still showed it as `deleted`. Neither config has it, and no rule
    reads it. R3 stayed in the lab after the run; the session's reset touches only R1 and R2.

`tests/test_lab_evidence.py` replays these comparisons on every commit.

## Packet captures: how they were taken

The three R1-R2 runs captured their link; the second-platform run did not. Each run started
`scripts/lab/cml_capture.py` right after the no-change check and saved the capture after the
restored comparison. The capture runs on CML through its API, on the link between R1
Ethernet0/1 and R2 Ethernet0/1, with a 900 s limit and a filter per run. Each `link.pcap` is
CML's file as downloaded: classic pcap, Ethernet link type, no frame truncated. Each
`summary.txt` is `scripts/lab/link_pcap.py`'s reading of it, as the run wrote it. Times below
are seconds from the first packet. Each capture's first packet came about 4 s after the log's
capture-start line, but the capture's clock is not tied to the collector's, so lining a
packet up with a log line carries a few seconds of doubt.

What none of the three can show: the capture point is on the link, outside both routers. It
sees what each router transmits, not what the other router accepts or does inside. It shows
no router state (FULL, `init`, Idle, Active), no routing table, and no timer. It cannot show a
message a router generated but never transmitted, nor anything sent before the capture
started (so the OPENs of sessions already up are missing) or after it stopped.

`tests/test_lab_evidence.py` replays the three captures against their summaries.

## Packet capture (`ospf-deadtimer-pcap/`)

Filter `ip proto 89`. 61,336 bytes, 476 frames, all OSPFv2: 461 Hellos, 5 DB Descriptions,
2 LS Requests, 6 LS Updates, 2 LS Acknowledgments. Addresses: 1.1.1.1, 1.1.1.2, 224.0.0.5.
The first packet is stamped 13:03:19 PT; the capture spans 216.8 s.

1. 0 to 9.979: Hellos about once a second from both routers, every one with hello 1 and
   dead 4. DR is 1.1.1.1 (R1), BDR is 1.1.1.2 (R2), and each lists the other.
2. R2's Hellos keep appearing on the wire for the whole block. R1's Hellos list 2.2.2.2
   through 9.206.
3. 10.134: R1's Hello lists `neighbors none`, with BDR 0.0.0.0.
4. From 10.135: R2 sends unicast Hellos to 1.1.1.1, then multicast Hellos naming itself DR
   with no BDR, still listing 1.1.1.1. R1 keeps sending Hellos with no neighbor, through
   112.223. No DB Description, LS Request, LS Update, or LS Acknowledgment appears during the
   block.
5. 112.236: an R2 Hello, and at 112.237 R1 starts a DB Description exchange. LS Requests and
   Updates follow; by 113.170 both routers' Hellos list each other again, and both send LS
   Acknowledgments at 114.738.
6. From 112.237 to the end, the DR is 1.1.1.2 (R2) and the BDR 1.1.1.1 (R1): the roles
   swapped.

Observed: R2's Hellos were on the wire during the block, and R1's Hellos stopped listing R2.
Inferred, not shown: that R1 discarded R2's Hellos; that R1 timed R2 out on its dead interval
(its first neighborless Hello at 10.134 came 4.0 s after an R2 Hello at 6.090, so the ACL
would have taken effect between 6.090 and 7.068); that the undo took effect between R2's
Hellos at 111.321 and 112.236; and that FULL was reached, which the wire shows only through
the completed exchange. R2's `init` comes from R2's snapshot; on the wire R2 just keeps
listing R1.

## Packet capture (`ibgp-pcap/`)

Filter `ip proto 89 or tcp port 179`. 107,075 bytes, 911 frames: 679 OSPF (664 Hellos and the
same 5, 2, 6, 2 split of the others) and 232 TCP segments on port 179. Addresses: 1.1.1.1,
1.1.1.2, 224.0.0.5, 10.255.255.1, 10.255.255.2. The first packet is stamped 13:11:51 PT; the
capture spans 314.1 s.

1. 0 to 10.111: OSPF as in the dead-timer run. One iBGP TCP connection, 10.255.255.1:64623
   to 10.255.255.2:179, with keepalives about every 3 s each way, each ACKed. The last segment
   before the gap is R2's ACK at 10.111.
2. 11.492: R1's Hello lists `neighbors none`. R2 keeps listing R1 and names itself DR, as
   before.
3. 10.111 to 160.533: no port-179 segment of any kind, for 150.4 s. No NOTIFICATION, FIN,
   RST, or SYN appears during the outage. The session loss shows on the wire only as missing
   keepalives.
4. 159.499: R1 starts the OSPF DB Description exchange. Afterwards the DR is R2 and the BDR
   R1, swapped as in the dead-timer run.
5. 160.533: R1 opens a new TCP connection from port 65081. Both send `OPEN` with AS 65010 and
   hold time 9 (id 1.1.1.1 and id 2.2.2.2), then UPDATEs and keepalives every 3 s to the end.
6. 172.029: R2 sends one segment on the old connection, to port 64623: three KEEPALIVEs, an
   UPDATE (55 bytes), and `NOTIFICATION 4/0 Hold Timer Expired`. R1 answers at once with a
   reset (RST).
7. R1's own NOTIFICATION for the old session never appears.

The packet prediction written before the run (the iBGP section of `scripts/lab/README.md`,
PR #16) did not hold. It said the keepalives would stop, no NOTIFICATION would follow, and
the NOTIFICATION each router logs when its hold timer runs out could not be sent. During the
outage, that is what the link showed: no NOTIFICATION was on the link. But R2's "Hold Timer
Expired" NOTIFICATION did reach the wire, only after the undo, on the old TCP connection, and
R1 answered it with a reset.

Inferred, not shown: that the ACL took effect between R2's Hellos at 6.765 and 7.668; that
neither router could send anything to the other's loopback during the outage, because the
post capture holds no route to the peer's Loopback0 on either router; that the 172.029 bytes
were queued during the outage and reached the wire for the first time then (they start at the
byte after R2's last data at 9.478); and that R1's RST means R1 had already closed the old
connection.

## Packet capture (`bgp-vrf-pcap/`)

Filter `tcp port 179 or (vlan and tcp port 179)`. 41,219 bytes, 479 frames, all TCP on port
179: 296 untagged (the global session) and 183 tagged with 802.1Q VLAN 100 (the vrf NCV
session, shown as `vlan 100` in the summary). Addresses: 1.1.1.1 and 1.1.1.2 only. The first
packet is stamped 13:22:42 PT; the capture spans 225.0 s.

1. 0 to 3.709: two sessions between the same addresses. The global one is untagged,
   1.1.1.1:12085 to 1.1.1.2:179; the VRF one is on VLAN 100, 1.1.1.1:41395 to 1.1.1.2:179.
   Both carry keepalives about every 3 s each way.
2. 3.709: R1's last frame on VLAN 100, a KEEPALIVE. From then until 117.336, R1 sends nothing
   on VLAN 100: no NOTIFICATION, no FIN, no RST, and no answer to R2's SYNs.
3. 6.144: R2's KEEPALIVE gets no ACK. R2 retransmits it at 7.147 and 9.153 and keeps sending
   keepalives.
4. 13.312: R2 sends `NOTIFICATION 4/0 Hold Timer Expired` and closes with FIN. That is 9.6 s
   after R1's last keepalive, against a 9 s hold time.
5. 21.189: R2 retransmits its unacknowledged data, the NOTIFICATION included.
6. From 21.509: R2 tries to reconnect, with SYNs to 1.1.1.1:179 from port 52170 (21.509),
   25851 (63.497), and 13875 (103.438), each retried. None is answered. This fits the
   snapshots' R1 `Idle` and R2 `Active`.
7. 117.336, after the undo: R1 opens a new connection from port 62426. Both send `OPEN` with
   hold time 9 (AS 65001 id 1.1.1.1, AS 65002 id 2.2.2.2), then UPDATEs and keepalives.
8. The global session runs untouched for the whole capture: keepalives about every 3 s each
   way, and no SYN, FIN, RST, UPDATE, or NOTIFICATION.

A decoder limit: `summary.txt` does not mark retransmissions that TCP repacketized. The
segments at 13.164 (three KEEPALIVEs) and 21.189 (three KEEPALIVEs and the NOTIFICATION)
start at the same sequence number as R2's unanswered keepalive at 6.144, so both are
retransmissions. The summary shows two NOTIFICATION lines, but R2 sent one NOTIFICATION
(13.3 s) and retransmitted it (21.2 s).

Not shown: what R1 did inside. The capture shows R1 fall silent on VLAN 100 after the
shutdown; it does not show R1 tearing the session down or any NOTIFICATION R1 may have logged.

## The NX-OS attempt, 21:18 to 21:40 PT

A third session tried the second-platform run with R3 on NX-OS. It stopped before any capture,
so nothing from it is published, and it is not evidence about ncv on NX-OS: ncv was never
run against that R3.

1. `cml_lab.py remove-r3` ran for the first time. It stopped the IOSv R3, wiped its disks,
   deleted its link to R1 Ethernet0/3, and deleted the node.
2. The reset found nothing to reset. `cml_lab.py add-r3 nxosv9000` then created R3 (node
   definition `nxosv9000`, image `nxosv9300-10-5-1-f`, 12288 MiB asked with 29757 MiB free).
   CML kept the day-0 configuration and linked R1 Ethernet0/3 to R3 Ethernet1/1. `add-r3`'s
   poll, every 15 s, saw R3 BOOTED at 483 s and the link STARTED.
3. At 21:27:07 the operator setup configured R1's side as in the IOSv run. R1 Ethernet0/3 was
   up/up.
4. From 21:28:35 the script waited up to 600 s for R1 to see R3 as its OSPF neighbor FULL and
   its BGP peer with a prefix. None of the 89 polls, 21:28:41 to 21:38:45, saw either. When
   the wait ended, R1 Ethernet0/3 showed line protocol up, and R1's CDP table listed only R2.
5. At 21:39:26 the run stopped before any capture (exit 1). The reset then returned R1 and R2
   to the shipped configuration. R3, the NX-OS node, was left in the lab; it was still there
   at 22:03 PT.

ncv never connected to R3. When the session ended, nothing in its logs showed why R1 never
saw R3. The next section does.

## R3 after the NX-OS attempt, 21:55 to 22:03 PT

Two read-only checks looked at R3 while it was still in the lab. They were ad-hoc scripts
outside the repo, not repo tools: GET calls to the CML 2.7.2 API, and one console connection
made the way ncv makes it (no init commands, with the first-boot guard). Nothing was
configured. Their logs are not published.

Observed:

- CML's lab events for R3, in UTC on 2026-11-22 (21:19 to 21:27 PT): QUEUED 05:19:05, STARTED
  05:19:08, BOOTED 05:27:06. BOOTED came 478 s after STARTED (481 s after QUEUED). That is the
  `nxosv9000` node definition's 480 s boot timeout, not a console line: before the timeout, CML
  marks the node BOOTED only when its console shows `There is no admin password in the bootstrap
  file` or `User Access Verification`. The 483 s above is when `add-r3`'s poll first saw that
  state.
- CML's console log for R3 held 12 characters on one line, `|0000000000|`, on both serial
  lines. The same call returned 1,243,601 characters for R1 and 1,048,453 for R2.
- The console connection (ssh to the console server, `open /default-lab/R3/0`) timed out
  with an empty buffer. R3's console showed nothing.
- Two samples of CML's statistics, 32 s apart, at 2630 s and 2662 s after R3 started: R3 had
  read 512 bytes from its disk and written 0 both times. Its CPU use was 49.9 and then 49.64,
  with 2 virtual CPUs. On the R1-R3 link CML counted 760 packets read and 0 written, both
  times. R1's side of that link was up from about 21:27 to 21:39 PT with a 1 s OSPF hello,
  which is about that many Hellos, so the 760 are R1's and the 0 is R3's side.
- In the same samples R1 and R2, which run as IOL processes, showed 0 bytes read and 0
  written. So the disk counter alone does not tell R3 from a running node. No booted
  virtual-machine node was sampled for comparison.
- CML's controller statistics showed 2,534,817,792 bytes of memory in use with R3 running.
  The probe at 12:59 PT, before any R3 existed, showed 2,424,606,720. CML's per-node RAM
  figure, which gives no unit, was 0.34 for R3 against 18.5 for R1.
- The node definition boots with EFI firmware (`efi_boot` true). The compute host's processor
  is an AMD EPYC 7773X. CML's health check reported hardware virtualization enabled.
- CML's own default day-0 file for `nxosv9000` carries a workaround for a boot that stops at
  `loader>`: an EEM applet that sets `boot nxos`. The day-0 configuration `add-r3` wrote for
  R3 does not have it.
- CML's diagnostics calls answered HTTP 403 for the `developer` login.

What follows:

- R3's virtual machine never loaded NX-OS. What set it apart from the running nodes was its
  console log and the link counter: in 44 minutes it printed nothing on its console beyond
  those 12 characters, and sent no packet. It also read 512 bytes from its disk, wrote
  nothing, and kept one of its two virtual CPUs busy. With R3 running, the controller's
  memory in use was about 110 MB above its level at the 12:59 PT probe, before any R3
  existed; that is the whole controller, not a figure for R3.
- CML's BOOTED state is not proof that a node booted. Here it came from the timeout, so the
  `R3 BOOTED` line from `cml_lab.py add-r3` is no proof either. The IOSv R3's BOOTED came
  within a few seconds of its own timeout, which points the same way (see "Environment").
- The day-0 configuration is not the cause: NX-OS reads it only once NX-OS runs. That does
  not show the configuration is right: no NX-OS has read it. The link is not the cause: it
  was up. ncv is not the cause: it never ran against R3, and a console connection made the
  way ncv makes it found no prompt.

Inference, not proven here:

- The machine is stuck in its firmware, before the NX-OS boot loader. The exact stopping point
  is not known: the API shows no screen output, and the `developer` login cannot read the
  hypervisor diagnostics.
- The likely reason is the AMD processor. A Cisco employee wrote on the Cisco Community on
  2024-12-04 that CML runs on AMD processors but some reference platform images are
  Intel-only, and named boot issues with IOS XRv 9000 and NX-OSv 9000 ([the post][amd-post]).
  This fits what was seen. It was not tested here.

Still open:

- Whether NX-OS 9000v can boot in this sandbox at all. There was one attempt.
- Whether the day-0 configuration `add-r3` writes works on NX-OS. No NX-OS has read it, and
  it lacks CML's `boot nxos` workaround.
- Everything about ncv on NX-OS. ncv has still never talked to an NX-OS device: the console
  login with two credentials, a first-boot dialog, and Genie's NX-OS output through the
  adapter are untested on a real device.
- Found the same evening, offline, against Unicon's mock `n9k` device only: with ncv's connect
  arguments, Unicon's NX-OS plugin answers a device at a `loader>` prompt by sending `boot`,
  and one at a boot-mode prompt by sending `load-nxos`. ncv's first-boot guard does not cover
  those prompts. No real device was affected. It is an open item for `src/ncv/live.py`, not
  something these runs change.

[amd-post]: https://community.cisco.com/t5/cisco-modeling-labs-discussions/which-cml-nodes-are-not-compatible-with-amd/m-p/5232504

## What was sanitized

`scripts/lab/sanitize_capture.py` made these copies. Only `config.json` was edited, the same
way in every stage of every run:

- R1, five lines: the values after `enable password`, `username cisco password 0`,
  `username admin password 0`, and the console and vty `password` lines were replaced with
  `<removed>`.
- R2, four lines: the same, without the `username admin` line.
- R3, one line: `username admin privilege 15 secret 9 <removed>`. The hash is removed; only the
  type digit is kept.
- R1 and R2: the self-signed certificate body was replaced with `<certificate body removed>`.
  That is 26 lines per config, except 27 in R1's restored config in `bgp-vrf/`, where the
  console capture had put one blank line inside the certificate body. R3 has no certificate.

Addresses, interface names, routes, the ACLs, the VRF and BGP configuration, and R3's IOSv
evaluation banner are as captured. The `raw/` directory the collector writes is not included.
`tests/test_lab_scripts.py` checks that these configs are the sanitizer's fixed point.

The three pcaps are published as CML returned them, unedited. They hold nothing secret: every
OSPF packet uses authentication type 0, with no cryptographic authentication block; no TCP SYN
carries an MD5 or TCP-AO option; the only IP addresses on the packets are the lab's (1.1.1.1,
1.1.1.2, 224.0.0.5, 10.255.255.1, 10.255.255.2), and the payloads name only the lab's router
IDs and prefixes; and the MAC addresses are the lab's `aa:bb:cc` ones and OSPF multicast.
Classic pcap has no comment, host, or interface-name fields; the only metadata is the capture
time.

## What this does not establish

- One more platform only: classic IOS 15.9 on IOSv, as R3, beside the same IOS XE 17.15 IOL
  R1 and R2. Still one simulated lab, reached through the console server. No run used the SSH
  path. NX-OS and Catalyst 8000V have no capture: the NX-OS attempt stopped before any, and
  Catalyst 8000V was not tried. Other Genie releases were not tried.
- Nothing here is evidence about ncv on NX-OS. ncv has still never talked to an NX-OS device.
  R3's virtual machine never loaded NX-OS; that it stopped in its firmware, likely because of
  the AMD host, is inference (see "R3 after the NX-OS attempt"). Whether NX-OS 9000v can boot
  in this sandbox at all rests on one attempt.
- CML's BOOTED state is not proof that a node booted. The NX-OS R3 reached it at its node
  definition's boot timeout with an empty console. The IOSv R3 reached it within a few
  seconds of its own timeout. What showed the IOSv R3 was up is that R1 saw it and ncv
  captured it.
- Offline, against Unicon's mock `n9k` device only: with ncv's connect arguments, Unicon's
  NX-OS plugin answers the loader and boot-mode prompts with `boot` and `load-nxos`, and ncv's
  first-boot guard does not cover those prompts. That is open for `src/ncv/live.py`.
- The iBGP and VRF evidence is IPv4 unicast only: one iBGP session between loopbacks, and one
  VRF on one dot1Q subinterface.
- ncv saw results; only the pcaps show causes, and only in part. That R1 timed R2 out on its
  dead interval is inferred from the Hellos. In the iBGP run, the pcap shows no NOTIFICATION
  during the outage and R2's late one after the undo. In the VRF run, it shows R2's Hold Timer
  Expired NOTIFICATION. Nothing shows how R1 ended either BGP session, or how R3's side ended
  in the second-platform run, which has no pcap.
- The no-change check compares each pre capture with itself. It shows the pre capture met
  every rule, not that two captures agreed.
- A restored comparison with 0 findings does not mean an identical lab. Config text differs in
  timestamps and stray blank lines, the DR and BDR roles swapped in both runs whose OSPF was
  captured on the wire, and BGP sessions came back on new TCP ports. ncv compares none of
  these.
- ncv's interface rules check error counters only. A link that goes down gives no interface
  finding.
- ncv checks only the devices an intent lists. In the second-platform run R2 lost three
  routes with no finding.
