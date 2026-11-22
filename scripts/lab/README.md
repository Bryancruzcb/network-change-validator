# Lab scripts

The operator side of the 2026-09-12, 2026-09-18, 2026-11-20, and 2026-11-21 lab runs, kept
here so the evidence under `fixtures/lab-*` can be reproduced and its sanitization rerun. They
are written for the Cisco DevNet "Cisco Modeling Labs" sandbox and its preloaded `default-lab`
(R1 and R2 joined on Ethernet0/1), for an isolated lab you are authorized to use, and they are
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
| `run-ospf-deadtimer.sh` | The OSPF dead-timer run, recorded on 2026-11-21 (`fixtures/lab-2026-11-21/ospf-deadtimer`): OSPF with a 1 s hello (so a 4 s dead interval), then the same sequence around an inbound ACL on R1 that drops OSPF from R2, with a packet capture of `ip proto 89`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its `expect-*.txt` file. |
| `run-ibgp.sh` | The iBGP run, recorded on 2026-11-21 (`fixtures/lab-2026-11-21/ibgp`): iBGP between the routers' loopbacks, which reach each other only over OSPF, then the same sequence around the dead-timer run's OSPF ACL on R1, with a packet capture of `ip proto 89 or tcp port 179`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its `expect-*.txt` file. |
| `run-bgp-vrf.sh` | The BGP VRF run, recorded on 2026-11-21 (`fixtures/lab-2026-11-21/bgp-vrf`): the hold-timer run's eBGP session plus a second one to the same peer address in vrf NCV on the dot1Q subinterface Ethernet0/1.100, then the same sequence around `shutdown` on R1's subinterface, with a packet capture of `tcp port 179 or (vlan and tcp port 179)`. It sources `_lib.sh` and exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its `expect-*.txt` file. |
| `run-second-platform.sh` | The second-platform run, recorded on 2026-11-21 with R3 on IOSv (`fixtures/lab-2026-11-21/second-platform-iosv`); an NX-OS attempt the same day stopped before any capture, and Catalyst 8000V has not run: `run-second-platform.sh nxosv9000\|cat8000v\|iosv` adds R3, a router of that platform, with `cml_lab.py add-r3`, links it to R1 Ethernet0/3, sets up OSPF and eBGP between R1 and R3, then the same sequence around `shutdown` on R1 Ethernet0/3, captured on all three routers. It refuses an unknown platform, or a testbed whose R3 has another `os`, before asking for any login. It sources `_lib.sh`, exits 0 only when every comparison exits as predicted and the change comparison finds exactly the findings in its platform's `expect-*.txt` file, and leaves R3 in the lab. |
| `run-ssh-path.sh` | The SSH path run, prepared and not run (the 2026-11-21 probe found port 22 silent on both management addresses): captures the routers through the console server and then over SSH to their management addresses, and expects `compare_captures.py` and `ncv diff` against the shipped lab's intent to find no difference between the two. It exits 4, a result rather than a failure, when the management addresses do not accept TCP port 22. Its only change to the lab is `labctl.py reset`. |
| `probe.sh` | The read-only probe: from this machine, the VPN route, a TCP test of ports 22 and 23, and a ping to both management addresses; then `cml_lab.py inspect`; then `labctl.py probe` on both routers; then three answers, each with the line it came from. It changes nothing on any device or in CML. |
| `run-session.sh` | A whole session with one login: `run-session.sh [name ...]` checks every name and the VPN, asks for the logins once (the routers' SSH login only when `ssh-path` is named), checks the CML login with `cml_lab.py check-login`, then runs `probe`, `ospf-deadtimer`, `ibgp`, `bgp-vrf`, `ssh-path`, `second-platform:<platform>`, `reset`, or `remove-r3` in the order given (by default `probe ospf-deadtimer ibgp bgp-vrf reset`), and ends with a table of each run's exit status, what it means, and where its log is. Before any prompt it also checks the testbed file each named run needs. `reset` and `remove-r3` run `labctl.py reset` and `cml_lab.py remove-r3` with the logins it asked for. It drove the three sessions of 2026-11-21. |
| `capture.sh` | One capture (`pre`, `post`, or `restored`) for a run driven by hand. |
| `change.sh` | The planned change by hand: `apply` shuts R1 Ethernet0/1 and `undo` brings it back; `bgp-apply` shuts the R1 peer and `bgp-undo` brings it back; `holdtimer-apply` adds the BGP ACL and `holdtimer-undo` removes it; `deadtimer-apply` adds the OSPF ACL and `deadtimer-undo` removes it; `vrf-apply` shuts R1 Ethernet0/1.100 and `vrf-undo` brings it back; `r3-apply` shuts R1 Ethernet0/3, the link to R3, and `r3-undo` brings it back. |
| `_lib.sh` | Sourced, not run: what new run scripts share. `lab_init` checks the VPN and the testbed file, asks for each login that is not set (through `lab_vpn_up` and `lab_logins`, which `run-session.sh` uses too) (again until it is not empty, and without `bash -x` printing it; the routers' SSH login too when the testbed names `NCV_SSH_PASS`), sets the capture and report paths (`NCV_STAMP` fixes the stamp), and installs an exit trap that stops a packet capture an early exit left running. Then `step`, `ctl`, `cap`, `snap`, `compare`, `lab_reset` (stops the run when `labctl.py reset` fails, naming `run-session.sh reset` as the way to retry it), `cap_start` and `cap_stop`, `expect_exit` and `expect_findings`, `lab_tcp` (a 3 s TCP test whose four outcomes are `open`, `refused`, `unreachable (<bash's reason>)`, and `no answer in 3 s`), `lab_takes_no_arguments` (`-h` prints the script's header and exits 0, any other argument exits 2), `lab_testbed_os` and `lab_r3_testbed_fits` (the R3 testbed checks `run-second-platform.sh` and `run-session.sh` share), `lab_not_reachable` (exit 4: the devices do not answer on the path a run tests), and `lab_finish`, which ends a run with exit 0 when every comparison gave its predicted exit and the change comparison its predicted findings, 3 when one did not, and warns if a password value reached the log. The four runs recorded before `_lib.sh` existed keep their own copy, since they reproduce recorded runs. |
| `check_findings.py` | Compares a report's findings, as (policy, device, path), with an expected file: exit 0 when they are the same, 1 with a `missing:` or `unexpected:` line for each difference, 2 on bad usage or input it cannot read. `_lib.sh`'s `expect_findings` runs it. |
| `compare_captures.py` | Whether two snapshots hold the same data: exit 0 when they do, 1 with a `<section>.<path>: <a> != <b>` line per difference (at most 40, then the count), 2 on bad usage or a section file it cannot read. It ignores `SOURCE.json` and `raw/`, compares running configs line by line, and never prints a config line that may hold a secret. |
| `expect-second-platform-nxosv9000.txt`, `expect-second-platform-cat8000v.txt` | The predicted findings of the second-platform run's change comparison for the two R3 platforms with no recorded run, one `<policy> <device> <path>` per line, written before any capture exists. `run-second-platform.sh` checks its report against its platform's file, and `tests/test_lab_scripts.py` reads the same file to pin the prediction. Each moves next to its evidence with its draft intent once a run is recorded, as the 2026-11-21 runs' `expect-<run>.txt` files did: they are in `fixtures/lab-2026-11-21/`. |
| `labctl.py` | The lab actions the scripts above call: `setup-ospf`, `shut`, `noshut`, `wait-full`, `wait-gone`, `setup-bgp`, `bgp-shut`, `bgp-noshut`, `wait-bgp-up`, `wait-bgp-down`, `setup-bgp-fast`, `check-hold-time`, `bgp-block`, `bgp-unblock`, `setup-ospf-fast`, `check-dead-time`, `ospf-block`, `ospf-unblock`, `wait-ospf-lost`, `setup-ibgp`, `wait-ibgp-up`, `wait-ibgp-down`, `check-ibgp-hold-time`, `wait-vrf-gone`, `setup-vrf`, `wait-vrf-bgp-up`, `wait-vrf-bgp-down`, `check-vrf-hold-time`, `vrf-shut`, `vrf-noshut`, `setup-r3-link`, `wait-r3-up`, `wait-r3-down`, `r3-shut`, `r3-noshut`, `reset`, which removes what these scripts add from both routers, and `probe`, which only reads. The R3 commands touch R1 alone: R3 is configured only by the day-0 configuration cml_lab.py gives it when it adds the node. |
| `sanitize_capture.py` | Copies a run's stage directories (`pre/`, `post/`, `restored/`, or the SSH path run's `console/` and `ssh/`: each subdirectory holding a `config.json`) for publishing with passwords and certificate bodies replaced and `raw/` left out. It exits 2 with its usage when the run holds no stage, and checks the source before it creates anything, so a refused run leaves no half-made destination. It also knows NX-OS's documented `username ... password` and `snmp-server user ... auth` forms, which no capture has shown yet: the 2026-11-21 NX-OS attempt stopped before any capture. On the IOSv R3 of that day, its `username ... secret` rule replaced the one secret line. |
| `bgp_pcap.py` | Lists the BGP messages in a pcap of the lab link: TCP flags, retransmissions, and each message by name, with NOTIFICATION error codes spelled out. |
| `link_pcap.py` | One timeline of the OSPF packets and BGP segments in a pcap of the lab link: each OSPF packet by type (a hello's timers, DR, BDR, and neighbor list; a database description's flags; an update's LSA count) and each BGP segment as `bgp_pcap.py` shows it, tagged with its VLAN when it has one. |
| `cml_capture.py` | Starts and saves a packet capture of the R1-R2 link through the CML API (`start [--filter "<bpf expression>"]`, default `tcp port 179`, and `stop <file.pcap>`), with the CML login the run scripts already hold. |
| `cml_lab.py` | The CML side of the lab. `inspect [<output dir>]` and `check-login` only read: the inventory gives the controller's version, node and image definitions, memory and CPU in use, and default-lab's nodes, interfaces, and links, ending with whether R1 Ethernet0/3 is free and which of `nxosv9000`, `cat8000v`, and `iosv` are available; after the login (a POST to `/authenticate`), every call is a GET, and configurations, notes, descriptions, canvas annotations, and VNC keys are dropped before anything is printed or saved. `check-login` exits 0 when CML accepts the login and 1 when it does not. `add-r3 <platform>` and `remove-r3` change the lab's topology: they add R3 with its day-0 configuration, link it to R1 Ethernet0/3, and boot it, or stop, wipe, and delete it and its link. `platform-os <platform>` prints the pyATS `os` R3's testbed entry needs, with no login and no call. |

The runs compare against the intents kept with their evidence
(`fixtures/lab-2026-09-12/intent-routes.yaml` and `intent-ospf.yaml`,
`fixtures/lab-2026-09-18/intent-bgp.yaml`,
`fixtures/lab-2026-11-20/intent-bgp-holdtimer.yaml`, and, in `fixtures/lab-2026-11-21/`,
`intent-ospf-deadtimer.yaml`, `intent-ibgp.yaml`, `intent-bgp-vrf.yaml`, and
`intent-second-platform-iosv.yaml`, each with its run's predicted findings beside it as
`expect-<run>.txt`), so a rerun on the same sandbox is checked against the same rules. The
second-platform run's draft intents for the platforms with no recorded run sit here in
`scripts/lab` (`intent-second-platform-nxosv9000.yaml` and
`intent-second-platform-cat8000v.yaml`), with their predicted findings beside them
(`expect-second-platform-<platform>.txt`), until a run is recorded.

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

## The OSPF dead-timer run

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
Hello 1, Dead 4. The no-change check then runs against
`fixtures/lab-2026-11-21/intent-ospf-deadtimer.yaml`, which requires the hello line on both
routers.

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

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py` and merged with
the script and the intent before the run (PR #16). The run on 2026-11-21 matched them
(`fixtures/lab-2026-11-21/SOURCE.md`):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (the ACL on R1) | 1 | `V_ADJ` R1 neighbor 2.2.2.2 (gone), `V_ADJ` R2 neighbor 1.1.1.1 (listed, not FULL) |
| pre vs restored | 0 | none |

On 2026-11-21, R1's neighbor 2.2.2.2 was gone and R2 still listed 1.1.1.1 on Ethernet0/1, as
`init`. Interfaces kept their status and zero error counters, the routing tables did not
change (this OSPF carries only 1.1.1.0/24, connected on both routers), and no rule names the
ACL lines in R1's post config. The restored comparison gave 0 findings, but the lab did not
return to an identical state: the DR and BDR roles swapped after recovery, and ncv does not
compare roles.

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

The capture (`fixtures/lab-2026-11-21/ospf-deadtimer-pcap/`) fits the prediction as far as the
wire can show it: when the ACL took effect is not on the wire. R2's Hellos stayed on the wire through the block and kept listing 1.1.1.1. R1's Hellos listed
`neighbors none` from 10.134 s. The database description exchange started at 112.237 s, when
the adjacency formed again. R1 was DR before the change and R2 after recovery. That R1
discarded R2's Hellos and timed R2 out on its dead interval is inferred from the Hello times,
not shown on the wire.

What only the run could confirm, and what the 2026-11-21 run showed:

- that IOS writes the hello line as `ip ospf hello-interval 1` and derives a 4 s dead interval:
  yes. `check-dead-time` read `Hello 1, Dead 4` on both routers, and neither config has a
  dead-interval line;
- that `check-dead-time` reads this IOS version's `show ip ospf interface`: yes, on IOS XE
  17.15, from the line `Timer intervals configured, Hello 1, Dead 4, Wait 4, Retransmit 5`;
- that an inbound ACL drops OSPF addressed to the router, as it dropped BGP on 2026-11-20: R1
  lost the neighbor while R2's Hellos were still on the wire, which fits a drop; the drop
  itself happens inside R1 and is not shown;
- that Genie reports R2's neighbor as `init` rather than leaving it out (its parser needs the
  `Neighbor priority is N, State is X, N state changes` line): yes;
- that CML accepts `ip proto 89` as a capture filter: yes; the capture holds 476 OSPF packets
  and nothing else.

## The iBGP run

Every BGP run before this one was eBGP between directly connected addresses. This one is iBGP
the way it is usually built: the session runs between the routers' loopbacks, and the loopbacks
are reachable only through OSPF. So BGP depends on OSPF, and one cause should produce findings in
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
runs against `fixtures/lab-2026-11-21/intent-ibgp.yaml`. It names both OSPF adjacencies, both
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
paths are in the by-VRF form new captures use) and merged with the script and the intent before
the run (PR #16). The run on 2026-11-21 matched them (`fixtures/lab-2026-11-21/SOURCE.md`):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (the ACL on R1) | 1 | eight: `V_ADJ` ospf R1 neighbor 2.2.2.2 and R2 neighbor 1.1.1.1; `V_ROUTE` R1 10.255.255.2/32 and R2 10.255.255.1/32 (the peer loopbacks, ospf); `V_ADJ` bgp R1 neighbor 10.255.255.2 and R2 neighbor 10.255.255.1; `V_ROUTE` R1 172.16.2.0/24 and R2 172.16.1.0/24 (bgp) |
| pre vs restored | 0 | none |

On 2026-11-21 both iBGP sessions went from `Established` to `Idle`, Genie labelled the loopback
routes `ospf` and the Loopback1 prefixes `bgp`, and the restored comparison gave 0 findings. As
in the dead-timer run, the DR and BDR roles swapped after recovery, and the iBGP session came
back on a new TCP connection; ncv compares neither.

No rule names the ACL, so there is no `V_DRIFT`, and the static and connected routes and the
link counters should not move; they did not. The synthetic snapshots are built by passing Genie-shaped
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

The packet prediction did not hold (`fixtures/lab-2026-11-21/ibgp-pcap/`). During the outage
the link showed what it said: the last port-179 segment was at 10.111 s, and no NOTIFICATION,
FIN, RST, or SYN followed until R1 opened a new connection at 160.533 s, after the undo. But
R2's `NOTIFICATION 4/0 Hold Timer Expired` did reach the wire. At 172.029 s, with the new
session already open, R2 sent one segment on the old connection, to port 64623: three
KEEPALIVEs, an UPDATE, and the NOTIFICATION. R1 answered with a reset. R1's own NOTIFICATION
never appeared. That R2's segment had waited out the outage in its queue is inferred, not
shown.

What only the run could confirm, and what the 2026-11-21 run showed:

- the timings and their order: the polls cannot time them (R1 had lost OSPF at the poll at
  13:12:19, and neither session was Established at the poll at 13:12:50). On the wire, the last
  port-179 segment was at 10.111 s and R1's first Hello with no neighbor at 11.492 s; no BGP
  message marks the moment either router gave its session up;
- whether Genie labels the learned route `bgp` and the loopback route `ospf`: yes;
- which state Genie captures for the downed sessions: `Idle`, on both routers;
- whether IOS writes each required line as the intent has it: yes, the no-change check passed;
- whether one console session can still reach both routers while the control plane is down:
  yes, the post capture of both succeeded.

## The BGP VRF run

Before this run, every BGP capture had one session, in the global table. This run adds a
second session to the same peer address inside a VRF, then breaks only that one. It is the live test of ncv
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
     no shutdown
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
`no shutdown` ends the subinterface block because IOS can bring a deleted subinterface back with
its old state, and a stopped run's `labctl.py reset` deletes it while it is shut down; without
it the next setup could leave the VRF link down. The line never shows in a running config.

`show bgp ipv4 unicast summary` lists only the global table, so the VRF commands read
`show bgp vpnv4 unicast vrf NCV summary` and `show bgp vpnv4 unicast vrf NCV neighbors <peer>`
with the parsers the global commands use. The script waits with `wait-bgp-up` and
`wait-vrf-bgp-up`, which waits for each VRF session to have learned at least one prefix, since
the intent names a BGP-learned prefix in the VRF. Then `check-hold-time` and
`check-vrf-hold-time`, and the no-change check against
`fixtures/lab-2026-11-21/intent-bgp-vrf.yaml`. It names four BGP adjacencies, two per router,
one per VRF; the hold-timer run's routes in the default VRF and, in vrf NCV, each router's connected
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

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py` and merged with
the script and the intent before the run (PR #16). The run on 2026-11-21 matched them
(`fixtures/lab-2026-11-21/SOURCE.md`):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (`shutdown` on R1 Ethernet0/1.100) | 1 | five, all in vrf NCV: `V_ADJ` R1 neighbor 1.1.1.2 and R2 neighbor 1.1.1.1; `V_ROUTE` R1 1.1.1.0/24 (connected) and 172.16.102.0/24 (bgp); `V_ROUTE` R2 172.16.101.0/24 (bgp) |
| pre vs restored | 0 | none |

On 2026-11-21 R1's VRF session went to `Idle` and R2's to `Active`, and the global session stayed
Established on both routers in all three captures. R2 kept 1.1.1.0/24 as connected in vrf NCV,
since its own subinterface stayed up. The restored comparison gave 0 findings; the VRF session
came back on a new TCP connection.

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

The capture (`fixtures/lab-2026-11-21/bgp-vrf-pcap/`) matched what the wire can show of that.
R1's last frame on VLAN 100 was a KEEPALIVE at 3.709 s, and R1 sent nothing more on the tag
until its SYN at 117.336 s, after the undo. R2 retransmitted its unanswered keepalive, then sent
`NOTIFICATION 4/0 Hold Timer Expired` at 13.312 s, 9.6 s after R1's last keepalive, and closed
with FIN. The summary lists a second NOTIFICATION at 21.189 s, but that segment is R2's
retransmission of the first: `link_pcap.py` does not mark a retransmission that TCP
repacketized. R2's SYNs from 21.509 s went unanswered. The untagged session ran on with
keepalives about every 3 s and no NOTIFICATION.

What only the run could confirm, and what the 2026-11-21 run showed:

- that IOL accepts a dot1Q subinterface on Ethernet0/1 and the CML link carries the tag: yes;
  the capture shows the VRF session's frames tagged `vlan 100`;
- that IOS accepts the same neighbor address in the global table and in the VRF: yes;
- how Genie files the VRF neighbor: its IOS XE test data puts it under
  `instance.default.vrf.<name>.neighbor`, which is what ncv expects, and whether the
  per-neighbor commands Genie runs cope with one address in two VRFs: they did, and ncv wrote
  `bgp.vrfs.NCV.neighbors.1.1.1.2` beside the same address under `default`;
- that `show bgp vpnv4 unicast vrf NCV summary` and `... neighbors 1.1.1.2` print the formats
  the parsers expect: yes, `wait-vrf-bgp-up` and `check-vrf-hold-time` passed. That `show vrf`
  lists NCV while IOS is still deleting it was not exercised: the first poll after the reset
  found no vrf NCV;
- that R1's session resets at once and R2's on its hold timer: R2's NOTIFICATION came 9.6 s
  after R1's last keepalive, against a 9 s hold time. How R1 ended its session is not shown: R1
  fell silent on the tag, and its snapshot shows `Idle`;
- that CML accepts the `vlan` capture filter: yes.

## The second-platform run

Until this run, everything published came from one image, IOS XE 17.15 on IOL. This run adds a
third router, R3, on another platform, joined to R1, and breaks the link from R1's end: an
adjacency lost and seen from both ends, one end on each platform. It tests ncv's adapter on
Genie data shaped by another platform. It was recorded on 2026-11-21 with R3 on IOSv
(`fixtures/lab-2026-11-21/second-platform-iosv`). An attempt with R3 on NX-OS the same evening
stopped before any capture, and Catalyst 8000V has not run. Each unknown is written to fail
early with a message that says what to look at; the list at the end of this section says which
ones the two attempts settled and which stay open.

The topology change is `cml_lab.py add-r3 <platform>`, through the CML API, stopping with exit 1
and a one-line reason at the first thing that is not as it needs:

1. the platform's node definition exists and has an image;
2. no node is labelled R3 (one that is already booted with the same node definition is exit 0,
   one still starting is waited for, anything else is refused, naming `remove-r3`);
3. R1 Ethernet0/3 exists in the topology and is not connected;
4. free memory, from `/system_stats`, is not plainly short of the node definition's RAM (it
   prints both numbers, and skips the check when either is missing);
5. it creates the node with its day-0 configuration
   (`POST /labs/{id}/nodes?populate_interfaces=true`), reads it back once with its configuration
   (`GET /labs/{id}/nodes/{id}?exclude_configurations=false`, the query Cisco's virl2_client
   2.7.1 sends), and checks that CML kept the configuration (its `hostname R3` line, read as a
   boolean and never printed);
6. it links R3's first data interface to R1 Ethernet0/3 (`POST /labs/{id}/links`);
7. it starts R3 and polls its state every 15 s, printing each, for at most 20 minutes, giving up
   after 3 minutes still `QUEUED` or `DEFINED_ON_CORE` (`CML has not started R3`) or `STOPPED`
   (`R3 is still STOPPED ... after the start`), since CML does not boot a stopped node by itself;
8. once R3 is `BOOTED`, it starts the link if it is not `STARTED` and stops if it still is not.

`BOOTED` is CML's state, and it is not proof that R3 booted. CML also sets it when the node
definition's boot timeout runs out: 180 s for `iosv` and 480 s for `nxosv9000`, both well inside
`add-r3`'s 20 minutes. On 2026-11-21 CML's events put the NX-OS R3's `BOOTED` 478 s after its
start, at that timeout, and that R3 never loaded NX-OS. They put the IOSv R3's `BOOTED` 177 s
after its start; that R3's console log was not read, so that this was the timeout too is
inferred from the timing only. The IOSv R3 was up by the first `wait-r3-up` poll, at 13:39:35
PT, when R1 saw it as its OSPF neighbor and BGP peer. So `add-r3`'s `R3 BOOTED` line can be a
timeout.

In the samples taken after the NX-OS attempt, two read-only calls told the stuck R3 from the
running R1 and R2: CML's console log for each node (12 characters for R3, over a million each
for R1 and R2) and the counters of the R1-R3 link (R3 had sent no packet). The disk counter
alone did not: R1 and R2, which run as IOL processes, showed 0 bytes read and written, and R3's
virtual machine 512 bytes read and none written, with one of its two virtual CPUs busy. No
booted virtual-machine node was sampled to compare with. `add-r3` makes none of these checks
today.

Every failure after the node exists ends with `R3 was created; cml_lab.py remove-r3 removes it`.
The day-0 configuration holds R3's admin password (`NCV_LAB_PASS`), so it is echoed with
`<removed>` in its place, the node POST's response is never printed, and every message passes
through one `redact` function. `cml_lab.py remove-r3` reads R3's state, stops it unless it is
already stopped, waits up to 3 minutes for `STOPPED` (or `DEFINED_ON_CORE`, the state a node
that never started returns to), wipes its disks unless it never started, deletes its link and
then the node, and treats a missing R3, or a 404 on the way, as already gone. The run leaves R3 in
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
form for the other two platforms, whose console has no login. On 2026-11-21 ncv reached the IOSv
R3 that way, with the CML login alone, and captured it three times with no connect error. ncv
has made no connection to an NX-OS R3. ncv's capture refuses to answer a
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

There is one intent per platform, because the strings differ. Each names devices R1 and
R3; the OSPF adjacencies (R1 neighbor 3.3.3.3 on Ethernet0/3, R3 neighbor 1.1.1.1 on its first
data interface) and the BGP ones (R1 neighbor 10.1.3.3 remote AS 65003, R3 neighbor 10.1.3.1
remote AS 65001, both in vrf default); R1's routes 10.1.3.0/24 connected, 3.3.3.3/32 ospf, and
172.16.3.0/24 bgp, and R3's 10.1.3.0/24 (`direct` on NX-OS, `connected` on IOS), 1.1.1.0/24
ospf, and 10.10.10.0/24 bgp; the counters of R1 Ethernet0/3 and R3's first data interface; R1's
lines `ip address 10.1.3.1 255.255.255.0`, `network 10.1.3.0 0.0.0.255 area 0`,
`neighbor 10.1.3.3 remote-as 65003`, and `neighbor 10.1.3.3 timers 3 9`, and for R3 only
`router bgp 65003`, since no capture existed to copy its lines from when the intents were
written. The three files differ only in R3's interface name and its connected-route string. ncv does not alias `direct` to
`connected` or fold `Mgmt0` to `mgmt0`: an intent copies what the device's capture says. These
strings came from Genie's parsers and test data, not from a device. The IOSv ones held: the
no-change check showed the first IOSv pre capture met every rule, so its intent, now in
`fixtures/lab-2026-11-21/`, needed no correction. The NX-OS and Catalyst 8000V ones may still
need it, and the no-change check is what will say so; the script then says to compare the
intent with `captures/second-platform-<stamp>/pre`, correct a draft intent, and rerun. The IOSv
intent is the recorded run's evidence and stays as it is.

Predicted findings, pinned on synthetic snapshots in `tests/test_lab_scripts.py` and merged with
the script and the intent before the run (PR #16). The IOSv run on 2026-11-21 matched them
(`fixtures/lab-2026-11-21/SOURCE.md`):

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (`shutdown` on R1 Ethernet0/3) | 1 | nine: `V_ADJ` ospf and bgp on R1 (neighbors 3.3.3.3 and 10.1.3.3) and on R3 (neighbors 1.1.1.1 and 10.1.3.1); `V_ROUTE` R1 10.1.3.0/24, 3.3.3.3/32, and 172.16.3.0/24; `V_ROUTE` R3 1.1.1.0/24 and 10.10.10.0/24 |
| pre vs restored | 0 | none |

R3's own 10.1.3.0/24 stays: the nine assume R3's interface stays up when R1 shuts its end,
because CML does not pass carrier across a link. If it does go down, R3 also loses that route
and the run gives ten; the expected files say so in their comments. On IOSv it stayed up: R3's
GigabitEthernet0/0 kept its status, R3 kept 10.1.3.0/24 as connected, and the run gave nine.
The findings are the same for all three platforms and live in
`expect-second-platform-<platform>.txt`, which the test reads and the script checks its change
report against. The synthetic snapshots are built
through ncv's own adapter from Genie's shapes, R3's as each platform writes them (on NX-OS:
lowercase BGP states, `direct`, and interface records that carry no status, which ncv keeps as
unknown), and a further test shows that an R3 capture saying `connected` fails the NX-OS
draft's no-change check with one `V_ROUTE`: the platform's strings are part of the intent. If a
run stops with Ethernet0/3 shut, `change.sh r3-undo` brings it back, or the next run's
`labctl.py reset` puts the port back as it ships.

What the IOSv run showed beyond the nine. Genie's output for classic IOS normalized into the
same snapshot layout as IOS XE, with no adapter change: R3's OSPF, BGP, routing, and interface
records have the same keys as R1's. R3's snapshot shows its OSPF neighbor gone and its BGP peer
`Active`; the run takes no packet capture, so nothing shows how R3's side ended. R2 was not
unaffected: it lost three routes it had learned through R1 (10.1.3.0/24, 3.3.3.3/32, and
172.16.3.0/24) with no finding, because the intent lists only R1 and R3. The captures record R3
as IOS `version 15.9`; the fuller 15.9(3)M9 comes only from the image name, `iosv-159-3-m9`.
The restored comparison gave 0 findings.

Assumptions the attempts had to check, each with how it fails and what 2026-11-21 showed:

- **Try the platforms in the order `iosv`, `cat8000v`, `nxosv9000`.** IOSv is light and needs
  neither a licence nor a boot line; NX-OS 9000v is the heaviest. `probe.sh` says which have a
  node definition and an image first. `add-r3` refuses an R3 of another platform, so remove each
  R3 before the next platform: `bash scripts/lab/run-session.sh second-platform:iosv remove-r3`,
  then put R3's `cat8000v` entry into `testbeds/lab-r3.yaml` and run
  `bash scripts/lab/run-session.sh second-platform:cat8000v remove-r3`. One session cannot hold
  two platforms, because each needs its own R3 entry and the session checks it before any prompt.
  On 2026-11-21 IOSv ran first, and NX-OS next, in a session that began with `remove-r3`;
  Catalyst 8000V was not tried.
- **The image exists.** `add-r3` refuses before any change: `the controller has no node
  definition <platform>` or `node definition <platform> has no image`. The probe found all
  three on CML 2.7.2: `iosv-159-3-m9`, `cat8000v-17-15-01a`, and `nxosv9300-10-5-1-f`.
- **R1 Ethernet0/3 is in the topology and free.** `add-r3` refuses, naming the link that uses
  it. The probe found it free.
- **CML can add a link to R1 while it runs.** R1 Ethernet0/3 already exists, so no interface is
  hot-added. If CML refuses, the link POST fails (`could not link R1 Ethernet0/3 to R3: ...`),
  and R3 is left for `remove-r3`. Settled on CML 2.7.2: with R1 running, it linked R1
  Ethernet0/3 to the IOSv R3's GigabitEthernet0/0, and later to the NX-OS R3's Ethernet1/1, and
  reported each link STARTED.
- **The form of `configuration` the API accepts.** `add-r3` sends one string; Cisco's client
  also sends a list of named files. If CML drops it, `add-r3` stops with `CML did not keep the
  day-0 configuration` before starting R3. If CML keeps it but R3 boots without applying it, R3
  comes up unconfigured and `wait-r3-up` times out with R1's line protocol up and no OSPF. CML
  kept the one string for both R3s. The IOSv R3 applied it: at the first poll R1 saw it as an
  OSPF neighbor FULL and a BGP peer with a prefix learned. The NX-OS attempt timed out in
  `wait-r3-up` with R1 Ethernet0/3 up/up, no OSPF neighbor, no BGP peer, and only R2 in R1's CDP
  table. A read-only look afterwards showed that this R3 never loaded NX-OS, so it never read
  its configuration (the NX-OS attempt, below). Whether an NX-OS R3 applies the one string is
  still open.
- **The image's `boot nxos bootflash:...` line.** A custom day-0 configuration may replace CML's
  template, which carries that line and the management VRF. Symptom: R3's console sits at
  `loader>` and the boot never completes. `add-r3`'s wait does not catch that, because CML
  reports `BOOTED` at the node definition's 480 s boot timeout anyway; only R3's console shows
  it. Not settled: `add-r3`'s poll saw the NX-OS R3 BOOTED after 483 s; CML's own event was 478 s
  after its start, at that timeout, not a boot. That R3 never loaded NX-OS, and CML's console log for it held 12 characters, with no
  `loader>` prompt. CML's own default day-0 configuration for `nxosv9000` carries a workaround
  for a boot that stops at `loader>` (an EEM applet that sets `boot nxos`); the one `add-r3`
  sends does not.
- **The interface labels.** `Ethernet1/1`, `GigabitEthernet1`, and `GigabitEthernet0/0` come
  from CML's documentation. If R3 has no interface by that label, `add-r3` stops and lists the
  labels it has. `GigabitEthernet0/0` (IOSv) and `Ethernet1/1` (NX-OS) were on the nodes
  `add-r3` created; `GigabitEthernet1` has not been tried.
- **Boot time and memory.** `add-r3` refuses up front when free memory is plainly short; CML may
  still refuse the start (`CML has not started R3 (memory or licence; see cml_lab.py inspect)`
  after 3 minutes), or a slow boot may outlast the 20-minute wait. The `iosv` node definition
  asks for 512 MiB; with 29783 MiB free, `add-r3`'s poll saw that R3 BOOTED after 181 s (CML's
  events: 177 s after its start). The `nxosv9000` one asks for 12288 MiB; with 29757 MiB free,
  the poll saw BOOTED after 483 s (CML's events: 478 s). Neither number is a boot time. The
  NX-OS one is the node definition's 480 s boot timeout; the IOSv one fits the `iosv` timeout of
  180 s, an inference from the timing, since that R3's console log was not read. The IOSv R3 was
  up by the first `wait-r3-up` poll, at 13:39:35 PT, when R1 saw it as its OSPF neighbor and BGP
  peer; the NX-OS R3 never loaded NX-OS.
- **The console path and login chain for R3.** `open /default-lab/R3/0`, then for NX-OS the
  admin login. If either is wrong, the pre capture fails at connect for R3 with Unicon's own
  message (`failed to connect to R3`); a device left at a first-boot dialog fails it too, with
  `lab capture failed for R3 during connect: device is at a first-boot setup dialog; ncv will not answer it`.
  On NX-OS the Enter that `SENDLINE_AFTER_CRED` sends after the CML password reaches that
  dialog before ncv stops the connect (on Unicon's mock the prompt was only printed again); ncv
  sends nothing after it. For IOSv the path worked: ncv connected to R3's console with the CML
  login alone and captured it three times with no connect error. The NX-OS admin login and
  `SENDLINE_AFTER_CRED` are still checked against Unicon's mock devices only: ncv never
  connected to the NX-OS R3. After the attempt, an ad-hoc read-only script outside the repo
  opened that R3's console the way ncv does; Unicon timed out with an empty buffer, and CML's
  console log for that R3 held only 12 characters.
- **What the console server shows when a console is opened.** If it replays old console output,
  a first-boot dialog from R3's boot could still be in that history, and ncv would refuse a
  healthy R3 at connect with that same first-boot message. Open R3's console by hand
  (`ssh developer@10.10.20.161 "open /default-lab/R3/0"`) to see what it shows now. Still open:
  the three IOSv connects raised no first-boot refusal, and nobody has opened R3's console by
  hand. The one later connection to the NX-OS R3's console got nothing back, but that R3 had
  printed only 12 characters to replay.
- **Genie's NX-OS shapes on a real 9000v.** Taken from Genie's test data. A shape the adapter
  does not handle fails the pre capture at a named learn; a string that differs (`direct`, an
  interface name, a state) is named by the no-change check. Still open: no NX-OS capture exists.
  Classic IOS on IOSv needed no adapter change.
- **R3's interface stays up when R1 shuts its end.** If not, the change comparison has a tenth
  finding, and `check_findings.py` names it as unexpected. On IOSv it stayed up, and the run gave
  nine.
- **An R3 capture must be read line by line before it is published.** `sanitize_capture.py`'s
  NX-OS rules (`username ... password <type> <hash> role ...` and `snmp-server user ... auth
  ... localizedkey`) were written from NX-OS's documented forms, not from a capture. The IOSv
  capture was read that way: its one secret line, `username admin privilege 15 secret 9` and a
  hash, was replaced by the `username` rule the sandbox routers already needed. The NX-OS rules
  are still untried.

`cml_lab.py remove-r3` ran for the first time at the start of the NX-OS session. It stopped the
IOSv R3, wiped its disks, deleted its link to R1 Ethernet0/3, and deleted the node.

The NX-OS attempt, 21:18 to 21:40 PT (`fixtures/lab-2026-11-21/SOURCE.md` has the details):
`add-r3 nxosv9000` created R3, CML kept its day-0 configuration, `add-r3` linked R1 Ethernet0/3
to R3 Ethernet1/1, and its poll saw R3 BOOTED after 483 s and the link STARTED. R1's side was configured
and R1 Ethernet0/3 was up/up. For 600 s R1 saw no OSPF neighbor and no BGP peer on that link,
and R1's CDP table listed only R2. The run stopped before any capture (exit 1), and nothing from
it is published. ncv never connected to R3, so it is not evidence about ncv on NX-OS. The reset
returned R1 and R2 to the shipped configuration; R3, the NX-OS node, was left in the lab; it was
still there at 22:03 PT.

A read-only look at that R3 afterwards, 21:55 to 22:03 PT, showed why R1 saw nothing. It was two
ad-hoc scripts outside the repo: GET calls to the CML API and one console connection made the
way ncv makes it. They configured nothing, and their logs are not published. What they saw:

- CML's events put R3's `BOOTED` 478 s after its start. That is the `nxosv9000` node
  definition's 480 s boot timeout, not a console line.
- 44 minutes after the start, R3's virtual machine had read 512 bytes from its disk and written
  none, kept one of its two virtual CPUs busy, and sent no packet on the link.
- CML's console log for R3 held 12 characters; the same call returned over a million for each
  of R1 and R2.
- The console connection timed out with an empty buffer.

So that R3 never loaded NX-OS, and CML's `BOOTED` is not proof that a node booted. The day-0
configuration is not the cause, since NX-OS reads it only once NX-OS runs; neither are the link
or ncv. The rest is inference, not proven here: the machine is stuck in its firmware, and the
likely reason is that the sandbox's CML host has an AMD processor. A Cisco employee wrote on the
Cisco Community on 2024-12-04 that some CML reference images, NX-OSv 9000 among them, have boot
issues on AMD
(https://community.cisco.com/t5/cisco-modeling-labs-discussions/which-cml-nodes-are-not-compatible-with-amd/m-p/5232504).

Still open: whether NX-OS 9000v can boot in this sandbox at all (there was one attempt);
everything about ncv on NX-OS, that is the console login with two credentials, a first-boot
dialog, and Genie's NX-OS output; and Catalyst 8000V, which has not been tried. One more item,
found the same evening offline against Unicon 26.8's mock n9k device only, is open for
`src/ncv/live.py`: with ncv's connect arguments, Unicon's NX-OS plugin answers a device at a
loader prompt by sending `boot`, and one at a boot-mode prompt by sending `load-nxos`, and ncv's
first-boot guard does not cover those prompts. No real device was affected.

## The probe

Two things decide what the next runs can do, and nothing here may guess them: whether the
routers' management addresses (10.10.20.171 and .172, on Ethernet0/2 in vrf Mgmt-intf) answer
over the sandbox VPN, and which node images the controller has. On 2026-09-12 the management
addresses did not answer, and nobody recorded why; the probe recorded what they do on 2026-11-21
(below). `probe.sh` asks, and changes nothing: it
sends no configuration to any device, every CML call after the login (a POST to
`/authenticate`) is a GET, and `show running-config` is not among the router commands.

1. From this machine: `ip -brief addr show tun0`, `ip route get 10.10.20.171`, and for each
   management address a TCP test of ports 22 and 23 and `ping -c 2 -W 2`. The TCP test has
   four outcomes, and the difference is the question 2026-09-12 left open: `open`; `refused`,
   only when bash's connect error says `Connection refused` (something at that address, the
   host or a filter in front of it, sent a reset); `unreachable (<bash's reason>)` for any
   other connect error, such as `Network is unreachable` or `No route to host` (this machine or
   a router on the way said there is no path); and `no answer in 3 s` (nothing came back:
   dropped on the way or never routed). On 2026-11-21 all four tests gave `no answer in 3 s`.
2. `cml_lab.py inspect output/lab/probe-<stamp>-cml`: the CML version, the node and image
   definitions, memory and CPU in use, and default-lab's nodes, interfaces, and links. Each
   response is saved there as JSON, without configurations, notes, descriptions, canvas
   annotations, or VNC keys. Several response shapes are unverified, so a missing field prints
   as unknown and a call that fails is reported and skipped.
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

It ran on 2026-11-21, from 12:58 to 13:00 PT, and answered all three questions
(`fixtures/lab-2026-11-21/SOURCE.md`). The management addresses did not answer: no answer on
port 22 or 23 within 3 s and no ping reply, and on both routers `show ip ssh` reported SSH
disabled, with no RSA or EC host keys. R1 Ethernet0/3 was free. CML 2.7.2 had node definitions
for `iosv` (image `iosv-159-3-m9`, 512 MiB), `cat8000v` (`cat8000v-17-15-01a`, 4096 MiB), and
`nxosv9000` (`nxosv9300-10-5-1-f`, 12288 MiB). Each node's image field printed as unknown.

## The SSH path (prepared, not run)

Every capture so far reached the routers through the CML console server. `run-ssh-path.sh`
tests one claim: the access path does not change the evidence. It captures the same routers
twice in a row, through the console server and then over SSH to their management addresses,
and changes nothing in the lab except `labctl.py reset`, which returns a used reservation to
the shipped configuration.

It has not run. On 2026-11-21 the probe found that neither management address answers on port
22, which would end this run with exit 4 at its port check, and both routers report SSH disabled
with no host keys. So the session did not start it.

Set up: `cp testbeds/cml-ssh.yaml.example testbeds/lab-ssh.yaml` (gitignored). It reaches R1 at
10.10.20.171 and R2 at 10.10.20.172 on port 22, logs in as the router's local user
(`NCV_SSH_USER`, default `cisco`, and `NCV_SSH_PASS`), and answers the `enable` prompt Unicon
always sends on IOS XE with `NCV_LAB_PASS`. Host keys go to `output/lab/known_hosts`, which the
run deletes before its SSH capture: a new reservation gives the routers new keys, and ssh
refuses a changed one. With that file in place, the runs that capture through
`_lib.sh` (`run-ospf-deadtimer.sh`, `run-ibgp.sh`, and `run-bgp-vrf.sh`) can be pointed at it
with `NCV_TESTBED=testbeds/lab-ssh.yaml`, and `_lib.sh` then asks for the SSH login. No run has
gone over SSH yet. The others use their own testbed: `run-lab.sh`, `run-ospf.sh`, `run-bgp.sh`,
`run-bgp-holdtimer.sh`, and `capture.sh` always capture through `testbeds/lab.yaml`,
`run-ssh-path.sh` sets its two testbeds itself, and `run-second-platform.sh` needs a testbed
with R3, which `lab-ssh.yaml` does not have.

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

Then an unnumbered `finish` step, and the log says where the captures and reports are. The
numbers are the ones the script prints, so step N in the log is step N here.

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
the sandbox, not a failure of the script: run `probe.sh` to record its reasons in the log, as
on 2026-11-21, and the console server stays the only path.

What only the run can confirm, and what the probe has answered already:

- whether the management addresses answer over the VPN at all: on 2026-11-21 they did not;
- whether the routers' SSH server accepts the client's key exchange and host key algorithms:
  not askable now, since both routers report SSH disabled with no host keys, and no script here
  enables it;
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
4. `bash scripts/lab/run-lab.sh`, `run-ospf.sh`, `run-bgp.sh`, `run-bgp-holdtimer.sh`, `run-ospf-deadtimer.sh`, `run-ibgp.sh`, or `run-bgp-vrf.sh`. Each asks for the CML
   username and password and the routers' enable password (`NCV_CML_USER`, `NCV_CML_PASS`,
   `NCV_LAB_PASS`), unless they are already set; the logins last only while that script runs.
   Each stops before touching the lab if the no-change check is not clean. A run that sources
   `_lib.sh` exits 0 when every comparison gave its predicted exit and the change comparison its predicted findings, 3 when it ran to
   the end but did not, 1 when it stopped early, and 2 when it could not start (no VPN, no
   testbed file, or no answer to a login prompt). One that stops early still stops and saves
   its packet capture on the way out. To run the newer runs one after another with one
   login, use `bash scripts/lab/run-session.sh` instead (see "A whole session with one login"
   below). The five run scripts that source `_lib.sh`, `probe.sh`, and `run-session.sh` print
   their header with `-h` and start nothing; those that take no argument refuse any other with exit 2.

`probe.sh` takes the same logins and is safe to run first on any reservation: it only reads.
`run-ssh-path.sh` also needs `testbeds/lab-ssh.yaml` and asks for the routers' SSH login, and
its exit 4 means the management addresses do not answer in this sandbox, a result recorded
before anything is reset or captured, not a run that stopped early.
`run-second-platform.sh <platform>` needs `testbeds/lab-r3.yaml`, adds R3 to the lab, and
leaves it there: `bash scripts/lab/run-session.sh remove-r3` takes it out, asking for the
logins. Neither `cml_lab.py` nor `labctl.py` asks for a login, so `run-session.sh remove-r3`
and `run-session.sh reset` are the way to run them after a script has ended. To run one
directly, set the logins with prompts that keep the passwords out of shell history first
(`labctl.py` also needs the enable password):

    read -rp 'CML user: ' NCV_CML_USER; read -rsp 'CML password: ' NCV_CML_PASS; export NCV_CML_USER NCV_CML_PASS
    read -rsp 'Enable password: ' NCV_LAB_PASS; export NCV_LAB_PASS
    .venv/bin/python scripts/lab/cml_lab.py remove-r3
    .venv/bin/python scripts/lab/labctl.py reset

`NCV_TESTBED` picks another testbed file for `labctl.py` (a relative path is read from the
repository root), and `labctl.py reset` returns a reused reservation to the shipped
configuration: it removes only what these scripts add (the `NCV-` ACLs, `router bgp` 65001,
65002, and 65010, `router ospf 1`, the link's shutdown and OSPF timers, Loopback0, Loopback1,
Loopback100, Ethernet0/1.100, a reused Ethernet0/3, and vrf NCV), and never touches the
management path or the
static routes. It never touches R3 either; `run-session.sh remove-r3` removes it. The gate commands `check-hold-time`, `check-dead-time`, `check-ibgp-hold-time`,
and `check-vrf-hold-time` print each router's show command and the raw output they parsed
before their reading, so the run log keeps the real text: no snapshot holds it. The 2026-11-21
logs hold it (for example `Hello 1, Dead 4` from IOS XE 17.15), but run logs are not published.

Captures land in `captures/<run>/`, reports and the log in `output/lab/`. Both directories
are gitignored, and the captures hold the lab's running configs.

## A whole session with one login

On 2026-11-20 every script asked for the three logins again, and a password pasted into a
hidden prompt in an embedded terminal did not arrive, so each run cost several attempts.
`run-session.sh` asks once and runs the named runs in order:

    bash scripts/lab/run-session.sh [name ...]

The names are `probe`, `ospf-deadtimer`, `ibgp`, `bgp-vrf`, `ssh-path`,
`second-platform:<platform>`, `reset`, and `remove-r3`. `reset` runs `labctl.py reset` and
`remove-r3` runs `cml_lab.py remove-r3`, both with the logins the session asked for, since the
logins last only while a script runs. Run it from the WSL clone
(`~/network-change-validator`), which must be on current `main`, with `testbeds/lab.yaml` in place
and `testbeds/lab-ssh.yaml` or `testbeds/lab-r3.yaml` copied there when `ssh-path` or
`second-platform:<platform>` is named. It refuses an unknown name, a platform
`cml_lab.py`'s table does not have, a missing `testbeds/lab-ssh.yaml` when `ssh-path` is named,
and a missing `testbeds/lab-r3.yaml` (or `NCV_TESTBED`) or one whose R3 has another `os` when
`second-platform:<platform>` is named, all before any prompt, with the messages the run
scripts themselves give. Then it checks the VPN, asks for
`NCV_CML_USER`, `NCV_CML_PASS`, and `NCV_LAB_PASS` until each is not empty (and for
`NCV_SSH_USER` and `NCV_SSH_PASS` only when `ssh-path` is named), and checks the CML login once
with `cml_lab.py check-login`: that password is also the console server's login, so a wrong one
would fail every run. Each run's own `lab_init` then finds the logins set and does not ask
again.

The order a first session should use:

1. `bash scripts/lab/run-session.sh probe`, then read its three answers: whether the
   management addresses answer on port 22, whether R1 Ethernet0/3 is free, and which
   second-platform images exist.
2. `bash scripts/lab/run-session.sh ospf-deadtimer ibgp bgp-vrf reset`: the runs that need
   nothing beyond the three logins. With no names, the script runs `probe` and then these.
3. `ssh-path` only if the probe says both management addresses answer on port 22, and
   `second-platform:<platform>` only if it says R1 Ethernet0/3 is free and that platform has an
   image. `reset` returns R1 and R2 to the shipped configuration but does not remove R3;
   `remove-r3` does, for example `bash scripts/lab/run-session.sh second-platform:iosv
   remove-r3`.

The 2026-11-21 sessions went this way: `probe ospf-deadtimer ibgp bgp-vrf reset`, then
`second-platform:iosv reset`, then `remove-r3 second-platform:nxosv9000 reset`. `ssh-path` was
not named, because the probe found port 22 silent.

A run that fails does not stop the session: every run script starts with `labctl.py reset`, so
the next one starts clean. Two things stop it, because every later run would fail the same way:
a run that could not start (exit 2: the VPN dropped, or a testbed file or a login is missing)
and a failed probe (the CML login or a console connection). The script then prints the names
still to run as a ready command, for example `bash scripts/lab/run-session.sh ibgp bgp-vrf
reset`; Ctrl-C prints the table so far and the same command. A stopped run may leave its change
on R1. `change.sh ...-undo` removes it but asks for the logins again; the next run's
`labctl.py reset` removes it just as well.

Each run gets its own `NCV_STAMP`, `<session stamp>-<n>`, so its log is
`output/lab/<run>-<session stamp>-<n>.log`. At the end a table goes to the screen and to
`output/lab/session-<stamp>.log`, with each name, its exit status, what that means, and where
its log is:

| Exit | Meaning in the table |
|---|---|
| 0 | every comparison gave the predicted exit and the change comparison gave exactly the predicted findings (for `probe`: it finished, read its three answers; for `ssh-path`: both comparisons gave exit 0; for `reset`: it sent what R1 and R2 needed; for `remove-r3`: R3 and its link are out of the lab, or were not there) |
| 3 | ran to the end, but a comparison or the findings differed from the prediction: read the report |
| 1 | stopped early, shown with where it stopped: the last `== ` line of its log before the steps that stop a packet capture left running (for `probe`: the CML login or a console connection failed; it ran to its end, so no line says where it stopped) |
| 2 | could not start |
| 4 | the management addresses do not answer in this sandbox (a result, from `ssh-path`) |
| `interrupted` | Ctrl-C during that run |
| anything else | unexpected (N) |

For `reset` and `remove-r3`, any exit but 0, Ctrl-C included, reads `labctl.py reset failed (N)`
or `cml_lab.py remove-r3 failed (N)`, and their output is in the session log.

The session exits 0 only when every named run exited 0, 3 when it ran every name but one did
not, 1 when it stopped before the last name, 2 when it could not start, and 130 on Ctrl-C. No
log line holds a password, and the script never traces itself. `tests/test_lab_lib.py` runs it
with stand-in run scripts, and it drove the three sessions of 2026-11-21.

## Publishing a run

The 2026-11-21 runs were published in these steps:

1. Sanitize each run's stages into a directory named after the run (with the platform added for
   the second-platform run, whose report name is the same for every platform):

       .venv/bin/python scripts/lab/sanitize_capture.py captures/<run>-<stamp> fixtures/lab-<date>/<run>

   A run that `run-session.sh` started has the session's suffix in its stamp, for example
   `captures/ibgp-20261121-1258-3`. The SSH path run would be published the same way from
   `captures/ssh-path-<stamp>`, whose stages are `console/` and `ssh/`.
