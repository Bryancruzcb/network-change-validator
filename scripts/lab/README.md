# Lab scripts

The operator side of the 2026-09-12, 2026-09-18, and 2026-11-20 lab runs, kept here so the
evidence under `fixtures/lab-*` can be reproduced and its sanitization rerun. They are written
for the Cisco DevNet "Cisco Modeling Labs" sandbox and its preloaded `default-lab` (R1 and
R2 joined on Ethernet0/1), for an isolated lab you are authorized to use, and they are
deliberately outside `ncv`: `ncv` never pushes configuration, and these scripts do. They set
each run up, make the one planned change the captures are meant to catch, and
`labctl.py reset` removes what they added. One more thing changes the lab itself rather than a
router's configuration: `cml_lab.py add-r3` adds a third router and its link to `default-lab`
for the second-platform run, and `cml_lab.py remove-r3` takes them out again.

| Script | What it does |
|---|---|
| `run-lab.sh` | The static-route run in one command: pre capture, no-change check, `shutdown` on R1 Ethernet0/1, post capture and compare, `no shutdown`, restored capture and compare. |
| `run-ospf.sh` | The OSPF run: sets up OSPF area 0 on the R1-R2 link, waits for FULL, then the same sequence, waiting for both neighbor entries to clear before the post capture. |
| `run-bgp.sh` | The BGP run: sets up eBGP between R1 and R2, waits for Established, then the same sequence around `neighbor 1.1.1.2 shutdown` on R1. |
| `run-bgp-holdtimer.sh` | The hold-timer run: eBGP with a 9 s hold time, then the same sequence around an inbound ACL on R1 that drops BGP from R2. |
| `run-ospf-deadtimer.sh` | The OSPF dead-timer run, prepared and not run: OSPF with a 1 s hello (so a 4 s dead interval), then the same sequence around an inbound ACL on R1 that drops OSPF from R2, with a packet capture of `ip proto 89`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its `expect-*.txt` file. |
| `run-ibgp.sh` | The iBGP run, prepared and not run: iBGP between the routers' loopbacks, which reach each other only over OSPF, then the same sequence around the dead-timer run's OSPF ACL on R1, with a packet capture of `ip proto 89 or tcp port 179`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its `expect-*.txt` file. |
| `run-bgp-vrf.sh` | The BGP VRF run, prepared and not run: the hold-timer run's eBGP session plus a second one to the same peer address in vrf NCV on the dot1Q subinterface Ethernet0/1.100, then the same sequence around `shutdown` on R1's subinterface, with a packet capture of `tcp port 179 or (vlan and tcp port 179)`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its `expect-*.txt` file. |
| `run-second-platform.sh` | The second-platform run, prepared and not run: `run-second-platform.sh nxosv9000\|cat8000v\|iosv` adds R3, a router of that platform, with `cml_lab.py add-r3`, links it to R1 Ethernet0/3, sets up OSPF and eBGP between R1 and R3, then the same sequence around `shutdown` on R1 Ethernet0/3, captured on all three routers. It refuses an unknown platform, or a testbed whose R3 has another `os`, before asking for any login. It sources `_lib.sh`, exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its platform's `expect-*.txt` file, and leaves R3 in the lab. |
| `run-ssh-path.sh` | The SSH path run, prepared and not run: captures the routers through the console server and then over SSH to their management addresses, and expects `compare_captures.py` and `ncv diff` against the shipped lab's intent to find no difference between the two. It exits 4, a result rather than a failure, when the management addresses do not accept TCP port 22. Its only change to the lab is `labctl.py reset`. |
| `probe.sh` | The read-only probe: from this machine, the VPN route, a TCP test of ports 22 and 23, and a ping to both management addresses; then `cml_lab.py inspect`; then `labctl.py probe` on both routers; then three answers, each with the line it came from. It changes nothing on any device or in CML. |
| `capture.sh` | One capture (`pre`, `post`, or `restored`) for a run driven by hand. |
| `change.sh` | The planned change by hand: `apply` shuts R1 Ethernet0/1 and `undo` brings it back; `bgp-apply` shuts the R1 peer and `bgp-undo` brings it back; `holdtimer-apply` adds the BGP ACL and `holdtimer-undo` removes it; `deadtimer-apply` adds the OSPF ACL and `deadtimer-undo` removes it; `vrf-apply` shuts R1 Ethernet0/1.100 and `vrf-undo` brings it back; `r3-apply` shuts R1 Ethernet0/3, the link to R3, and `r3-undo` brings it back. |
| `_lib.sh` | Sourced, not run: what new run scripts share. `lab_init` checks the VPN and the testbed file, asks for each login that is not set (again until it is not empty, and without `bash -x` printing it; the routers' SSH login too when the testbed names `NCV_SSH_PASS`), sets the capture and report paths (`NCV_STAMP` fixes the stamp), and installs an exit trap that stops a packet capture an early exit left running. Then `step`, `ctl`, `cap`, `snap`, `compare`, `lab_reset` (stops the run when `labctl.py reset` fails), `cap_start` and `cap_stop`, `expect_exit` and `expect_findings`, `lab_tcp` (a 3 s TCP test that tells an open port from a refused one and from no answer), `lab_not_reachable` (exit 4: the devices do not answer on the path a run tests), and `lab_finish`, which ends a run with exit 0 when every comparison gave its predicted exit and the change comparison its predicted findings, 3 when one did not, and warns if a password value reached the log. The four published runs keep their own copy, since they reproduce recorded runs. |
| `check_findings.py` | Compares a report's findings, as (policy, device, path), with an expected file: exit 0 when they are the same, 1 with a `missing:` or `unexpected:` line for each difference, 2 on bad usage or input it cannot read. `_lib.sh`'s `expect_findings` runs it. |
| `compare_captures.py` | Whether two snapshots hold the same data: exit 0 when they do, 1 with a `<section>.<path>: <a> != <b>` line per difference (at most 40, then the count), 2 on bad usage or a section file it cannot read. It ignores `SOURCE.json` and `raw/`, compares running configs line by line, and never prints a config line that may hold a secret. |
| `expect-ospf-deadtimer.txt`, `expect-ibgp.txt`, `expect-bgp-vrf.txt`, `expect-second-platform-<platform>.txt` | The predicted findings of each prepared run's change comparison (one file per R3 platform for the second-platform run), one `<policy> <device> <path>` per line, written before any capture exists. The run script checks its report against its file, and `tests/test_lab_scripts.py` reads the same file to pin the prediction. Each moves next to its evidence with the draft intent once a run is recorded. |
| `labctl.py` | The lab actions the scripts above call: `setup-ospf`, `shut`, `noshut`, `wait-full`, `wait-gone`, `setup-bgp`, `bgp-shut`, `bgp-noshut`, `wait-bgp-up`, `wait-bgp-down`, `setup-bgp-fast`, `check-hold-time`, `bgp-block`, `bgp-unblock`, `setup-ospf-fast`, `check-dead-time`, `ospf-block`, `ospf-unblock`, `wait-ospf-lost`, `setup-ibgp`, `wait-ibgp-up`, `wait-ibgp-down`, `check-ibgp-hold-time`, `wait-vrf-gone`, `setup-vrf`, `wait-vrf-bgp-up`, `wait-vrf-bgp-down`, `check-vrf-hold-time`, `vrf-shut`, `vrf-noshut`, `setup-r3-link`, `wait-r3-up`, `wait-r3-down`, `r3-shut`, `r3-noshut`, `reset`, which removes what these scripts add from both routers, and `probe`, which only reads. The R3 commands touch R1 alone: R3 is configured only by the day-0 configuration cml_lab.py gives it when it adds the node. |
| `sanitize_capture.py` | Copies a run's `pre/`, `post/`, `restored/` for publishing with passwords and certificate bodies replaced and `raw/` left out. It also knows NX-OS's documented `username ... password` and `snmp-server user ... auth` forms, which no capture has shown yet. |
| `bgp_pcap.py` | Lists the BGP messages in a pcap of the lab link: TCP flags, retransmissions, and each message by name, with NOTIFICATION error codes spelled out. |
| `link_pcap.py` | One timeline of the OSPF packets and BGP segments in a pcap of the lab link: each OSPF packet by type (a hello's timers, DR, BDR, and neighbor list; a database description's flags; an update's LSA count) and each BGP segment as `bgp_pcap.py` shows it, tagged with its VLAN when it has one. |
| `cml_capture.py` | Starts and saves a packet capture of the R1-R2 link through the CML API (`start [--filter "<bpf expression>"]`, default `tcp port 179`, and `stop <file.pcap>`), with the CML login the run scripts already hold. |
| `cml_lab.py` | The CML side of the lab. `inspect [<output dir>]` and `check-login` only read: the inventory gives the controller's version, node and image definitions, memory and CPU in use, and default-lab's nodes, interfaces, and links, ending with whether R1 Ethernet0/3 is free and which of `nxosv9000`, `cat8000v`, and `iosv` are available; every call is a GET, and configurations, notes, and descriptions are dropped before anything is printed or saved. `check-login` exits 0 when CML accepts the login and 1 when it does not. `add-r3 <platform>` and `remove-r3` change the lab's topology: they add R3 with its day-0 configuration, link it to R1 Ethernet0/3, and boot it, or stop, wipe, and delete it and its link. `platform-os <platform>` prints the pyATS `os` R3's testbed entry needs, with no login and no call. |

The runs compare against the intents kept with their evidence
(`fixtures/lab-2026-09-12/intent-routes.yaml` and `intent-ospf.yaml`,
`fixtures/lab-2026-09-18/intent-bgp.yaml`, and
`fixtures/lab-2026-11-20/intent-bgp-holdtimer.yaml`), so a rerun on the
same sandbox is checked against the same rules. A prepared run's draft intent sits here in
`scripts/lab` (`intent-ospf-deadtimer.yaml`, `intent-ibgp.yaml`, `intent-bgp-vrf.yaml`, and
`intent-second-platform-<platform>.yaml`, one per R3 platform), with the predicted findings of
its change comparison beside it (`expect-<run>.txt`), until a run is recorded.

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
has a record in the wrong state; the test asserts that evidence too, and builds its OSPF
sections by passing Genie-shaped data through ncv's own adapter. No rule names the ACL, so
there is no `V_DRIFT`. The change comparison's two findings live in
`expect-ospf-deadtimer.txt`, which the test reads and the script checks its report against: it
exits 0 only when all three comparisons give the exits in this table and the change
comparison finds exactly those two findings, 3 when it ran to the end but one did not, and 1
when it stopped early. If a run stops with the ACL in place, `change.sh deadtimer-undo` removes
it, or the next run's `labctl.py reset` does.

Packet evidence: right before the change the script starts `cml_capture.py start --filter
"ip proto 89"`, and at the end it saves `captures/ospf-deadtimer-<stamp>/link.pcap` and prints
`link_pcap.py`'s timeline of it. The prediction: hellos every second from both routers; after
the ACL goes on, R2's hellos keep arriving on the wire and keep listing 1.1.1.1, while R1's
hellos list no neighbor from about 4 s on; after the ACL comes off, database description, link
state request, update, and acknowledgment packets as the adjacency forms again. The DR and BDR
fields are not part of the prediction: with a 4 s wait timer the router configured first is
likely DR before the change, and 2.2.2.2 wins after recovery; ncv does not compare them.

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
the wrong key. The eight findings live in `expect-ibgp.txt`, which the test reads and the
script checks its change report against: it exits 0 only when all three comparisons give the
exits in this table and the change comparison finds exactly those eight, 3 when it ran to the
end but one did not, and 1 when it stopped early. If a run stops with the ACL in place, `change.sh deadtimer-undo` removes it, or the next run's
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
KEEPALIVE), perhaps after resets answering segments of the old one. As in the dead-timer run,
the hellos' DR and BDR fields are not predicted, and ncv does not compare them.

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
takes the global sessions down instead and gets findings for the default VRF only. The five
findings live in `expect-bgp-vrf.txt`, which the test reads and the script checks its change
report against: it exits 0 only when all three comparisons give the exits in this table and
the change comparison finds exactly those five, 3 when it ran to the end but one did not, and 1
when it stopped early. If a run stops with the
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

## The second-platform run (prepared, not run)

Everything published so far comes from one image, IOS XE 17.15 on IOL. This run adds a third
router, R3, on another platform, joined to R1, and breaks the link from R1's end: an adjacency
lost and seen from both ends, one end on each platform. It is the first test of ncv's adapter
on Genie data shaped by another platform, and more of it is unverified than of any other run:
nobody has listed the sandbox's images, added a node through its API, or connected Unicon to an
NX-OS console there. Each unknown is written to fail early with a message that says what to
look at; the list at the end of this section names them.

The topology change is `cml_lab.py add-r3 <platform>`, through the CML API, stopping with exit 1
and a one-line reason at the first thing that is not as it needs:

1. the platform's node definition exists and has an image;
2. no node is labelled R3 (one that is already booted with the same node definition is exit 0,
   one still starting is waited for, anything else is refused, naming `remove-r3`);
3. R1 Ethernet0/3 exists in the topology and is not connected;
4. free memory, from `/system_stats`, is not plainly short of the node definition's RAM (it
   prints both numbers, and skips the check when either is missing);
