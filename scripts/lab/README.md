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
| `capture.sh` | One capture (`pre`, `post`, or `restored`) for a run driven by hand. |
| `change.sh` | The planned change by hand: `apply` shuts R1 Ethernet0/1 and `undo` brings it back; `bgp-apply` shuts the R1 peer and `bgp-undo` brings it back; `holdtimer-apply` adds the BGP ACL and `holdtimer-undo` removes it; `deadtimer-apply` adds the OSPF ACL and `deadtimer-undo` removes it. |
| `_lib.sh` | Sourced, not run: what new run scripts share (the VPN check, the login prompts, the capture and report paths, `step`, `ctl`, `cap`, `snap`, `compare`), plus `expect_exit` and `lab_finish`, which end a run with exit 0 when every comparison exited as predicted and 3 when one did not. The four published runs keep their own copy, since they reproduce recorded runs. |
| `labctl.py` | The lab actions the scripts above call: `setup-ospf`, `shut`, `noshut`, `wait-full`, `wait-gone`, `setup-bgp`, `bgp-shut`, `bgp-noshut`, `wait-bgp-up`, `wait-bgp-down`, `setup-bgp-fast`, `check-hold-time`, `bgp-block`, `bgp-unblock`, `setup-ospf-fast`, `check-dead-time`, `ospf-block`, `ospf-unblock`, `wait-ospf-lost`, and `reset`, which removes what these scripts add from both routers. |
| `sanitize_capture.py` | Copies a run's `pre/`, `post/`, `restored/` for publishing with passwords and certificate bodies replaced and `raw/` left out. |
| `bgp_pcap.py` | Lists the BGP messages in a pcap of the lab link: TCP flags, retransmissions, and each message by name, with NOTIFICATION error codes spelled out. |
| `link_pcap.py` | One timeline of the OSPF packets and BGP segments in a pcap of the lab link: each OSPF packet by type (a hello's timers, DR, BDR, and neighbor list; a database description's flags; an update's LSA count) and each BGP segment as `bgp_pcap.py` shows it, tagged with its VLAN when it has one. |
| `cml_capture.py` | Starts and saves a packet capture of the R1-R2 link through the CML API (`start [--filter "<bpf expression>"]`, default `tcp port 179`, and `stop <file.pcap>`), with the CML login the run scripts already hold. |

The runs compare against the intents kept with their evidence
(`fixtures/lab-2026-09-12/intent-routes.yaml` and `intent-ospf.yaml`,
`fixtures/lab-2026-09-18/intent-bgp.yaml`, and
`fixtures/lab-2026-11-20/intent-bgp-holdtimer.yaml`), so a rerun on the
same sandbox is checked against the same rules. A prepared run's draft intent sits here in
`scripts/lab` (`intent-ospf-deadtimer.yaml`) until a run is recorded.

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
4. `bash scripts/lab/run-lab.sh`, `run-ospf.sh`, `run-bgp.sh`, `run-bgp-holdtimer.sh`, or the prepared `run-ospf-deadtimer.sh`. Each asks for the CML
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
