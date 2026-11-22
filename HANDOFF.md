# Handoff

Working notes for whoever picks this up next. Everything described here is on `main`. Four of
the five runs PR #16 prepared ran on 2026-11-21 and are recorded, which makes eight live runs with published snapshots. The
fifth, the SSH path run, cannot start in this sandbox. Of the second-platform run's three forms,
IOSv is recorded, NX-OS was tried once and stopped before any capture because R3's virtual
machine never loaded NX-OS, and Catalyst 8000V has not been tried.

## Current state

- Everything below is on `main`. PRs [#1](https://github.com/Bryancruzcb/network-change-validator/pull/1)
  through [#11](https://github.com/Bryancruzcb/network-change-validator/pull/11) went in as
  fast-forwards, so every hash quoted in these notes is the hash the commit carries on
  `main`. Six commits on 2026-09-18 went straight to `main` without a PR (see "Direct
  commits"). No open PRs, no open issues, and every merged branch is deleted.
- PR #12 went in as a squash (`e539627`). PRs #13, #14, and #15 went in as fast-forwards, so
  `ee58e95`, `017541c`, and `914431e` are the hashes their commits carry on `main`.
- PR [#16](https://github.com/Bryancruzcb/network-change-validator/pull/16) holds eight pieces
  of prepared work and two rounds of fixes, one after a design review and one after an
  examination of the whole branch, described below from "PR #16, BGP neighbors keyed by VRF"
  on. It went in as a fast-forward, 17 commits on top of `914431e`. Four of its runs ran on
  2026-11-21.
- PR #17 publishes those four runs: their sanitized captures in `fixtures/lab-2026-11-21`, three
  link captures, their reports in `docs/artifacts`, and each run's intent and expect file moved
  beside its evidence. See "PR #17, the 2026-11-21 evidence".
- `main` is protected: a commit reaches it only after the three CI jobs passed on that
  exact commit, admins included, and force pushes and deletion are refused. Push a
  branch, let CI finish, then fast-forward `main` to it (or merge the PR).
- CI runs Ruff, pytest, and the fixture gates on Ubuntu 3.10, Ubuntu 3.12, and Windows
  3.11, with pyATS and Genie absent. Each job publishes its findings table to the run
  summary.
- The oldest work here is built on `11ee5bd` ("Harden offline validation and fail
  incomplete lab captures").

## What landed

### PR #1, on top of `11ee5bd`

1. **Refactor + tests** -- section validation extracted to `ncv/schema.py` (shared by
   the snapshot loader and the Genie normalizer); `_to_dict` renamed
   `learned_to_mapping` now that live capture calls it across modules; each device's
   running-config is split once per snapshot and reused across every config rule group
   in an evaluation, with the caches local so a later evaluation re-reads its evidence.
   Tests reorganized to mirror the module under test, with shared fixtures in
   `tests/conftest.py`. Two policy regressions added:
   `test_config_rules_share_evidence_but_not_across_evaluations` and
   `test_missing_config_is_reported_once_across_rule_groups` -- both verified to fail
   when the cache or the dedupe is removed.
2. **Ruff + CI** -- Ruff added to the `dev` extra and configured in `pyproject.toml`;
   `ruff format` applied in its own commit so the reformatting is separate from the
   refactor. CI widened from one Ubuntu 3.12 job to Ubuntu 3.10/3.12 plus Windows 3.11,
   `fail-fast: false`, running both Ruff checks, pytest, and the fixture gates with
   pyATS and Genie absent. The exit-code gate is pinned to `shell: bash` because the
   Windows runner defaults to PowerShell.
3. **CI action majors** -- `actions/checkout` and `actions/setup-python` moved off the
   versions that target the deprecated Node 20, so the jobs no longer lean on the
   runner's Node 24 fallback. The matrix, `fail-fast: false`, and the bash-pinned gate
   are untouched.

### PR #2, BGP adjacencies and feature selection

`V_ADJ` was OSPF-shaped. An intent adjacency now takes `protocol: bgp` with `vrf` and
`remote_as`, both optional discriminators checked only when declared, the way
`interface` already worked for OSPF; a field belonging to the other protocol is
rejected by name. Snapshots gained a `bgp.json` section mirroring `ospf.json`, and the
Genie adapter walks the instance/vrf/neighbor shape, refusing the same peer seen in two
VRFs. It also claimed a device with no BGP normalizes to no neighbors; that held only for
a hand-built empty mapping, and PR #11 corrected it.

That raised the question the old code could not answer -- what happens in a lab that
does not run BGP -- so `snapshot --testbed` takes `--features` to narrow the learned
set. `show running-config` is always collected, an unknown or empty set is refused
before the testbed loads, and the flag is an error on a `--from-dir` copy.

The demo fixtures plant a peer that falls back to Idle, so the demo reports 8 findings
instead of 7, still across the same four classes.

### PR #3, report provenance and the CI summary

`report.json` opens with `report_version` and `ncv_version`, `report.md` ends with the
same pair, and `ncv --version` prints what a reader compares against. A test asserts
the packaging metadata and the module constant agree. Each CI job appends its own
findings table to the run summary instead of leaving it in a log.

### PR #4, the live runbook

`docs/LIVE.md` gained a step-by-step runbook for a first capture against a reserved
Cisco DevNet sandbox.

### PR #5, the interface shape Genie actually learns

The first real interface learn could not normalize: Genie's iosxe Interface ops key
their info by interface name and add a `vrf` summary, while the adapter only accepted a
hand-authored `interfaces` mapping. The adapter now accepts that shape, skips the `vrf`
summary, and still rejects records that do not look like interfaces. Two tests.

### PR #6, lab evidence

The first live run, on 2026-09-12, captured two IOS XE 17.15 IOL routers in a DevNet CML
sandbox through the CML console server. The sanitized captures live in
`fixtures/lab-2026-09-12` with a `SOURCE.md`, and `tests/test_lab_evidence.py` replays
them: shutting R1 Ethernet0/1 yields exactly two `V_ROUTE` findings on R1, and the
no-change and restored comparisons are clean. `testbeds/cml-console.yaml.example`
documents the console-server path, and the README, `docs/LIVE.md`, and this file now say
what happened.

### PR #7, OSPF adjacency evidence

A second run in the same sandbox set up OSPF area 0 on the R1-R2 link with pinned router IDs.
Shutting R1 Ethernet0/1 yielded `V_ADJ` on both routers plus the two R1 route findings, and
the no-change and restored comparisons were clean. The sanitized captures are in
`fixtures/lab-2026-09-12/ospf` with `intent-ospf.yaml`, and three more tests replay them.

### PR #8, the lab scripts

The scripts that drove the 2026-09-12 runs from WSL, and the sanitizer that prepared the
evidence for publishing, moved from a home directory into `scripts/lab/` with a README.
On the way in they learned to find the repository root from their own location, to compare
against the intents recorded with the evidence, and to log under `output/lab/`; the three
copies of the shut/no shut step became one `labctl.py` command. They push configuration
to the lab by design, which `ncv` never does, and the README says so.
`tests/test_lab_scripts.py` pins the sanitizer's rules on a synthetic config and checks
that every published `config.json` is the sanitizer's own fixed point. `.gitattributes`
keeps the shell scripts LF on Windows checkouts.

### PR #9, the BGP run, prepared and not run

`scripts/lab/run-bgp.sh`, new `labctl.py` commands (`setup-bgp`, `bgp-shut`, `bgp-noshut`,
`wait-bgp-up`, `wait-bgp-down`), and `scripts/lab/intent-bgp.yaml` prepare the one live path
with no evidence yet: eBGP between R1 and R2 over the 1.1.1.0/24 link, with an
administrative `neighbor 1.1.1.2 shutdown` on R1 as the planned change. `labctl.py` now
imports Genie only when a command runs, so its show-output parsers are tested without the
lab extra, and `change.sh` gained `bgp-apply|bgp-undo`. Three tests pin the parsers, the
draft intent, and the predicted findings on synthetic snapshots (`V_ADJ` on both routers
plus `V_DRIFT` on R1). Nothing was run against a lab and no document claims otherwise;
`scripts/lab/README.md` says what happens when it is run and recorded.

### PR #10, BGP evidence

The BGP run happened on 2026-09-18 in a fresh reservation of the same sandbox, driven by
`run-bgp.sh` unattended. Genie's BGP learn normalized with no adapter change, the no-change
check was clean, `neighbor 1.1.1.2 shutdown` on R1 yielded `V_ADJ` on both routers plus
`V_DRIFT` on R1, and the restored comparison was clean: the findings PR #9 predicted. The
sanitized captures are in `fixtures/lab-2026-09-18/bgp` with `intent-bgp.yaml` and a
`SOURCE.md`, and three more tests replay them.

### Direct commits on 2026-09-18, README and artifacts

Six commits went straight to `main` between 19:50 and 20:07 PT, without a PR: the README
now leads with the flow, the four policies, and the reports `ncv` wrote; `EXPLAIN.md`
names the lab evidence; `docs/artifacts` holds the four reports and two SVG summaries;
and `scripts/render_artifacts.py` rebuilds them. The last commit failed Ruff on all three
CI jobs, so `main` stayed red until PR #11.

### PR #11, review fixes

- `scripts/render_artifacts.py` passes Ruff again. It reads and writes UTF-8 with LF
  endings, so it runs on Windows (it used to crash writing the first SVG there), works in
  a temporary directory instead of a hard-coded `/tmp`, runs this checkout's `ncv`
  in-process without `PYTHONPATH`, and keeps building the files apart from writing them.
  Its output is the checked-in files byte for byte.
- `tests/test_artifacts.py` rebuilds every file in `docs/artifacts` and fails when one
  falls behind the code.
- A learn that returns no `info` now fails the capture with a message that names the
  feature and says to leave it out of `--features`. Genie 26.8's own ops test harness
  showed that a device which does not run BGP or OSPF returns an ops object with no
  `info`, and the adapter used to fall back to that object's internals and report an
  "unsupported" shape. Recording "no neighbors" instead would be unsafe: Genie cannot tell
  "not configured" from "every show command failed to parse". The empty-BGP special case
  that only a hand-built `{}` could reach is gone, and LIVE.md says what really happens.
- An empty `--features` value is refused instead of quietly learning all four features,
  and a repeated name is learned once.
- README and `EXPLAIN.md` no longer hard-code a test count, `fixtures/lab-2026-09-12/SOURCE.md`
  notes the unexplained configuration timestamps in the route run's pre capture, and
  `main` is protected (see "Current state").

### PR #13, the hold-timer run, prepared and not run

The fourth live path, prepared the way PR #9 prepared the BGP run, and merged before it ran.

- `labctl.py setup-bgp-fast` is `setup-bgp` plus `neighbor <peer> timers 3 9` on both
  routers, and `check-hold-time` reads the negotiated timers from `show bgp ipv4 unicast
  neighbors` and stops the run unless both sessions run a 9 s hold time. Timers take effect
  only when a session starts, so this matters on a reservation where BGP was already up.
  `setup-bgp`'s lines moved into `bgp_setup_lines()`, and a test pins them to what the
  2026-09-18 run sent.
- The change is `labctl.py bgp-block`: an inbound ACL, `NCV-BLOCK-BGP`, on R1 Ethernet0/1
  that drops TCP port 179 from R2 in both directions of the session and permits everything
  else. Nothing is shut down, so R1 stops hearing R2's keepalives and its hold timer
  expires. `bgp-unblock` unbinds and deletes the ACL; `change.sh holdtimer-apply|holdtimer-undo`
  does either by hand.
- `run-bgp-holdtimer.sh` drives it, against `intent-bgp-holdtimer.yaml` (the BGP intent plus
  the timers line on both routers), drafted in `scripts/lab/` and moved beside its evidence
  by the next PR. It pauses before the change and at
  the end so the operator can run a packet capture on the R1-R2 link in the CML UI.
- `scripts/lab/bgp_pcap.py` lists the BGP messages in a classic pcap (standard library only,
  outside ncv): TCP flags, retransmissions, OPEN timers, and NOTIFICATION codes by name. It
  is the packet side of the evidence: the hold-timer run should show NOTIFICATION code 4,
  where the admin shutdown would show code 6. Whether the DevNet sandbox lets a reservation
  capture on a link had not been checked then; PR #15 showed that it does.
- Predicted findings, pinned on synthetic snapshots: `V_ADJ` on both routers and nothing
  else. No rule names the ACL, so the config rules stay clean; that the adjacency rules
  catch a cause no rule anticipated is the point of the run.

### PR #14, hold-timer evidence

The run happened on 2026-11-20 in a fresh reservation of the same sandbox (CML 2.7.2,
IOS XE 17.15 IOL), driven by `run-bgp-holdtimer.sh` at `ee58e95`, and matched PR #13's
prediction: the no-change check clean, `V_ADJ` on both routers with both peers `Idle` after
the ACL, nothing else, and the restored comparison clean. `check-hold-time` read the
negotiated 9 s hold time from real output, and IOS wrote the timers line exactly as the
intent requires. No packet capture was taken on that run.

The sanitized captures are in `fixtures/lab-2026-11-20/bgp-holdtimer` with the intent and a
`SOURCE.md`; `tests/test_lab_evidence.py` replays them in four more tests;
`docs/artifacts/lab-2026-11-20-bgp-holdtimer-post.*` and a fourth block in
`lab-findings.svg` come from `render_artifacts.py`. `docs/LIVE.md` records what the new
sandbox logins cost: the CML login is `developer` from Access Details, not the per-reservation
VPN user, and passwords pasted into a hidden prompt in an embedded terminal did not arrive.

### PR #15, the hold-timer run's packet capture

A Windows browser cannot reach the CML web UI while the sandbox VPN runs inside WSL, so
`scripts/lab/cml_capture.py` starts and saves a capture of the R1-R2 link through the CML 2.7
API (field names checked against the sandbox's own OpenAPI description), and
`run-bgp-holdtimer.sh` calls it in place of the two manual pauses. `NCV_PCAP=0` skips it, and
a capture that cannot start does not stop the run. A second run on 2026-11-20 used it:
`fixtures/lab-2026-11-20/bgp-holdtimer-pcap/link.pcap` shows R1 sending NOTIFICATION 4/0 Hold
Timer Expired and retransmitting it, R2 sending none, the SYN backoff while the ACL stood, and
both OPENs carrying a 9 s hold time after it came off. `summary.txt` is `bgp_pcap.py`'s
reading of it, and `.gitattributes` keeps pcaps binary. 6 more tests: 5 for `cml_capture.py`
against a fake CML, and 1 that replays the pcap.

### PR #16, BGP neighbors keyed by VRF

`normalize_learn` now writes BGP as `{device: {"vrfs": {vrf: {"neighbors": {address: {state,
remote_as}}}}}}`, with the VRF as the key instead of a field. The same peer address in two VRFs
is two records; before, it aborted the whole capture with `ambiguous BGP neighbor`. Two cases
are still refused: the same address twice in one VRF (`ambiguous BGP neighbor <addr> in vrf
<vrf>: multiple instances`) and a neighbor outside any VRF (`not under a vrf`). The schema
refuses a node that holds both `neighbors` and `vrfs`, and a `vrf` field inside a by-VRF record
("the vrf is the key, not a field").

The flat shape every published fixture uses is still read and never written, and those
fixtures report the same findings at the same `bgp.neighbors.<address>` paths; `docs/artifacts`
did not change. Policy looks each snapshot up against its own shape, so a flat pre can meet a
by-VRF post. In a by-VRF snapshot an adjacency checks `bgp.vrfs.<vrf>.neighbors.<address>`, and
one that names no `vrf` checks the default VRF, as routes already did; the `why` names the VRF
it checked. Flat snapshots keep the old rule and wording.

The shape was prepared from Genie 26.8's Ops model and its own IOS XE and NX-OS test data,
which normalize to their `default` and `VRF1` peers. No lab capture of a non-default-VRF peer
existed then; the 2026-11-21 BGP VRF run is the first (PR #17).

### PR #16, the lab script foundation

- `labctl.py` looks commands up in one table, `COMMANDS`, and builds `USAGE` from it. Bad usage
  prints `USAGE` and exits 2 before Genie is imported. `NCV_TESTBED` picks another testbed file.
  Every command that existed sends the same lines to the same router as before;
  `tests/test_labctl_commands.py` runs each one through `main()` against a fake R1 and R2 that
  record one ordered log, and compares the whole log.
- `labctl.py reset` returns a reused reservation to the shipped configuration, so runs whose
  setups conflict can share one. The pure `reset_lines` removes only what the scripts add: the
  `NCV-` ACLs and their bindings, `router bgp` 65001, 65002, and 65010, `router ospf 1`, the
  link's shutdown and OSPF timers, Loopback0, Loopback1, Loopback100, Ethernet0/1.100, a reused
  Ethernet0/3, and vrf NCV. It never touches the management path or the static routes. It is
  pinned on the published configs and on configs built in the tests. It first ran on the routers
  on 2026-11-21, at the start of every run and as a session step, and exited 0 each time. IOS
  keeps listing a subinterface it deleted, so the captures after the VRF run show
  Ethernet0/1.100 down with empty counters; no config holds it and no rule reads it.
- `scripts/lab/_lib.sh` is what the new run scripts source. It asks for each login only when it
  is unset, again until it is not empty, without `bash -x` printing it. It holds the shared
  steps (`lab_reset`, `cap_start`/`cap_stop` with an exit trap that stops a capture an early
  exit left running, `expect_exit`, `expect_findings`, `lab_finish`). A prepared run exits 0
  when every comparison gave its predicted exit and the change comparison found exactly the
  findings in its `expect-<run>.txt` (in `scripts/lab/` until the run is recorded, then beside
  its evidence), 3 when it ran to the end but did not, 1 when it stopped early, and 2 when it
  could not start. `scripts/lab/check_findings.py` does the findings check, and the tests read
  the same expected files. The four run scripts written before `_lib.sh` are unchanged.

### PR #16, the OSPF dead-timer run

`scripts/lab/run-ospf-deadtimer.sh` is the OSPF twin of the hold-timer run. It resets both
routers, sets up OSPF with a 1 s hello (`setup-ospf-fast`; IOS derives the 4 s dead interval),
and stops unless `check-dead-time` reads Hello 1, Dead 4 on both. The change is an inbound ACL
on R1, `NCV-BLOCK-OSPF`, that drops OSPF from R2 (`ospf-block`; `change.sh
deadtimer-apply|deadtimer-undo` by hand), and `wait-ospf-lost` waits for it, because R2 keeps
its entry. The packet capture filters `ip proto 89`, and the new `scripts/lab/link_pcap.py`
prints OSPF packets and BGP segments on one timeline; on the published hold-timer pcap it
prints exactly `summary.txt`. The intent was drafted in `scripts/lab/` and now sits beside the
evidence as `fixtures/lab-2026-11-21/intent-ospf-deadtimer.yaml`.

Predicted findings of the change comparison, pinned on synthetic snapshots built through ncv's
adapter: `V_ADJ` R1 2.2.2.2 (gone) and `V_ADJ` R2 1.1.1.1 (listed in INIT), and no `V_DRIFT`.
The run happened on 2026-11-21 and matched the prediction (PR #17).

### PR #16, the iBGP run

`scripts/lab/run-ibgp.sh` builds iBGP the usual way. `setup-ibgp` gives each router Loopback0
(10.255.255.x/32, in OSPF, the iBGP endpoint) and Loopback1 (172.16.x.1/24, originated into BGP
only), OSPF with a 1 s hello, and iBGP in AS 65010 between the Loopback0s with `update-source
Loopback0` and `timers 3 9`. `wait-ibgp-up` waits for a learned prefix, not only Established.
The change is the dead-timer run's OSPF ACL; nothing about BGP is touched. The capture filters
`ip proto 89 or tcp port 179`. The intent now sits beside the evidence as
`fixtures/lab-2026-11-21/intent-ibgp.yaml`.

Predicted findings, pinned the same way: eight from one cause, in three layers. `V_ADJ` ospf on
R1 and R2, `V_ROUTE` for each peer loopback /32, `V_ADJ` bgp at
`bgp.vrfs.default.neighbors.<loopback>`, and `V_ROUTE` for each 172.16.x.0/24. The packet
prediction was that no NOTIFICATION would reach the wire, the opposite of 2026-11-20. The run
happened on 2026-11-21 and the eight findings matched. The packet prediction held only during
the outage: R2's NOTIFICATION reached the wire after the undo, on the old TCP connection (PR #17).

### PR #16, the BGP VRF run

`scripts/lab/run-bgp-vrf.sh` is the live test of BGP neighbors keyed by VRF. After `reset` it
waits with `wait-vrf-gone`, because IOS deletes a VRF in the background. `setup-bgp-fast` builds
the hold-timer run's global session, and `setup-vrf` adds a second eBGP session to the same
peer address in vrf NCV, on the dot1Q subinterface Ethernet0/1.100, which reuses 1.1.1.1/24 and
1.1.1.2/24. The change is `shutdown` on R1 Ethernet0/1.100 (`change.sh vrf-apply|vrf-undo`).
The capture filters `tcp port 179 or (vlan and tcp port 179)`. The intent now sits beside the
evidence as `fixtures/lab-2026-11-21/intent-bgp-vrf.yaml`.

Predicted findings, pinned on snapshots built through the adapter from a Genie-shaped dict with
the same address under `default` and `NCV`: five, all in vrf NCV. `V_ADJ` R1 1.1.1.2 and R2
1.1.1.1, `V_ROUTE` R1 1.1.1.0/24 and 172.16.102.0/24, and `V_ROUTE` R2 172.16.101.0/24, with
nothing for the default VRF. The run happened on 2026-11-21 and matched the prediction (PR #17).

### PR #16, fixes after a design review

Three reviewers read the designs before any run. What changed:

- By VRF, an adjacency that names no `vrf` is checked in the default VRF. The earlier rule
  ("match the address in exactly one VRF, several is a finding") let a new VRF neighbor change
  a rule about the default session.
- `reset` removes only the BGP processes and interfaces the scripts create, so a reservation
  that ships with another loopback or BGP process keeps it.
- `check-hold-time`, `check-dead-time`, `check-ibgp-hold-time`, and `check-vrf-hold-time` print
  each router's show command and the raw output before their reading, so the first run's log
  records the real text.
- `link_pcap.py` ends an OSPF body at the OSPF packet length, so an LLS block (RFC 5613) is not
  read as neighbors. One Hello is spelled out byte by byte from RFC 2328 A.3.2 in the tests.
- Each prepared run keeps its predicted findings in `expect-<run>.txt` and checks its change
  report against it, instead of trusting the exit code alone.
- `_lib.sh` gained the re-asking prompts, `lab_reset` (a failed reset stops the run), and the
  capture exit trap.

### PR #16, a read-only probe and the SSH path run

`scripts/lab/probe.sh` asks what the sandbox answers and changes nothing. From this machine it
gives the VPN route, a TCP test of ports 22 and 23 on both management addresses that tells
`open`, `refused` (only when bash's connect error says `Connection refused`), `unreachable
(<bash's reason>)` (any other connect error, such as `No route to host`), and `no answer in 3 s`
apart, and a ping. Then `scripts/lab/cml_lab.py inspect`, an inventory of the controller
(after the login, a POST to `/authenticate`, every call is a GET), saved without
configurations, notes, descriptions, canvas annotations, or VNC keys, and `labctl.py probe`, a fixed list of read-only commands on R1 and R2. It ends
with three answers, each with its evidence line: do the management addresses answer on port
22, is R1 Ethernet0/3 free, and which of `nxosv9000`, `cat8000v`, and `iosv` are available.
`cml_lab.py check-login` checks the CML login alone.

The probe ran on 2026-11-21 from 12:58 to 13:00 PT and gave three definite answers. The
management addresses 10.10.20.171 and .172 gave no answer on port 22 or port 23 within 3 s, and
no ping reply over the VPN; the routers themselves report SSH disabled, with no host keys. R1
Ethernet0/3 is free: CML lists it as not connected. All three images exist: `iosv`
(`iosv-159-3-m9`, 512 MiB), `cat8000v` (`cat8000v-17-15-01a`, 4096 MiB), and `nxosv9000`
(`nxosv9300-10-5-1-f`, 12288 MiB).

`scripts/lab/run-ssh-path.sh` tests that the access path does not change the evidence. After a
port check and `reset`, it captures the routers through the console server and then over SSH
(`testbeds/cml-ssh.yaml.example`, copied to the gitignored `testbeds/lab-ssh.yaml`), and
expects `scripts/lab/compare_captures.py` and `ncv diff` against
`fixtures/lab-2026-09-12/intent-routes.yaml` to both exit 0. When the management addresses do
not accept port 22 it exits 4, "not reachable in this sandbox": a result, not a run that
stopped early.

Prediction: both comparisons exit 0, with no difference between the two paths. The run was not
started, because of the probe's first answer. Running it needs another lab whose management
addresses answer, or SSH enabled with host keys on these routers, a configuration change that no
lab script makes and that ncv must not make. No capture has gone over SSH.

### PR #16, the second-platform run

`scripts/lab/run-second-platform.sh nxosv9000|cat8000v|iosv` adds a third router, R3, on another
platform, and breaks the link from R1's end. `cml_lab.py add-r3 <platform>` checks the image,
the free R1 Ethernet0/3, and the memory, creates R3 with a day-0 configuration (OSPF with a 1 s
hello, eBGP AS 65003 with `timers 3 9`, and an admin login whose password is `NCV_LAB_PASS` and
is never printed), checks that CML kept it, links R3, boots it, and starts the link. Every
failure after the node exists names `cml_lab.py remove-r3`. `labctl.py` configures R1's side
only. The testbed is `testbeds/cml-console-r3.yaml.example`, copied to `testbeds/lab-r3.yaml`.
The run leaves R3 in the lab. One intent and one expected-findings file per platform differ
only in R3's interface and its connected-route string (`direct` on NX-OS). The iosv pair now sits
beside its evidence in `fixtures/lab-2026-11-21/`; the nxosv9000 and cat8000v pairs stay in
`scripts/lab/`, and the script picks the directory per platform with one `case`.

In ncv: NX-OS interface records that carry no status are kept with unknown status, as long as
one record in the learn reports a status (checked against Genie 26.8's NX-OS test data). A
device at a first-boot setup dialog fails the capture at connect instead of Unicon answering it,
and the error names the dialog (checked against Unicon's mock devices only).

Predicted findings, pinned on synthetic snapshots built through the adapter from each
platform's Genie shapes: nine. `V_ADJ` ospf and bgp on R1 and on R3, `V_ROUTE` R1 10.1.3.0/24,
3.3.3.3/32, and 172.16.3.0/24, and `V_ROUTE` R3 1.1.1.0/24 and 10.10.10.0/24.

The `iosv` form ran on 2026-11-21 and its nine findings matched the prediction (PR #17).
`add-r3`'s poll saw R3 BOOTED at 181 s (CML's events put it 177 s after STARTED), and R3's
strings in the intent, written before any capture, needed no correction: the no-change check
showed the pre capture met every rule. ncv connected to R3's console with the CML login alone
and captured it three times with no connect error. R3's GigabitEthernet0/0 stayed up and R3 kept
its connected 10.1.3.0/24, so there was no tenth finding.

The `nxosv9000` form was tried that evening, from 21:18 to 21:40 PT, and stopped before any
capture (exit 1). `remove-r3` first took the IOSv R3 out. `add-r3 nxosv9000` then created R3
(image `nxosv9300-10-5-1-f`, 12288 MiB asked with 29757 MiB free), CML kept the day-0
configuration, R1 Ethernet0/3 was linked to R3 Ethernet1/1, and `add-r3` printed R3 BOOTED after
483 s and the link STARTED. R1's side was configured and R1 Ethernet0/3 was up/up, but for 600 s
R1 saw no OSPF neighbor and no BGP peer on that link, and R1's CDP table listed only R2. ncv never
connected to R3. R3, the NX-OS node, was still in the lab when the session ended.

Two read-only checks looked at R3 afterwards, from 21:55 to 22:03 PT. They were ad-hoc scripts
outside the repo: GET calls to the CML API and one console connection made the way ncv makes it.
Nothing was configured. What they showed: CML's events put R3's BOOTED 478 s after STARTED (481 s
after QUEUED), at the `nxosv9000` node definition's 480 s boot timeout, not after a console line.
CML's console log for R3 held 12 characters, against over a million each for R1 and R2, and 44
minutes after the start R3 had sent no packet on its link. Those two set it apart. Its disk
counter did not: R3's virtual machine had read 512 bytes and written none, but R1 and R2, which
run as IOL processes, showed 0 bytes read and written. R3 also kept one of its two virtual CPUs
busy. No booted virtual-machine node was sampled for comparison. The console connection timed
out with an empty buffer.

What follows: R3's virtual machine never loaded NX-OS, and CML's BOOTED state is not proof that a
node booted. (The IOSv R3's BOOTED, 177 s after STARTED in CML's events, most likely came from its
node definition's 180 s timeout too. That is inferred from the timing only: its console log was
not read before the node was deleted. That R3 did boot, as its captures show.) The day-0
configuration, the link, and ncv are not the cause: NX-OS reads its day-0 configuration only once
it runs, the link was up, and ncv never reached a prompt.

Inferred, not proven here: the machine is stuck in its firmware. The likely reason is that the
sandbox's CML host has an AMD processor; a Cisco employee wrote on the Cisco Community on
2024-12-04 that some CML reference images, NX-OSv 9000 among them, have boot issues on AMD. The
attempt says nothing about ncv on NX-OS, which has still never talked to an NX-OS device. The
NX-OS section of `fixtures/lab-2026-11-21/SOURCE.md` has the detail and the Cisco Community link.

The `cat8000v` form has not been tried.

### PR #16, one login for a whole session

`scripts/lab/run-session.sh [name ...]` asks for the logins once and runs the named runs in
order: `probe`, `ospf-deadtimer`, `ibgp`, `bgp-vrf`, `ssh-path`, `second-platform:<platform>`,
`reset`, and `remove-r3` (by default `probe ospf-deadtimer ibgp bgp-vrf reset`). The logins last
only while a script runs, so `reset` and `remove-r3` run `labctl.py reset` and `cml_lab.py
remove-r3` with the logins the session asked for. It refuses an unknown name or platform, a
missing testbed file a named run needs, or an R3 testbed whose `os` does not fit the platform,
before any prompt, asks again until each password is not empty (the routers' SSH login only when
`ssh-path` is named), and checks the CML login once with `cml_lab.py check-login`. Each run gets
its own `NCV_STAMP`, so the closing table, on the screen and in
`output/lab/session-<stamp>.log`, names each run's log and, for a run that stopped early, its
last step before the capture cleanup. A failed run does not stop the session, since the next
run starts with `reset`; a run that could not start (exit 2) or a failed probe does, and the
script prints the names still to run as a ready command. Ctrl-C prints the table so far and the
same command. Besides the stand-in run scripts in `tests/test_lab_lib.py`, it drove three real
sessions on 2026-11-21: `probe ospf-deadtimer ibgp bgp-vrf reset` and `second-platform:iosv
reset`, with every run exit 0, and in the evening `remove-r3 second-platform:nxosv9000 reset`.
There the NX-OS run stopped early (exit 1), the table named its last step, and the reset still
ran. The logs show the logins were accepted; they do not show whether they were typed at the
`read -rsp` prompt or already set.

### PR #16, fixes after an examination of the whole branch

Once the eight pieces above were built, the whole branch was examined again before any run, and
a second set of fixes followed. None of it had run against a lab when it merged. What changed:

- **The tool**: the capture's first-boot guard also refuses NX-OS's `Do you want to enforce
  secure password standard` question. A failed `show running-config` read names only the
  exception's type, because Unicon's timeout and failure messages quote the device's output so
  far, and during that read the output is a running config with its passwords. A connect the
  guard stopped says `device is at a first-boot setup dialog; ncv will not answer it`:
  Unicon reports it as its own `failed to connect`, with the guard's reason only in the chain
  of causes, so ncv looks for its own exception type there.
- **The lab scripts**: `labctl.py reset` prints `<router>: show running-config failed (<type>)`
  and exits 1 when that read fails, with no device output. `vrf_listed` counts IOS's `* NCV` row
  for a VRF still being deleted, and `setup-vrf` ends the subinterface block with `no shutdown`.
  `compare_captures.py` also withholds lines with `authentication`, `snmp-server host`, or
  `psk`. `sanitize_capture.py` copies every stage directory a run holds (any subdirectory with
  a `config.json`, so the SSH path run's `console/` and `ssh/` too), exits 2 with its usage when
  there is none, and checks the source before it creates anything; for `pre/ post/ restored/`
  its output is unchanged. Every prepared script answers `-h` with its header and starts
  nothing, and the five that take no argument refuse any other with exit 2. `lab_tcp` tells `open`,
  `refused` (only `Connection refused`), `unreachable (<bash's reason>)`, and `no answer in 3 s`
  apart. `run-ssh-path.sh` numbers its steps 1/7 to 7/7 as the README does, and a failed reset
  points at `run-session.sh reset`.
- **The CML client**: `add-r3` gives up 3 minutes after the start on an R3 still `STOPPED`
  instead of polling for 20 minutes, and reads the new node back with
  `?exclude_configurations=false`, the query Cisco's virl2_client 2.7.1 sends. `remove-r3` also
  accepts `DEFINED_ON_CORE` after the stop, so one run removes a node that never started. The
  inventory also drops canvas annotations and VNC keys, and a 403 on the node POST also names
  the licence's node limit. On 2026-11-21 `add-r3` created R3 twice, and each time the read-back
  said CML kept the day-0 configuration; `remove-r3` ran once and took out the booted IOSv R3.
- **The session script**: `remove-r3` is a session name, run like `reset` with the logins the
  session asked for, since the logins last only while a script runs. The session refuses a
  missing `testbeds/lab-ssh.yaml` or R3 testbed, or an R3 `os` that does not fit the platform,
  before any prompt. "Where it stopped" is the last step before the capture cleanup, and a
  failed probe has none.
- **The documents**: `scripts/lab/README.md` names the three runs that can be pointed at
  `testbeds/lab-ssh.yaml` instead of saying every run can; the R3 testbed example says what
  `SENDLINE_AFTER_CRED` is for; `docs/LIVE.md` says the first-boot guard was checked against
  Unicon's mock devices only; the README counts four live runs; the publishing steps under
  "Open" say where a run's packet capture goes; and the second-platform assumptions add a
  console server that replays old output, whose first-boot dialog ncv would refuse, and say
  that one Enter can reach such a dialog before ncv stops the connect. New tests hold
  `scripts/lab/README.md` to the code: the SSH sentence, each prediction table against its
  expected file, and each configuration block against its builder.

### PR #17, the 2026-11-21 evidence

Four of the runs PR #16 prepared happened on 2026-11-21, in the same reservation as the 2026-11-20
runs (CML 2.7.2, R1 and R2 on IOS XE 17.15 IOL), driven by `run-session.sh` at `630402c` in two
sessions: the probe, the OSPF dead-timer, iBGP, and BGP VRF runs, and a reset, from 12:58 to 13:27
PT; then the second-platform run with R3 on IOSv, and a reset, from 13:34 to 13:49 PT. Every step
exited 0. All four change comparisons matched the prediction: each gave exactly the findings of
its expect file, written and merged before the run (PR #16), and each no-change check and
restored comparison gave 0 findings. The packet predictions are a separate matter: the iBGP one
did not hold (see below).

- **OSPF dead timer**: 2 findings, `V_ADJ` on R1 (2.2.2.2 gone) and on R2 (1.1.1.1 in `init`). An
  inbound ACL on R1 denied OSPF from R2; nothing was shut down.
- **iBGP over OSPF**: 8 findings from the same ACL. `V_ADJ` for both OSPF neighbors and both iBGP
  peers (`Established` to `Idle`), and `V_ROUTE` for each peer's Loopback0 /32 (`ospf`) and
  Loopback1 /24 (`bgp`). It is the first capture written in the by-VRF BGP layout.
- **BGP in vrf NCV**: 5 findings, all in vrf NCV, and none for the global session to the same
  address, which stayed Established. It is the first real capture with peers in two VRFs.
- **Second platform, R3 on IOSv**: 9 findings, on R1 and R3. The captures record R3 as IOS
  `version 15.9`; `15.9(3)M9` comes from the CML image name `iosv-159-3-m9`. Genie's output for
  classic IOS normalized into the same snapshot layout as IOS XE with no adapter change. R3's
  GigabitEthernet0/0 stayed up and R3 kept its connected 10.1.3.0/24, which is why there are nine
  findings and not ten. R2 was not unaffected: it lost three routes it had learned through R1,
  with no finding because the intent does not list R2. This run has no packet capture, so R3's
  snapshot shows its OSPF neighbor gone and its BGP peer `Active`, not why.

The no-change check compares each pre capture with itself, so it shows the pre capture met every
rule. In all four runs the normalized JSON of restored equals pre, but the lab did not return to
an identical state: config text differs in timestamps and stray blank lines, the OSPF DR and BDR
roles swapped after recovery in the two runs whose OSPF was captured on the wire, and the BGP
sessions came back on new TCP ports. ncv compares none of those.

The three R1-R2 runs captured their link through `cml_capture.py`. What the pcaps added:

- **OSPF dead timer**: R2's Hellos stayed on the wire through the block while R1's Hellos stopped
  listing R2, 4.0 s after an R2 Hello. That R1 timed R2 out on its dead interval is inferred, not
  shown.
- **iBGP**: the written packet prediction did not hold. During the outage no NOTIFICATION was on
  the link, only 150.4 s with no port-179 segment at all. But R2's "Hold Timer Expired"
  NOTIFICATION reached the wire after the undo, on the old TCP connection, and R1 answered it with
  a reset. R1's own NOTIFICATION never appears.
- **BGP VRF**: the VRF session rode 802.1Q VLAN 100, so a CML link capture keeps the tag. R1 went
  silent on VLAN 100. R2 sent one NOTIFICATION 4/0 Hold Timer Expired at 13.3 s, 9.6 s after R1's
  last keepalive, and retransmitted it at 21.2 s; `summary.txt` shows two NOTIFICATION lines
  because `link_pcap.py` does not mark repacketized retransmissions. The untagged global session
  ran on untouched.

Not recorded: the SSH path run, never started because the probe showed the management addresses
do not answer (see "PR #16, a read-only probe and the SSH path run"); the NX-OS attempt that
evening, which stopped before any capture because R3 never loaded NX-OS (see "PR #16, the
second-platform run"); and Catalyst 8000V, not tried.

The sanitized captures are in `fixtures/lab-2026-11-21`, one directory per run (`ospf-deadtimer`,
`ibgp`, `bgp-vrf`, `second-platform-iosv`), with a `SOURCE.md` that tells each run step by step,
what was sanitized, and what the evidence does not establish. The pcaps and their `summary.txt`
are in `ospf-deadtimer-pcap`, `ibgp-pcap`, and `bgp-vrf-pcap`. `tests/test_lab_evidence.py`
replays the captures and the pcaps (see "Test count"). `docs/artifacts/lab-2026-11-21-<run>-post.*`
and four more blocks in `lab-findings.svg` come from `render_artifacts.py`. The README,
`docs/LIVE.md`, `docs/EXPLAIN.md`, and `scripts/lab/README.md` say what ran.

What moved: each recorded run's intent and expect file went from `scripts/lab/` to
`fixtures/lab-2026-11-21/`, with their rules and findings unchanged and only their headers
reworded, as `intent-bgp-holdtimer.yaml` moved in PR #14. The run scripts and the tests read them
from there. `run-second-platform.sh` picks the directory per platform with one `case`: `iosv` from
`fixtures/lab-2026-11-21`, `nxosv9000` and `cat8000v` from `scripts/lab`, which have no recorded
run.

## Test count

**609 tests.** The 50 that existed at `11ee5bd` all survive the reorganization, plus
the 2 policy regressions from PR #1, the 21 that came with BGP support and feature
selection, 3 covering report provenance and the version flag, 1 that loads both
bundled intents so the lab template cannot rot unnoticed, 2 covering the interface shape
Genie actually learns, 6 that replay the lab evidence, 2 that pin the lab sanitizer, 3
that pin the BGP run's parsers, intent, and predicted findings, 3 that replay the BGP
evidence, and 12 more from PR #11 (13 new, one replaced): the artifact rebuild, a learn
with no `info` in the adapter and in a capture, a BGP shape with no neighbors in place of
the old empty-mapping test, an empty mapping refused for each of the five feature names,
three empty `--features` values, and a repeated feature. PR #12 brought `main` to 109. The
hold-timer branch adds 12: 6 in `tests/test_lab_scripts.py` (the timers parser, the setup,
block, and unblock lines, the draft intent, the predicted findings, and a pre capture without
the timers failing the no-change check) and 6 in `tests/test_bgp_pcap.py` on captures built
byte by byte. PR #14 adds 4 that replay the hold-timer captures, and PR #15 6, which made 131.

PR #16 adds 448, in build order: 20 for BGP keyed by VRF (in `tests/test_normalize.py`,
`test_schema.py`, `test_policy.py`, and `test_snapshot.py`); 40 for the script foundation (7 in
`tests/test_lab_scripts.py` pinning `reset`, 33 in the new `tests/test_labctl_commands.py`
fake lab); 46 for the OSPF dead-timer run (`test_lab_scripts.py`, `test_labctl_commands.py`,
`test_cml_capture.py`, and the new `tests/test_link_pcap.py`); 19 for the iBGP run and 26 for
the BGP VRF run (`test_lab_scripts.py` and `test_labctl_commands.py`); 74 in the review fixes
(18 in `test_policy.py` and `test_schema.py` for the default-VRF rule, 7 for the OSPF timers
parser, the fake lab's order and printouts, and the OSPF decoder, and 49 in the new `tests/test_check_findings.py` and
`tests/test_lab_lib.py` with the expected-file reads in `test_lab_scripts.py`); 37 for the probe
and the SSH path (the new `tests/test_cml_lab.py` and `tests/test_compare_captures.py`, plus
`test_labctl_commands.py`, `test_lab_scripts.py`, `test_cml_capture.py`, and
`test_lab_lib.py`); 89 for the second-platform run (`test_normalize.py`, `test_live.py`,
`test_cml_lab.py`, `test_labctl_commands.py`, `test_lab_scripts.py`, `test_lab_lib.py`, and
`test_check_findings.py`); 15 for the session script (12 in `test_lab_lib.py`, 3 in
`test_lab_scripts.py`); and 82 in the second set of fixes: 25 for the tool and the Python lab
scripts (`test_live.py`, `test_labctl_commands.py`, `test_lab_scripts.py`,
`test_compare_captures.py`, and `test_schema.py`), 15 for the CML client (`test_cml_lab.py`), 35
for the shell (34 in `test_lab_lib.py`, 1 in `test_lab_scripts.py`), and 7 that hold the README
to the code (6 in `test_lab_scripts.py`, 1 in `test_lab_evidence.py`). The 80 tests in
`tests/test_lab_lib.py` run the shell scripts under bash and are skipped on Windows; the Ubuntu
CI jobs run them.

PR #17 adds 30 in `tests/test_lab_evidence.py` (15 before, 45 now), for the four 2026-11-21
runs: each change comparison gives exactly its recorded findings, and those equal its expect
file; each no-change and restored comparison is clean; each post capture holds the change and
the states `SOURCE.md` names (the ACL or shutdown lines, the neighbor and session states, the
routes lost, in the second-platform run only R2's, and in three runs the status of both ends of
the changed link); restored equals pre outside the config text; and each of the three link
summaries is what `link_pcap.py` reads from its pcap, with the timeline facts `SOURCE.md` relies
on pinned (the Hello neighbor lists and the DR/BDR swap, the iBGP gap, the late NOTIFICATION and
the reset, and the VLAN 100 NOTIFICATION and its retransmission). `tests/test_lab_scripts.py`
and `tests/test_check_findings.py` read the moved intent and expect files from their new place,
with the same number of tests as before.

## Verify

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest                      # 609 passed (on Windows: 529 passed, 80 skipped)
git diff --check                       # clean
python3 scripts/render_artifacts.py    # rewrites docs/artifacts with identical bytes
git status --short docs/artifacts      # lists nothing (on Windows, run git diff instead;
                                       # the rewrite swaps a CRLF checkout for LF)

python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/ci
# exits 1, 8 findings: V_ADJ 3, V_ROUTE 2, V_ERR 1, V_DRIFT 2

python3 -m ncv diff fixtures/pre fixtures/pre --intent intents/demo.yaml --report output/clean
# exits 0, 0 findings
```

The Windows machine has no `python3` and no `py` launcher on `PATH` -- only the
Microsoft Store `python`, which cannot see an editable install. Build a virtualenv and
run the commands through it, substituting `.venv/Scripts/python.exe` for `python3`:

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

## Invariants -- do not regress

- **Offline-first.** `genie`/`pyats` are imported inside `snapshot_live` only, after the
  lab flag check. The suite must pass with neither installed, and CI asserts their absence.
- **Live capture is opt-in.** `--i-am-in-a-lab` is mandatory; `snapshot_live` raises
  `PermissionError` without it, before importing Genie and before creating output.
- **No configuration push.** There is no `configure`/push path, and the fake-lab test
  asserts `device.configure` is never called. ncv never answers a first-boot setup dialog
  either: `snapshot_live` passes Unicon a `connect_reply` guard that fails the connection at
  NX-OS POAP, its secure-password or admin-password prompt, the IOS setup dialog, or `Enter
  enable secret`,
  because Unicon would otherwise answer them and so configure the device during a capture.
- **A learn that returns nothing fails the capture.** Never turn a missing Genie `info`
  into an empty section: it would hide a parser failure as a lost neighbor.
- **`docs/artifacts` is what the code writes.** Rebuild it with
  `scripts/render_artifacts.py` whenever a report changes; `tests/test_artifacts.py`
  enforces it.
- **Old snapshots stay readable.** The flat BGP shape in the published fixtures keeps loading
  and reporting the same findings and paths.
- **Claims match the evidence.** Eight live runs with published snapshots have happened in a
  DevNet CML sandbox, all with
  R1 and R2 on IOS XE 17.15 IOL in its `default-lab`, reached through the CML console server, and
  Genie 26.8: two on 2026-09-12 (`fixtures/lab-2026-09-12`), one on static routes and one with
  OSPF; one on 2026-09-18 (`fixtures/lab-2026-09-18`) with eBGP lost to an administrative
  shutdown; one on 2026-11-20 (`fixtures/lab-2026-11-20`) with the same session lost to a
  hold-timer expiry; and four on 2026-11-21 (`fixtures/lab-2026-11-21`): an OSPF adjacency lost
  to an inbound ACL, iBGP over OSPF, BGP in vrf NCV, and a third router, R3, on IOSv (classic IOS
  15.9). The evidence covers no NX-OS or Catalyst 8000V capture (the NX-OS attempt stopped before
  any), no SSH path, nothing beyond IPv4 unicast, and no other Genie release. The no-change check
  shows a pre capture met every rule, not that two captures agreed; a restored comparison with 0
  findings is not an identical lab; ncv's interface rules check error counters only, never
  up/down; and a mechanism such as a timer expiry or a NOTIFICATION is claimed only where a pcap
  shows it. Nothing in the repo may claim more than that evidence shows, and synthetic fixtures
  are never relabeled as captures.

## Open

What is open:

- **NX-OS evidence needs another lab.** On 2026-11-21 the NX-OS R3's virtual machine never
  loaded NX-OS (see "PR #16, the second-platform run"). Whether NX-OS 9000v can boot in this
  sandbox at all rests on that one attempt. Any lab where an NX-OS 9000v actually boots, reached
  over SSH or a console, would do. Everything about ncv on NX-OS is still open: the console login
  with two credentials, a first-boot dialog, and Genie's NX-OS output through the adapter. ncv has
  never talked to an NX-OS device, so its NX-OS handling still rests on Genie's test data and
  Unicon's mock devices. When the evening session ended R3, the NX-OS node, was still in the lab;
  on that reservation, `bash scripts/lab/run-session.sh remove-r3` takes it out.
- **`add-r3` trusts CML's BOOTED state.** That state came from the node definition's boot
  timeout, not from a console line, so the NX-OS run waited ten minutes on R1 for a router that
  never ran. `add-r3` should check the boot by something better before that wait, such as R3's
  console log or the packets it sends on its link. The disk counter alone would not do: the
  running IOL routers R1 and R2 showed 0 bytes read and written, while the stuck R3 showed 512
  bytes read and none written.
- **Unicon at an NX-OS loader prompt** (`src/ncv/live.py`): found the same evening, offline
  against Unicon 26.8's mock n9k device only. With ncv's connect arguments, Unicon's NX-OS plugin
  answers a device at a loader prompt by sending `boot`, and one at a boot-mode prompt by sending
  `load-nxos`, and ncv's first-boot guard does not cover those prompts. No real device was
  affected. This branch does not fix it.
- **Catalyst 8000V**: still untried. The probe lists `cat8000v` (`cat8000v-17-15-01a`, 4096 MiB). Its
  intent and expect file are in `scripts/lab/`, and `testbeds/lab-r3.yaml` must give R3 `os:
  iosxe`. With no R3 in the lab, `bash scripts/lab/run-session.sh second-platform:cat8000v
  remove-r3` runs it and takes R3 out afterwards.
- **The SSH path**: it cannot run in this sandbox. It needs another lab whose management addresses
  answer, or SSH enabled with host keys on the routers. That is a configuration change no lab
  script makes, and ncv must not make it.
- **Sanitizer gaps** that no capture has triggered yet. `sanitize_capture.py` lets these through
  with their values: `enable algorithm-type scrypt secret`; a `username` line with
  `algorithm-type` or `view` before `secret`; BGP `neighbor <address> password`; key-chain
  `key-string`; TACACS and RADIUS keys; SNMP communities and IOS-form v3 users; OSPF
  authentication and message-digest keys; NTP authentication keys; ISAKMP and pre-shared keys;
  `ppp chap password`; the body of an enrolled (not self-signed) certificate; `license udi`
  serials; and the user named in `! Last configuration change ... by <user>`. It has no catch-all
  for a hash or type 7 string under another keyword, and a certificate block cut off before
  `quit` silently drops the rest of the config. Read every new capture's configs before
  publishing it.
- **The pcap decoder**: `link_pcap.py` does not mark retransmissions that TCP repacketized. In the
  BGP VRF summary, R2's one NOTIFICATION appears twice (13.3 s, and its retransmission at 21.2 s).
- **What ncv does not compare**: OSPF DR and BDR roles, interface up/down (the interface rules
  check error counters only), TCP connections and ports, config lines no rule names, and devices
  the intent does not list. On 2026-11-21 each of these changed with no finding: the roles swapped
  after recovery, R1 Ethernet0/3 went down, sessions came back on new ports, the ACL lines
  appeared, and R2 lost three routes in the second-platform run. Whether any of them should
  become a rule has not been decided.

What the 2026-11-21 sessions settled among the assumptions PR #16 listed as most likely to differ
from each prediction:

- **Probe**: all three answers came back definite, and CML lists R1 Ethernet0/3 as not connected.
  The per-node image still prints as `unknown`.
- **OSPF dead timer**: after the inbound ACL went on, R2's Hellos stayed on the wire and R1 lost
  its neighbor; Genie reported R2's neighbor in `init` rather than leaving it out; and CML
  accepted `ip proto 89` as a capture filter.
- **iBGP**: both sessions were out of Established at the poll at 13:12:50, inside `wait-ibgp-down
  60`, and Genie labeled the routes `ospf` and `bgp`.
- **BGP VRF**: IOL accepted the dot1Q subinterface, the CML link carried the VLAN 100 tag and the
  link capture kept it, and Genie filed the VRF neighbor under vrf NCV.
- **SSH path**: the management addresses gave no answer on port 22 within 3 s, and the routers
  report SSH disabled with no host keys. Whether their SSH server would accept the client's key
  exchange and host key algorithms was not reached.
- **Second platform**: the sandbox has all three images, with 29783 MiB free before the IOSv run;
  this login may add nodes; CML kept a day-0 configuration sent as one string; CML linked R1 while
  it ran; `add-r3`'s poll saw the IOSv R3 BOOTED after 181 s; and the IOSv R3's interface
  stayed up when R1 shut its end, so there was no tenth finding. For NX-OS, `add-r3` printed R3
  BOOTED after 483 s, but CML's events put that state 478 s after STARTED, at the node
  definition's 480 s boot timeout: R3's virtual machine never loaded NX-OS. The IOSv R3's BOOTED,
  177 s after STARTED in CML's events, most likely came from its node definition's 180 s timeout
  too; that is inferred from the timing only.
- **The session script**: it drove three real sessions (see "PR #16, one login for a whole
  session").

A run that came out as predicted is published as PR #17 published the 2026-11-21 runs: sanitize
its captures into `fixtures/lab-<date>/<run>` with `scripts/lab/sanitize_capture.py`, move its
intent and `expect-<run>.txt` beside them with a `SOURCE.md`, point its run script and the tests
at the new place, add tests that replay the captures to `tests/test_lab_evidence.py`, rebuild
`docs/artifacts` if a report is added there, and update the README, `docs/LIVE.md`, this file,
and "Claims match the evidence". If the run saved a packet capture, copy
`captures/<run>-<stamp>/link.pcap` and `output/lab/<run>-<stamp>-pcap.txt` (under
`run-session.sh` the stamp ends in the run's number, `-<n>`) to
`fixtures/lab-<date>/<run>-pcap/link.pcap` and `summary.txt`, after checking that it holds only
lab addresses, as PR #15 published the hold-timer pcap; `sanitize_capture.py` does not copy it.
A run that did not come out as predicted is published the same way, with what happened: its
`SOURCE.md` and the README say which part of the prediction was wrong, and the expected file
stays as the prediction that was made.

Still open from the design review and the examination of the branch, which no change in PR #16
or PR #17 settled:

- OSPF neighbors are still keyed by router id only, so the same router id on two links is still
  refused. Keying them by interface or VRF, as BGP now is by VRF, has not started.
- Whether CML allows two captures on one link at once; the 2026-11-21 runs did not try. The
  capture exit trap stops a capture a run leaves behind after an ordinary early exit, but not
  after a killed shell or a VPN drop.
- Whether `show vrf` lists NCV while IOS is still deleting it; the BGP VRF run's own reset found
  no NCV to wait for.
- `SENDLINE_AFTER_CRED` for R1 and R2 in `testbeds/cml-console.yaml.example`. It was verified
  offline to clear a leftover `Password:` prompt, a possible second cause of the 2026-11-20
  `CredentialsExhaustedError` failures, and not adopted there, because the published path works
  without it. It is used on the NX-OS R3's connection only, in
  `testbeds/cml-console-r3.yaml.example` (checked against Unicon's mock devices only); the IOS
  form that reached the IOSv R3 does not set it.
- `lab_finish` warns when a password value appears in a run log; a very short password can
  give a false warning. No 2026-11-21 log has the warning.

Ideas not started: the always-on DevNet sandboxes as a capture-only source of more images, and
OSPF neighbors keyed by interface or VRF (above).