5. it creates the node with its day-0 configuration
   (`POST /labs/{id}/nodes?populate_interfaces=true`), reads it back once, and checks that CML
   kept the configuration (its `hostname R3` line, read as a boolean and never printed);
6. it links R3's first data interface to R1 Ethernet0/3 (`POST /labs/{id}/links`);
7. it starts R3 and polls its state every 15 s, printing each, for at most 20 minutes, giving up
   after 3 minutes still `QUEUED` or `DEFINED_ON_CORE` (`CML has not started R3`);
8. once R3 is `BOOTED`, it starts the link if it is not `STARTED` and stops if it still is not.

Every failure after the node exists ends with `R3 was created; cml_lab.py remove-r3 removes it`.
The day-0 configuration holds R3's admin password (`NCV_LAB_PASS`), so it is echoed with
`<removed>` in its place, the node POST's response is never printed, and every message passes
through one `redact` function. `cml_lab.py remove-r3` reads R3's state, stops it unless it is
already stopped, waits up to 3 minutes for `STOPPED`, wipes its disks, deletes its link and then
the node, and treats a missing R3, or a 404 on the way, as already gone. The run leaves R3 in
the lab; `remove-r3` is a separate step.

The platforms, from `cml_lab.py`'s table:

| Platform | Node definition | pyATS `os` | R3's first data interface | Connected routes |
|---|---|---|---|---|
| NX-OS 9000v | `nxosv9000` | `nxos` | Ethernet1/1 | `direct` |
| Catalyst 8000V | `cat8000v` | `iosxe` | GigabitEthernet1 | `connected` |
| IOSv | `iosv` | `ios` | GigabitEthernet0/0 | `connected` |