2. Read the copy before committing it, line by line for a platform with no published capture
   yet, as the IOSv R3's config was checked.
3. The sanitizer does not copy a packet capture. After checking that it holds only lab addresses
   and no authentication data, copy `captures/<run>-<stamp>/link.pcap` and
   `output/lab/<run>-<stamp>-pcap.txt` (`link_pcap.py`'s reading, as the run wrote it) to
   `fixtures/lab-<date>/<run>-pcap/link.pcap` and `summary.txt`.
4. Move the run's intent and expect file next to its evidence with `git mv`, their rules and
   findings unchanged; only the header comments change, to say which run used them. The run
   script then reads them from there (`run-second-platform.sh` picks the directory per
   platform).
5. Register the run in `LAB_RUNS` in `scripts/render_artifacts.py`, and run that script to write
   the run's report into `docs/artifacts`.
6. Add replay tests to `tests/test_lab_evidence.py`: the change comparison gives exactly the
   expect file's findings, the no-change and restored comparisons give none, and each
   `summary.txt` is what `link_pcap.py` reads from its `link.pcap`.
7. Write a `SOURCE.md` beside the runs recording the environment, the date, what each run did
   and showed, and exactly what was removed, as `fixtures/lab-2026-11-21/SOURCE.md` does.
8. Update the places that count or list the runs: the root README's live-lab count and table
   (`tests/test_lab_evidence.py` counts the rows), the config counts in
   `tests/test_lab_scripts.py`, `docs/artifacts/SOURCE.md`'s commands and file table,
   `docs/LIVE.md`, and `HANDOFF.md`.

The sanitizer knows the forms the sandbox routers carried: `enable password|secret`,
`username ... password|secret`, the indented `password` of a console or vty line, and the
body of a `certificate self-signed|ca` block. For an NX-OS R3 it also replaces the hash in
`username <name> password <type> <hash> role ...` and everything from `auth` on in
`snmp-server user ... localizedkey`, forms written from NX-OS's documentation rather than a
capture, so read an NX-OS capture line by line. On the IOSv R3 the `username ... secret` rule
replaced its one secret line. The sanitizer changes nothing else.
`tests/test_lab_scripts.py` pins the rules and checks that the published configs are the
script's own fixed point.
