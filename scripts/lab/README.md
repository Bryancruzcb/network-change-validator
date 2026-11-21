# Lab scripts

The operator side of the 2026-09-12, 2026-09-18, and 2026-11-20 lab runs, kept here so the
evidence under `fixtures/lab-*` can be reproduced and its sanitization rerun. They are written
for the Cisco DevNet "Cisco Modeling Labs" sandbox and its preloaded `default-lab` (R1 and
R2 joined on Ethernet0/1), for an isolated lab you are authorized to use, and they are
deliberately outside `ncv`: `ncv` never pushes configuration, and these scripts do, to make
the one planned change the captures are meant to catch.

| Script | What it does |
|---|---|
| `run-lab.sh` | The static-route run in one command: pre capture, no-change check, `shutdown` on R1 Ethernet0/1, post capture and compare, `no shutdown`, restored capture and compare. |
| `run-ospf.sh` | The OSPF run: sets up OSPF area 0 on the R1-R2 link, waits for FULL, then the same sequence, waiting for both neighbor entries to clear before the post capture. |
| `run-bgp.sh` | The BGP run: sets up eBGP between R1 and R2, waits for Established, then the same sequence around `neighbor 1.1.1.2 shutdown` on R1. |
| `run-bgp-holdtimer.sh` | The hold-timer run: eBGP with a 9 s hold time, then the same sequence around an inbound ACL on R1 that drops BGP from R2. |
| `run-ospf-deadtimer.sh` | The OSPF dead-timer run, prepared and not run: OSPF with a 1 s hello (so a 4 s dead interval), then the same sequence around an inbound ACL on R1 that drops OSPF from R2, with a packet capture of `ip proto 89`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted. |
| `run-ibgp.sh` | The iBGP run, prepared and not run: iBGP between the routers' loopbacks, which reach each other only over OSPF, then the same sequence around the dead-timer run's OSPF ACL on R1, with a packet capture of `ip proto 89 or tcp port 179`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted. |
| `run-bgp-vrf.sh` | The BGP VRF run, prepared and not run: the hold-timer run's eBGP session plus a second one to the same peer address in vrf NCV on the dot1Q subinterface Ethernet0/1.100, then the same sequence around `shutdown` on R1's subinterface, with a packet capture of `tcp port 179 or (vlan and tcp port 179)`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted. |
| `capture.sh` | One capture (`pre`, `post`, or `restored`) for a run driven by hand. |
| `change.sh` | The planned change by hand: `apply` shuts R1 Ethernet0/1 and `undo` brings it back; `bgp-apply` shuts the R1 peer and `bgp-undo` brings it back; `holdtimer-apply` adds the BGP ACL and `holdtimer-undo` removes it; `deadtimer-apply` adds the OSPF ACL and `deadtimer-undo` removes it; `vrf-apply` shuts R1 Ethernet0/1.100 and `vrf-undo` brings it back. |
| `_lib.sh` | Sourced, not run: what new run scripts share (the VPN check, the login prompts, the capture and report paths, `step`, `ctl`, `cap`, `snap`, `compare`), plus `expect_exit` and `lab_finish`, which end a run with exit 0 when every comparison exited as predicted and 3 when one did not. The four published runs keep their own copy, since they reproduce recorded runs. |
| `labctl.py` | The lab actions the scripts above call: `setup-ospf`, `shut`, `noshut`, `wait-full`, `wait-gone`, `setup-bgp`, `bgp-shut`, `bgp-noshut`, `wait-bgp-up`, `wait-bgp-down`, `setup-bgp-fast`, `check-hold-time`, `bgp-block`, `bgp-unblock`, `setup-ospf-fast`, `check-dead-time`, `ospf-block`, `ospf-unblock`, `wait-ospf-lost`, `setup-ibgp`, `wait-ibgp-up`, `wait-ibgp-down`, `check-ibgp-hold-time`, `wait-vrf-gone`, `setup-vrf`, `wait-vrf-bgp-up`, `wait-vrf-bgp-down`, `check-vrf-hold-time`, `vrf-shut`, `vrf-noshut`, and `reset`, which removes what these scripts add from both routers. |
| `sanitize_capture.py` | Copies a run's `pre/`, `post/`, `restored/` for publishing with passwords and certificate bodies replaced and `raw/` left out. |
| `bgp_pcap.py` | Lists the BGP messages in a pcap of the lab link: TCP flags, retransmissions, and each message by name, with NOTIFICATION error codes spelled out. |
| `link_pcap.py` | One timeline of the OSPF packets and BGP segments in a pcap of the lab link: each OSPF packet by type (a hello's timers, DR, BDR, and neighbor list; a database description's flags; an update's LSA count) and each BGP segment as `bgp_pcap.py` shows it, tagged with its VLAN when it has one. |
| `cml_capture.py` | Starts and saves a packet capture of the R1-R2 link through the CML API (`start [--filter "<bpf expression>"]`, default `tcp port 179`, and `stop <file.pcap>`), with the CML login the run scripts already hold. |

The runs compare against the intents kept with their evidence
(`fixtures/lab-2026-09-12/intent-routes.yaml` and `intent-ospf.yaml`,
`fixtures/lab-2026-09-18/intent-bgp.yaml`, and
`fixtures/lab-2026-11-20/intent-bgp-holdtimer.yaml`), so a rerun on the
same sandbox is checked against the same rules. A prepared run's draft intent sits here in
`scripts/lab` (`intent-ospf-deadtimer.yaml`, `intent-ibgp.yaml`, `intent-bgp-vrf.yaml`) until a
run is recorded.

## The BGP run

`run-bgp.sh` sets up eBGP between R1 (AS 65001, router-id 1.1.1.1) and R2 (AS 65002,
router-id 2.2.2.2) over the 1.1.1.0/24 link, each router advertising its own LAN, waits for
Established, takes the pre capture with `--features bgp,routing,interface`, and checks it
against the intent before anything changes. The static routes the lab ships with outrank the
learned prefixes, so the routing table does not change with the session. The planned change
is `neighbor 1.1.1.2 shutdown` on R1: an administrative peer shutdown rather than a link
shutdown, so both routers drop the session at once, the routes and interfaces stay
compliant, and the findings isolate the BGP path.

The script, the intent, and this table were written on 2026-09-17, before any BGP capture
existed, and `tests/test_lab_scripts.py` pinned the table on synthetic snapshots. The run on
2026-09-18 matched it (`fixtures/lab-2026-09-18/SOURCE.md`):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (`neighbor 1.1.1.2 shutdown` on R1) | 1 | `V_ADJ` R1 neighbor 1.1.1.2, `V_ADJ` R2 neighbor 1.1.1.1, `V_DRIFT` R1 (the forbidden line is present) |
| pre vs restored | 0 | none |

## The hold-timer run

The BGP run ended the session with a command, so both routers knew at once. The hold-timer
run ends it the way a broken path does: nothing is shut down, BGP from R2 just stops reaching
R1, and R1 gives up when its hold timer runs out.

`run-bgp-holdtimer.sh` sets up the same eBGP session with `neighbor <peer> timers 3 9` on both
routers (a 3 s keepalive and a 9 s hold time, in place of IOS's 60 s and 180 s), waits for
Established, and runs `labctl.py check-hold-time`, which stops the run unless both sessions
negotiated the 9 s hold time. New timers apply only when a session starts, so use a fresh
reservation, or clear the session if BGP was already up. The no-change check then runs against
`intent-bgp-holdtimer.yaml`, which requires the timers line on both routers.

The planned change is `labctl.py bgp-block`, on R1:

    ip access-list extended NCV-BLOCK-BGP
     deny tcp host 1.1.1.2 host 1.1.1.1 eq bgp
     deny tcp host 1.1.1.2 eq bgp host 1.1.1.1
     permit ip any any
    interface Ethernet0/1
     ip access-group NCV-BLOCK-BGP in

The two deny lines cover both directions of the TCP session, since either router may have
opened it. An inbound ACL also filters traffic addressed to the router itself, so R1 never
sees R2's keepalives; R2 still hears R1. IOS stores the ACL with sequence numbers
(`10 deny ...`). The script, the intent, and this table were merged before the run (PR #13),
with the table pinned on synthetic snapshots in `tests/test_lab_scripts.py`. The run on
2026-11-20 matched it (`fixtures/lab-2026-11-20/SOURCE.md`):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (the ACL on R1) | 1 | `V_ADJ` R1 neighbor 1.1.1.2, `V_ADJ` R2 neighbor 1.1.1.1 |
| pre vs restored | 0 | none |

No rule names the ACL, so unlike the BGP run there is no `V_DRIFT`: the adjacency rules have
to catch a cause the intent did not anticipate. The static routes still outrank the learned
prefixes, and dropped packets are not interface errors, so the route and counter rules should
stay compliant, and they did. The run also confirmed the two things only a run could: IOS
writes the timers line exactly as `neighbor 1.1.1.2 timers 3 9`, and `check-hold-time` read
the negotiated 9 s hold time from IOS XE 17.15's `show bgp ipv4 unicast neighbors`. The
sessions left Established within about ten seconds of the ACL going on and came back about
30 seconds after it came off. That run took no packet capture; a second run did (below).

### Packet evidence

ncv reads what the routers report. A packet capture shows what crossed the wire, which is the
other half of the story: the capture point is on the link, outside R1, so it also sees the
packets R1's ACL throws away.

The CML web UI can capture a link, but with the sandbox VPN running inside WSL a Windows
browser cannot reach it. So right before the change the script runs `cml_capture.py start`,
which logs in to the CML API with the CML login given at the prompts, finds the R1-R2 link of
`default-lab`, and starts a capture filtered to `tcp port 179`. At the end, `cml_capture.py
stop` saves `captures/bgp-holdtimer-<stamp>/link.pcap`, and the script runs

    .venv/bin/python scripts/lab/bgp_pcap.py captures/bgp-holdtimer-<stamp>/link.pcap

which prints one line per BGP segment: time, endpoints, TCP flags, and the messages, with a
NOTIFICATION's error code by name. If the capture cannot start, the run goes on without one;
`NCV_PCAP=0` skips it. The second run on 2026-11-20 captured this way and showed R1 sending
`NOTIFICATION 4/0 Hold Timer Expired`, about nine seconds after the last keepalive it could
have heard, and R2 sending none (`fixtures/lab-2026-11-20/SOURCE.md`); the BGP run's admin
shutdown would have shown `6/2 Cease: Administrative Shutdown`. `bgp_pcap.py` reads classic
pcap, which is what CML 2.7 returns; convert a pcapng with `editcap -F pcap`, which comes with
Wireshark. Open the same file in Wireshark to compare the two views. Publish a pcap only after
checking it holds nothing but lab addresses.

## The OSPF dead-timer run (prepared, not run)

The OSPF twin of the hold-timer run. The 2026-09-12 OSPF run ended the adjacency by shutting
the link, so both routers saw an interface go down. This run shuts nothing: OSPF from R2 just
stops reaching R1, and R1 gives up when its dead timer runs out.

`run-ospf-deadtimer.sh` first runs `labctl.py reset`, so a reused reservation starts from the
shipped configuration, then `setup-ospf-fast`: OSPF area 0 on the R1-R2 link as before, with
`ip ospf hello-interval 1` on Ethernet0/1 of both routers ahead of the `router ospf 1` lines,
so the adjacency forms with the fast timers. IOS then sets the dead interval to four hellos by
itself, 4 s in place of 40 s, and writes only the hello line into the running config, so no
dead interval is configured. After `wait-full`, `labctl.py check-dead-time` reads
`show ip ospf interface Ethernet0/1` on both routers and stops the run unless both report
Hello 1, Dead 4. The no-change check then runs against the draft
`scripts/lab/intent-ospf-deadtimer.yaml`, which requires the hello line on both routers.

The planned change is `labctl.py ospf-block`, on R1:

    ip access-list extended NCV-BLOCK-OSPF
     deny ospf host 1.1.1.2 any
     permit ip any any
    interface Ethernet0/1
     ip access-group NCV-BLOCK-OSPF in

The one deny line covers every destination R2's OSPF uses: the 224.0.0.5 and 224.0.0.6
multicast groups and R1's own address. The prediction, from RFC 2328 sections 10.3 and 10.5:
R1's inactivity timer for 2.2.2.2 runs out within about 4 s and R1 deletes the neighbor. R2
still hears R1, but R1's hellos stop listing 2.2.2.2, so R2 moves its neighbor 1.1.1.1 from
FULL to INIT and keeps it there while the ACL stands. That is why the script waits with
`wait-ospf-lost` (neither router has its peer FULL) and not `wait-gone`, which would never
finish. The link stays up, so no route in the intent changes (its routes are static and
connected), and dropped packets are not interface errors.

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py`:

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (the ACL on R1) | 1 | `V_ADJ` R1 neighbor 2.2.2.2 (gone), `V_ADJ` R2 neighbor 1.1.1.1 (listed, not FULL) |
| pre vs restored | 0 | none |

The two sides differ, which the BGP runs could not show: one router has no record, the other
has a record in the wrong state. No rule names the ACL, so there is no `V_DRIFT`. The script
checks each comparison's exit against this table and exits 0 only when all three match, 3 when
it ran to the end but one did not, and 1 when it stopped early. `change.sh deadtimer-undo`
removes the ACL by hand if a run stops with it in place.

Packet evidence: right before the change the script starts `cml_capture.py start --filter
"ip proto 89"`, and at the end it saves `captures/ospf-deadtimer-<stamp>/link.pcap` and prints
`link_pcap.py`'s timeline of it. The prediction: hellos every second from both routers; after
the ACL goes on, R2's hellos keep arriving on the wire and keep listing 1.1.1.1, while R1's
hellos list no neighbor from about 4 s on; after the ACL comes off, database description, link
state request, update, and acknowledgment packets as the adjacency forms again.

What only the run can confirm:

- that IOS writes the hello line as `ip ospf hello-interval 1` and derives a 4 s dead interval;
- that `check-dead-time` reads this IOS version's `show ip ospf interface`;
- that an inbound ACL drops OSPF addressed to the router, as it dropped BGP on 2026-11-20;
- that Genie reports R2's neighbor as `init` rather than leaving it out (its parser needs the
  `Neighbor priority is N, State is X, N state changes` line);
- that CML accepts `ip proto 89` as a capture filter.

## The iBGP run (prepared, not run)

Every BGP run so far was eBGP between directly connected addresses. This one is iBGP the way it
is usually built: the session runs between the routers' loopbacks, and the loopbacks are
reachable only through OSPF. So BGP depends on OSPF, and one cause should produce findings in
three layers: the OSPF adjacencies, the routes OSPF carried, and the BGP sessions with the
routes they carried.

| | R1 | R2 |
|---|---|---|
| Loopback0, in OSPF, the iBGP endpoint | 10.255.255.1/32 | 10.255.255.2/32 |
| Loopback1, originated into BGP only | 172.16.1.1/24 | 172.16.2.1/24 |

None of these overlaps the lab's own subnets. A router runs one BGP process, so this setup
cannot sit on top of the eBGP one (AS 65001 and 65002): `run-ibgp.sh` starts with
`labctl.py reset`, and stops if the reset fails. Then `labctl.py setup-ibgp` sends each router
(R1 shown; R2 mirrors it):

    interface Loopback0
     ip address 10.255.255.1 255.255.255.255
    interface Loopback1
     ip address 172.16.1.1 255.255.255.0
    interface Ethernet0/1
     ip ospf hello-interval 1
    router ospf 1
     router-id 1.1.1.1
     network 1.1.1.0 0.0.0.255 area 0
     network 10.255.255.1 0.0.0.0 area 0
    router bgp 65010
     bgp router-id 1.1.1.1
     bgp log-neighbor-changes
     neighbor 10.255.255.2 remote-as 65010
     neighbor 10.255.255.2 update-source Loopback0
     neighbor 10.255.255.2 timers 3 9
     address-family ipv4
      network 172.16.1.0 mask 255.255.255.0
      neighbor 10.255.255.2 activate
      neighbor 10.255.255.2 soft-reconfiguration inbound
     exit-address-family

The OSPF part is `setup-ospf-fast`'s lines with Loopback0 added to area 0, and the timers are
the hold-timer run's. `update-source Loopback0` makes each router open the session from its
own loopback, the address the other router names as its neighbor. Loopback1 exists to give BGP
a prefix to originate and is not part of the underlay, so it is not in OSPF. The lab's static
routes do not cover 172.16.0.0/16, so unlike the earlier BGP runs the learned prefix is
installed, and its loss is visible.

The script waits for FULL and runs `check-dead-time`, then waits with `wait-ibgp-up` and runs
`check-ibgp-hold-time` against the loopback peers. `wait-ibgp-up` waits for each session to
have learned at least one prefix, not only for Established: a session that has just come up can
show a prefix count of 0, and the pre capture follows the wait closely. The no-change check then
runs against the draft `scripts/lab/intent-ibgp.yaml`. It names both OSPF adjacencies, both
iBGP sessions (`vrf: default`, `remote_as: 65010`), and each router's two learned routes (the
peer's Loopback0 through OSPF, its Loopback1 prefix through BGP), and requires the hello,
`router bgp 65010`, `remote-as`, `update-source`, and timers lines. A setup that never learned
the BGP prefix, say because a `network` statement was forgotten, fails that check and stops
the run.

The planned change is `labctl.py ospf-block` on R1, the dead-timer run's ACL. Nothing about BGP
is touched. The prediction: R1 loses its OSPF neighbor within about 4 s and with it the route
to 10.255.255.2, and R2 drops to INIT and loses the route to 10.255.255.1. The iBGP sessions do
not reset at once: fast external fallover covers only directly connected eBGP, and
`neighbor ... fall-over` is not configured. Each router's 9 s hold timer runs out about 10 to
14 s after the ACL, and the BGP-learned prefix goes then, or a few seconds earlier when
next-hop tracking finds its next hop unreachable. The script waits with `wait-ospf-lost`, then
`wait-ibgp-down`.

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py` (the BGP
paths are in the by-VRF form new captures use):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (the ACL on R1) | 1 | eight: `V_ADJ` ospf R1 neighbor 2.2.2.2 and R2 neighbor 1.1.1.1; `V_ROUTE` R1 10.255.255.2/32 and R2 10.255.255.1/32 (the peer loopbacks, ospf); `V_ADJ` bgp R1 neighbor 10.255.255.2 and R2 neighbor 10.255.255.1; `V_ROUTE` R1 172.16.2.0/24 and R2 172.16.1.0/24 (bgp) |
| pre vs restored | 0 | none |

No rule names the ACL, so there is no `V_DRIFT`, and the static and connected routes and the
link counters should not move. The synthetic snapshots are built by passing Genie-shaped
data through ncv's own adapter, so the test also fails if the adapter files a neighbor under
the wrong key. The script checks each comparison's exit against this table and exits 0 only
when all three match, 3 when it ran to the end but one did not, and 1 when it stopped early. If
a run stops with the ACL in place, `change.sh deadtimer-undo` removes it, or the next run's
`labctl.py reset` does.

Packet evidence: right before the change the script starts `cml_capture.py start --filter
"ip proto 89 or tcp port 179"`, and at the end it saves `captures/ibgp-<stamp>/link.pcap` and
prints `link_pcap.py`'s timeline of it. The prediction: OSPF hellos every second from both
routers, and BGP keepalives every 3 s between the loopbacks, carried over the link. After the
ACL goes on, R2's hellos keep arriving on the wire while R1's stop listing 2.2.2.2; the
keepalives stop once each router has lost its route to the other's loopback, and no
NOTIFICATION follows. When the hold timer runs out, each router has no route to its peer, so
the NOTIFICATION it logs cannot be sent. That is the opposite of the 2026-11-20 run, where R1
still had the connected route to R2 and its `NOTIFICATION 4/0` was on the wire. After the ACL
comes off: the OSPF exchange, then a new BGP connection (SYN, OPEN with hold time 9, UPDATE,
KEEPALIVE), perhaps after resets answering segments of the old one.

What only the run can confirm:

- the timings and their order: the OSPF loss at about 4 s, then the BGP loss when the 9 s hold
  timer runs out;
- whether Genie labels the learned route `bgp` and the loopback route `ospf`;
- which state Genie captures for the downed sessions (`Idle` or `Active`);
- whether IOS writes each required line as the intent has it;
- whether one console session can still reach both routers while the control plane is down (it
  should: the console does not use the link).

## The BGP VRF run (prepared, not run)

Every BGP capture so far had one session, in the global table. This run adds a second session
to the same peer address inside a VRF, then breaks only that one. It is the live test of ncv
keeping BGP neighbors by VRF: the same address in two VRFs must be captured as two neighbors,
and a change to one must be reported for that one only.

The base is the hold-timer run's eBGP session in the global table (R1 AS 65001, R2 AS 65002,
`timers 3 9`), unchanged and untagged on Ethernet0/1. `run-bgp-vrf.sh` starts with
`labctl.py reset` and stops if it fails. IOS deletes a VRF in the background and refuses its
route distinguisher until it has finished, so on a reservation that already had vrf NCV the
script then waits with `labctl.py wait-vrf-gone 90`, which polls `show vrf` on both routers
until NCV is no longer listed. Then `setup-bgp-fast`, and `labctl.py setup-vrf`, which adds to
the same BGP process (R1 shown; R2 mirrors it with 1.1.1.2, `rd 65002:100`, Loopback100
172.16.102.1/24, neighbor 1.1.1.1 remote-as 65001, and network 172.16.102.0):

    vrf definition NCV
     rd 65001:100
     address-family ipv4
     exit-address-family
    interface Ethernet0/1.100
     encapsulation dot1Q 100
     vrf forwarding NCV
     ip address 1.1.1.1 255.255.255.0
    interface Loopback100
     vrf forwarding NCV
     ip address 172.16.101.1 255.255.255.0
    router bgp 65001
     address-family ipv4 vrf NCV
      neighbor 1.1.1.2 remote-as 65002
      neighbor 1.1.1.2 timers 3 9
      neighbor 1.1.1.2 activate
      neighbor 1.1.1.2 soft-reconfiguration inbound
      network 172.16.101.0 mask 255.255.255.0
     exit-address-family

The order is forced at three points. IOS takes no address on a LAN subinterface before it has
its `encapsulation dot1Q`. `vrf forwarding` strips any address already on the interface, and
in the global table `ip address 1.1.1.1 255.255.255.0` would be refused as overlapping
Ethernet0/1, so `vrf forwarding` comes before `ip address`. And BGP refuses a VRF address
family until the VRF has an `rd`. The subinterface deliberately reuses the global link's
addresses, so 1.1.1.2 is a BGP neighbor twice on R1, once in each table, and 1.1.1.0/24 is
connected twice. Nothing is imported or exported between the tables, so no route target is set.

`show bgp ipv4 unicast summary` lists only the global table, so the VRF commands read
`show bgp vpnv4 unicast vrf NCV summary` and `show bgp vpnv4 unicast vrf NCV neighbors <peer>`
with the parsers the global commands use. The script waits with `wait-bgp-up` and
`wait-vrf-bgp-up`, which waits for each VRF session to have learned at least one prefix, since
the intent names a BGP-learned prefix in the VRF. Then `check-hold-time` and
`check-vrf-hold-time`, and the no-change check against the draft
`scripts/lab/intent-bgp-vrf.yaml`. It names four BGP adjacencies, two per router, one per VRF;
the hold-timer run's routes in the default VRF and, in vrf NCV, each router's connected
1.1.1.0/24 and the other router's Loopback100 network through BGP; Ethernet0/1's counters (not
the subinterface's, which IOS XE does not report); and the hold-timer run's required lines plus
`vrf definition NCV`, `encapsulation dot1Q 100`, and `address-family ipv4 vrf NCV`. The
`remote-as` and `timers` lines appear twice in each running config, and ncv matches a line
without its block, so those rules prove only that one copy exists; `check-vrf-hold-time` is what
proves the VRF session's timers. If the pre capture fails with
`ambiguous BGP neighbor ...: multiple VRFs or instances`, the ncv in that clone predates BGP
neighbors keyed by VRF, and the script says to update it.

The planned change is `labctl.py vrf-shut`: `shutdown` on R1 `interface Ethernet0/1.100`. The
prediction: R1 resets its VRF session at once, because the neighbor is directly connected eBGP
and its interface went down, and it loses the VRF's connected 1.1.1.0/24 and the prefix it
learned. R2's subinterface stays up, since link state belongs to the physical link, so R2 keeps
the session until its 9 s hold timer runs out, then loses the prefix it learned. Both global
sessions stay Established throughout. The script waits with `wait-vrf-bgp-down`.

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py`:

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (`shutdown` on R1 Ethernet0/1.100) | 1 | five, all in vrf NCV: `V_ADJ` R1 neighbor 1.1.1.2 and R2 neighbor 1.1.1.1; `V_ROUTE` R1 1.1.1.0/24 (connected) and 172.16.102.0/24 (bgp); `V_ROUTE` R2 172.16.101.0/24 (bgp) |
| pre vs restored | 0 | none |

Nothing for the default VRF: the same neighbor address there is still Established, and the same
1.1.1.0/24 there is still connected. The synthetic BGP sections are built by passing a
Genie-shaped dict with the same address under `vrf.default` and `vrf.NCV` through ncv's own
adapter, so the test also fails if the adapter merges or drops the VRF neighbor; a mirror test
takes the global sessions down instead and gets findings for the default VRF only. The script
checks each comparison's exit against this table and exits 0 only when all three match, 3 when
it ran to the end but one did not, and 1 when it stopped early. If a run stops with the
subinterface shut, `change.sh vrf-undo` brings it back, or the next run's `labctl.py reset`
removes it.

Packet evidence: right before the change the script starts `cml_capture.py start --filter
"tcp port 179 or (vlan and tcp port 179)"` (a plain `tcp port 179` would not match a tagged
frame), and at the end it saves `captures/bgp-vrf-<stamp>/link.pcap` and prints
`link_pcap.py`'s timeline, which marks the VRF session's segments `vlan 100`. The prediction:
two TCP sessions between the same two addresses, told apart only by the tag. The untagged one
keeps exchanging keepalives. On the tagged one R2 retransmits, then sends
`NOTIFICATION 4/0 Hold Timer Expired`; this time it is R2's NOTIFICATION that reaches the wire,
because R2's side is up, while R1 sends nothing on the tag because its subinterface is down.

What only the run can confirm:

- that IOL accepts a dot1Q subinterface on Ethernet0/1 and the CML link carries the tag;
- that IOS accepts the same neighbor address in the global table and in the VRF;
- how Genie files the VRF neighbor: its IOS XE test data puts it under
  `instance.default.vrf.<name>.neighbor`, which is what ncv expects, and whether the
  per-neighbor commands Genie runs cope with one address in two VRFs;
- that `show bgp vpnv4 unicast vrf NCV summary` and `... neighbors 1.1.1.2` print the formats
  the parsers expect, and that `show vrf` lists NCV while IOS is still deleting it;
- that R1's session resets at once and R2's on its hold timer;
- that CML accepts the `vlan` capture filter.

## Running a session

Run from WSL or Linux: pyATS does not install on native Windows, and the VPN check uses
`ip`. The scripts find the repository root from their own location, so any working
directory works.

1. Reserve the sandbox, connect its VPN, and confirm the console server answers.
   `docs/LIVE.md` has the steps and the traps.
2. `cp testbeds/cml-console.yaml.example testbeds/lab.yaml` (gitignored) and adjust it if
   the lab differs.
3. `.venv/bin/python -m pip install -e '.[dev,lab]'` once. The scripts use
   `.venv/bin/python`; set `NCV_PYTHON` to use another interpreter.
4. `bash scripts/lab/run-lab.sh`, `run-ospf.sh`, `run-bgp.sh`, `run-bgp-holdtimer.sh`, or the prepared `run-ospf-deadtimer.sh`, `run-ibgp.sh`, or `run-bgp-vrf.sh`. Each asks for the CML
   username and password and the routers' enable password, keeps them in that terminal's
   environment (`NCV_CML_USER`, `NCV_CML_PASS`, `NCV_LAB_PASS`), and stops before touching
   the lab if the no-change check is not clean.

`NCV_TESTBED` picks another testbed file for `labctl.py` (a relative path is read from the
repository root), and `labctl.py reset` returns a reused reservation to the shipped
configuration: it removes only what these scripts add, and never touches the management path
or the static routes.

Captures land in `captures/<run>/`, reports and the log in `output/lab/`. Both directories
are gitignored, and the captures hold the lab's running configs.

## Publishing a run

    .venv/bin/python scripts/lab/sanitize_capture.py captures/run-<stamp> fixtures/lab-<date>/<run>

The sanitizer knows the forms the sandbox routers carried: `enable password|secret`,
`username ... password|secret`, the indented `password` of a console or vty line, and the
body of a `certificate self-signed|ca` block. It changes nothing else, so read the copy
before committing it, and write a `SOURCE.md` beside it recording the environment, the
date, and exactly what was removed, as `fixtures/lab-2026-09-12/SOURCE.md` does.
`tests/test_lab_scripts.py` pins the rules and checks that the published configs are the
script's own fixed point.