R3's day-0 configuration on NX-OS, as `add-r3` echoes it (the IOS form is the same router in IOS
syntax: `network` statements for OSPF, `neighbor 10.1.3.1 timers 3 9`, no dead-interval line,
since IOS derives 4 s from the 1 s hello, and no console login):

    hostname R3
    no password strength-check
    username admin password <removed> role network-admin
    feature ospf
    feature bgp
    interface loopback0
      ip address 3.3.3.3/32
      ip router ospf 1 area 0.0.0.0
    interface loopback1
      ip address 172.16.3.1/24
    interface Ethernet1/1
      no switchport
      ip address 10.1.3.3/24
      ip ospf hello-interval 1
      ip ospf dead-interval 4
      ip router ospf 1 area 0.0.0.0
      no shutdown
    router ospf 1
      router-id 3.3.3.3
    router bgp 65003
      router-id 3.3.3.3
      address-family ipv4 unicast
        network 172.16.3.0/24
      neighbor 10.1.3.1
        remote-as 65001
        timers 3 9
        address-family ipv4 unicast

R3 is never configured after that: `labctl.py` configures R1's side only, so no NX-OS
configuration dialect enters it. `labctl.py setup-r3-link` adds to the processes `setup-ospf`
and `setup-bgp` create:

    interface Ethernet0/3
     ip address 10.1.3.1 255.255.255.0
     ip ospf hello-interval 1
     no shutdown
    router ospf 1
     network 10.1.3.0 0.0.0.255 area 0
    router bgp 65001
     neighbor 10.1.3.3 remote-as 65003
     neighbor 10.1.3.3 timers 3 9
     address-family ipv4
      neighbor 10.1.3.3 activate
      neighbor 10.1.3.3 soft-reconfiguration inbound
     exit-address-family

Set up: `cp testbeds/cml-console-r3.yaml.example testbeds/lab-r3.yaml` (gitignored). It reaches
R1 and R2 as `cml-console.yaml.example` does and R3 through the same console server
(`open /default-lab/R3/0`). NX-OS asks for its own login after the CML one, so R3's connection
lists `login_creds: [default, nxos]` next to `command:` (under `arguments:` Unicon ignores it),
with the `nxos` credential the admin user `add-r3` created; the example's header shows the IOS
form for the other two platforms, whose console has no login. ncv's capture refuses to answer a
first-boot setup dialog (NX-OS POAP, its admin-password prompt, the IOS setup dialog): Unicon
would otherwise answer it and so configure the device during a capture.

`run-second-platform.sh <platform>` first checks the platform against `cml_lab.py`'s table and
that `testbeds/lab-r3.yaml` (or `NCV_TESTBED`) gives R3 that platform's `os`, before it asks for
any login. Then:

1. `labctl.py reset` on R1 and R2, which also returns Ethernet0/3 to what ships;
2. `cml_lab.py add-r3 <platform>`, stopping if it refuses;
3. `setup-ospf`, `setup-bgp`, `setup-r3-link`;
4. `wait-r3-up 600`, judged from R1 only: OSPF neighbor 3.3.3.3 FULL and BGP neighbor 10.1.3.3
   Established with at least one prefix received. On a timeout it prints R1's
   `show interfaces Ethernet0/3 | include line protocol` and `show cdp neighbors`, which tell a
   link that never came up from an R3 whose configuration is wrong;
5. pre capture of all three routers with `ospf,bgp,routing,interface`;
6. the no-change check against `intent-second-platform-<platform>.yaml`, which must exit 0;
7. the change: `labctl.py r3-shut`, `shutdown` on R1 Ethernet0/3;
8. `wait-r3-down 60`, then a fixed 15 s for R3's own 4 s dead interval and 9 s hold time;
9. post capture and compare, expecting exit 1 and the platform's expected findings;
10. `r3-noshut` and `wait-r3-up 300`;
11. restored capture and compare, expecting exit 0.

There is one draft intent per platform, because the strings differ. Each names devices R1 and
R3; the OSPF adjacencies (R1 neighbor 3.3.3.3 on Ethernet0/3, R3 neighbor 1.1.1.1 on its first
data interface) and the BGP ones (R1 neighbor 10.1.3.3 remote AS 65003, R3 neighbor 10.1.3.1
remote AS 65001, both in vrf default); R1's routes 10.1.3.0/24 connected, 3.3.3.3/32 ospf, and
172.16.3.0/24 bgp, and R3's 10.1.3.0/24 (`direct` on NX-OS, `connected` on IOS), 1.1.1.0/24
ospf, and 10.10.10.0/24 bgp; the counters of R1 Ethernet0/3 and R3's first data interface; R1's
lines `ip address 10.1.3.1 255.255.255.0`, `network 10.1.3.0 0.0.0.255 area 0`,
`neighbor 10.1.3.3 remote-as 65003`, and `neighbor 10.1.3.3 timers 3 9`, and for R3 only
`router bgp 65003`, since no capture exists to copy its lines from. The three files differ only
in R3's interface name and its connected-route string. ncv does not alias `direct` to
`connected` or fold `Mgmt0` to `mgmt0`: an intent copies what the device's capture says. These
strings come from Genie's parsers and test data, not from a device, so the first pre capture
may correct them, and the no-change check is what will say so; the script then says to correct
the intent from `captures/second-platform-<stamp>/pre` and rerun.

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py`:

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (`shutdown` on R1 Ethernet0/3) | 1 | nine: `V_ADJ` ospf and bgp on R1 (neighbors 3.3.3.3 and 10.1.3.3) and on R3 (neighbors 1.1.1.1 and 10.1.3.1); `V_ROUTE` R1 10.1.3.0/24, 3.3.3.3/32, and 172.16.3.0/24; `V_ROUTE` R3 1.1.1.0/24 and 10.10.10.0/24 |
| pre vs restored | 0 | none |

R3's own 10.1.3.0/24 stays: the nine assume R3's interface stays up when R1 shuts its end,
because CML does not pass carrier across a link. If it does go down, R3 also loses that route
and the run gives ten; the expected files say so in their comments. The findings are the same
for all three platforms and live in `expect-second-platform-<platform>.txt`, which the test
reads and the script checks its change report against. The synthetic snapshots are built
through ncv's own adapter from Genie's shapes, R3's as each platform writes them (on NX-OS:
lowercase BGP states, `direct`, and interface records that carry no status, which ncv keeps as
unknown), and a further test shows that an R3 capture saying `connected` fails the NX-OS
draft's no-change check with one `V_ROUTE`: the platform's strings are part of the intent. If a
run stops with Ethernet0/3 shut, `change.sh r3-undo` brings it back, or the next run's
`labctl.py reset` puts the port back as it ships.

Assumptions the first session must check, each with how it fails:

- **Try the platforms in the order `iosv`, `cat8000v`, `nxosv9000`.** IOSv is light, boots in a
  few minutes, and needs neither a licence nor a boot line; NX-OS 9000v needs about 8 GB and up
  to 15 minutes. `probe.sh` says which have a node definition and an image first.
- **The image exists.** `add-r3` refuses before any change: `the controller has no node
  definition <platform>` or `node definition <platform> has no image`.
- **R1 Ethernet0/3 is in the topology and free.** `add-r3` refuses, naming the link that uses it.
- **CML can add a link to R1 while it runs.** Unverified; R1 Ethernet0/3 already exists, so no
  interface is hot-added. If not, the link POST fails: `could not link R1 Ethernet0/3 to R3:
  ... (whether CML links a running R1 is unverified)`, and R3 is left for `remove-r3`.
- **The form of `configuration` the API accepts.** `add-r3` sends one string; Cisco's client
  also sends a list of named files. If CML drops it, `add-r3` stops with `CML did not keep the
  day-0 configuration` before starting R3. If CML keeps it but R3 boots without applying it, R3
  comes up unconfigured and `wait-r3-up` times out with R1's line protocol up and no OSPF.
- **The image's `boot nxos bootflash:...` line.** A custom day-0 configuration may replace CML's
  template, which carries that line and the management VRF. Symptom: R3's console sits at
  `loader>` and the boot never completes; `add-r3`'s 20-minute wait times out.
- **The interface labels.** `Ethernet1/1`, `GigabitEthernet1`, and `GigabitEthernet0/0` come
  from CML's documentation, not from a node this controller created. If R3 has no interface by
  that label, `add-r3` stops and lists the labels it has.
- **Boot time and memory.** `add-r3` refuses up front when free memory is plainly short; CML may
  still refuse the start (`CML has not started R3 (memory or licence; see cml_lab.py inspect)`
  after 3 minutes), or a slow boot may outlast the 20-minute wait.
- **The console path and login chain for R3.** `open /default-lab/R3/0`, then for NX-OS the
  admin login, were checked only against Unicon's mock devices. If either is wrong, the pre
  capture fails at connect for R3; a device left at a first-boot dialog fails it the same way.
- **Genie's NX-OS shapes on a real 9000v.** Taken from Genie's test data. A shape the adapter
  does not handle fails the pre capture at a named learn; a string that differs (`direct`, an
  interface name, a state) is named by the no-change check.
- **R3's interface stays up when R1 shuts its end.** If not, the change comparison has a tenth
  finding, and `check_findings.py` names it as unexpected.
- **An R3 capture must be read line by line before it is published.** `sanitize_capture.py`'s
  NX-OS rules (`username ... password <type> <hash> role ...` and `snmp-server user ... auth
  ... localizedkey`) were written from NX-OS's documented forms, not from a capture.

## The probe

Two things decide what the next runs can do, and nothing here may guess them: whether the
routers' management addresses (10.10.20.171 and .172, on Ethernet0/2 in vrf Mgmt-intf) answer
over the sandbox VPN, and which node images the controller has. On 2026-09-12 the management
addresses did not answer, and nobody recorded why. `probe.sh` asks, and changes nothing: it
sends no configuration to any device, every CML call is a GET, and `show running-config` is
not among the router commands.

1. From this machine: `ip -brief addr show tun0`, `ip route get 10.10.20.171`, and for each
   management address a TCP test of ports 22 and 23 and `ping -c 2 -W 2`. The TCP test has
   three outcomes, and the difference is the question 2026-09-12 left open: `open`, `refused`
   (the host answered), and `no answer in 3 s` (filtered or not routed).
2. `cml_lab.py inspect output/lab/probe-<stamp>-cml`: the CML version, the node and image
   definitions, memory and CPU in use, and default-lab's nodes, interfaces, and links. Each
   response is saved there as JSON, without configurations, notes, or descriptions. Several
   response shapes are unverified, so a missing field prints as unknown and a call that fails
   is reported and skipped.
3. `labctl.py probe`, through the console testbed: on R1 and then R2, the management path
   (`show ip interface brief`, `show vrf`, the Mgmt-intf route and ARP tables, `show ip ssh`,
   `show users`, and pings in vrf Mgmt-intf to the gateway 10.10.20.254 and the controller
   10.10.20.161), what Ethernet0/0 and Ethernet0/3 connect to (`show cdp neighbors`,
   `show interfaces Ethernet0/3`), and `show version | include Version`. A command the router
   rejects is printed with its error and the probe goes on. It asks nothing about OSPF or BGP:
   a fresh or reset lab runs neither, and the gate commands print that text during the runs.
4. Three answers, each with the line it came from: do the management addresses answer on port
   22; is R1 Ethernet0/3 free; which of `nxosv9000`, `cat8000v`, and `iosv` have a node
   definition and at least one image.

Everything goes to the screen and to `output/lab/probe-<stamp>.log`. It exits 1 when the CML
login or the console connection to a router fails, since every run needs both, and 0
otherwise.

## The SSH path (prepared, not run)

Every capture so far reached the routers through the CML console server. `run-ssh-path.sh`
tests one claim: the access path does not change the evidence. It captures the same routers
twice in a row, through the console server and then over SSH to their management addresses,
and changes nothing in the lab except `labctl.py reset`, which returns a used reservation to
the shipped configuration.

Set up: `cp testbeds/cml-ssh.yaml.example testbeds/lab-ssh.yaml` (gitignored). It reaches R1 at
10.10.20.171 and R2 at 10.10.20.172 on port 22, logs in as the router's local user
(`NCV_SSH_USER`, default `cisco`, and `NCV_SSH_PASS`), and answers the `enable` prompt Unicon
always sends on IOS XE with `NCV_LAB_PASS`. Host keys go to `output/lab/known_hosts`, which the
run deletes before its SSH capture: a new reservation gives the routers new keys, and ssh
refuses a changed one. With that file in place, any run script works over SSH with
`NCV_TESTBED=testbeds/lab-ssh.yaml`, because `_lib.sh` asks for the SSH login whenever the
testbed names it.

The steps:

1. Check that `testbeds/lab-ssh.yaml` exists and ask for the logins, the SSH one included.
2. Port check: both management addresses must accept TCP port 22. If not, the script exits 4
   before anything is reset or captured.
3. `labctl.py reset` through the console testbed, so the routers carry the configuration the
   published intent describes. If it fails, the run stops as the other runs do.
4. Capture `console` through `testbeds/lab.yaml`, with `routing,interface`.
5. Capture `ssh` through `testbeds/lab-ssh.yaml`, with the same features.
6. `compare_captures.py captures/ssh-path-<stamp>/console captures/ssh-path-<stamp>/ssh`.
7. `ncv diff` of the two against `fixtures/lab-2026-09-12/intent-routes.yaml`, the intent of
   the shipped lab.

There is no draft intent: the run reuses that published one and makes no change. The prediction:

| Comparison | Exit | Findings |
|---|---|---|
| `compare_captures.py` console vs ssh | 0 | none: the same data in all five sections |
| `ncv diff` console vs ssh, against `intent-routes.yaml` | 0 | none |

The script exits 0 only when both give 0, 3 when it ran to the end but one did not, 4 when the
management addresses do not answer, 1 when it stopped early, and 2 when it could not start.
`tests/test_compare_captures.py` pins the comparison on invented snapshots, and
`tests/test_lab_scripts.py` pins the testbed example and the order of the steps; no capture
over SSH exists yet.

If the port check fails, the result is "not reachable in this sandbox". That is a finding about
the sandbox, not a failure of the script: run `probe.sh` again to record its reasons in the
log, and the console server stays the only path.

What only the run can confirm:

- whether the management addresses answer over the VPN at all;
- whether the routers' SSH server accepts the client's key exchange and host key algorithms;
- whether the local user lands in user EXEC and needs `enable`, and whether Unicon handles it
  with the `enable` credential as it did against a mock;
- whether the two captures are identical, or differ in some field the console path renders
  differently.

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
   the lab if the no-change check is not clean. A prepared run exits 0 when every comparison
   gave its predicted exit and the change comparison its predicted findings, 3 when it ran to
   the end but did not, 1 when it stopped early, and 2 when it could not start (no VPN, no
   testbed file, or no answer to a login prompt). One that stops early still stops and saves
   its packet capture on the way out.

`probe.sh` takes the same logins and is safe to run first on any reservation: it only reads.
`run-ssh-path.sh` also needs `testbeds/lab-ssh.yaml` and asks for the routers' SSH login, and
its exit 4 means the management addresses do not answer in this sandbox, a result recorded
before anything is reset or captured, not a run that stopped early.
`run-second-platform.sh <platform>` needs `testbeds/lab-r3.yaml`, adds R3 to the lab, and
leaves it there: `.venv/bin/python scripts/lab/cml_lab.py remove-r3`, with the CML login in
`NCV_CML_USER` and `NCV_CML_PASS`, takes it out.

`NCV_TESTBED` picks another testbed file for `labctl.py` (a relative path is read from the
repository root), and `labctl.py reset` returns a reused reservation to the shipped
configuration: it removes only what these scripts add (the `NCV-` ACLs, `router bgp` 65001,
65002, and 65010, `router ospf 1`, the link's shutdown and OSPF timers, Loopback0, Loopback1,
Loopback100, Ethernet0/1.100, a reused Ethernet0/3, and vrf NCV), and never touches the
management path or the
static routes. It never touches R3 either; `cml_lab.py remove-r3` removes it. The gate commands `check-hold-time`, `check-dead-time`, `check-ibgp-hold-time`,
and `check-vrf-hold-time` print each router's show command and the raw output they parsed
before their reading, so the run log keeps the real text: no capture holds it yet.

Captures land in `captures/<run>/`, reports and the log in `output/lab/`. Both directories
are gitignored, and the captures hold the lab's running configs.

## Publishing a run

    .venv/bin/python scripts/lab/sanitize_capture.py captures/run-<stamp> fixtures/lab-<date>/<run>

The sanitizer knows the forms the sandbox routers carried: `enable password|secret`,
`username ... password|secret`, the indented `password` of a console or vty line, and the
body of a `certificate self-signed|ca` block. For an NX-OS R3 it also replaces the hash in
`username <name> password <type> <hash> role ...` and everything from `auth` on in
`snmp-server user ... localizedkey`, forms written from NX-OS's documentation rather than a
capture, so read an R3 capture line by line. It changes nothing else, so read the copy
before committing it, and write a `SOURCE.md` beside it recording the environment, the
date, and exactly what was removed, as `fixtures/lab-2026-09-12/SOURCE.md` does.
`tests/test_lab_scripts.py` pins the rules and checks that the published configs are the
script's own fixed point.
