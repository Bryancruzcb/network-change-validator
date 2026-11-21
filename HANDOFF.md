# Handoff

Working notes for whoever picks this up next. The merged work is on `main`; the prepared lab
runs are on the branch `lab/next-runs`.

## Current state

- Everything below up to "PR #15" is on `main`. PRs [#1](https://github.com/Bryancruzcb/network-change-validator/pull/1)
  through [#11](https://github.com/Bryancruzcb/network-change-validator/pull/11) went in as
  fast-forwards, so every hash quoted in these notes is the hash the commit carries on
  `main`. Six commits on 2026-09-18 went straight to `main` without a PR (see "Direct
  commits"). No open PRs, no open issues, and every merged branch is deleted.
- PR #12 went in as a squash (`e539627`). PRs #13, #14, and #15 went in as fast-forwards, so
  `ee58e95`, `017541c`, and `914431e` are the hashes their commits carry on `main`.
- The branch `lab/next-runs` holds eight pieces of prepared work and two rounds of fixes, one
  after a design review and one after an examination of the whole branch, described below from
  "Branch `lab/next-runs`, BGP neighbors keyed by VRF" on. None of it is merged and none of it
  has run against a lab. `main` is unchanged at `914431e`.
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
  capture on a link has not been checked.
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

### Branch `lab/next-runs`, BGP neighbors keyed by VRF

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
exists yet.

### Branch `lab/next-runs`, the lab script foundation

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
  pinned on the published configs and on configs built in the tests; it has not run on a
  router.
- `scripts/lab/_lib.sh` is what the new run scripts source. It asks for each login only when it
  is unset, again until it is not empty, without `bash -x` printing it. It holds the shared
  steps (`lab_reset`, `cap_start`/`cap_stop` with an exit trap that stops a capture an early
  exit left running, `expect_exit`, `expect_findings`, `lab_finish`). A prepared run exits 0
  when every comparison gave its predicted exit and the change comparison found exactly the
  findings in its `scripts/lab/expect-<run>.txt`, 3 when it ran to the end but did not, 1 when
  it stopped early, and 2 when it could not start. `scripts/lab/check_findings.py` does the
  findings check, and the tests read the same expected files. The four published run scripts
  are unchanged.

### Branch `lab/next-runs`, the OSPF dead-timer run, prepared and not run

`scripts/lab/run-ospf-deadtimer.sh` is the OSPF twin of the hold-timer run. It resets both
routers, sets up OSPF with a 1 s hello (`setup-ospf-fast`; IOS derives the 4 s dead interval),
and stops unless `check-dead-time` reads Hello 1, Dead 4 on both. The change is an inbound ACL
on R1, `NCV-BLOCK-OSPF`, that drops OSPF from R2 (`ospf-block`; `change.sh
deadtimer-apply|deadtimer-undo` by hand), and `wait-ospf-lost` waits for it, because R2 keeps
its entry. The packet capture filters `ip proto 89`, and the new `scripts/lab/link_pcap.py`
prints OSPF packets and BGP segments on one timeline; on the published hold-timer pcap it
prints exactly `summary.txt`. The draft intent is `scripts/lab/intent-ospf-deadtimer.yaml`.

Predicted findings of the change comparison, pinned on synthetic snapshots built through ncv's
adapter: `V_ADJ` R1 2.2.2.2 (gone) and `V_ADJ` R2 1.1.1.1 (listed in INIT), and no `V_DRIFT`.
Nothing has run against a lab and no document claims otherwise.

### Branch `lab/next-runs`, the iBGP run, prepared and not run

`scripts/lab/run-ibgp.sh` builds iBGP the usual way. `setup-ibgp` gives each router Loopback0
(10.255.255.x/32, in OSPF, the iBGP endpoint) and Loopback1 (172.16.x.1/24, originated into BGP
only), OSPF with a 1 s hello, and iBGP in AS 65010 between the Loopback0s with `update-source
Loopback0` and `timers 3 9`. `wait-ibgp-up` waits for a learned prefix, not only Established.
The change is the dead-timer run's OSPF ACL; nothing about BGP is touched. The capture filters
`ip proto 89 or tcp port 179`. The draft intent is `scripts/lab/intent-ibgp.yaml`.

Predicted findings, pinned the same way: eight from one cause, in three layers. `V_ADJ` ospf on
R1 and R2, `V_ROUTE` for each peer loopback /32, `V_ADJ` bgp at
`bgp.vrfs.default.neighbors.<loopback>`, and `V_ROUTE` for each 172.16.x.0/24. The packet
prediction is that no NOTIFICATION reaches the wire, the opposite of 2026-11-20. Nothing has run
against a lab and no document claims otherwise.

### Branch `lab/next-runs`, the BGP VRF run, prepared and not run

`scripts/lab/run-bgp-vrf.sh` is the live test of BGP neighbors keyed by VRF. After `reset` it
waits with `wait-vrf-gone`, because IOS deletes a VRF in the background. `setup-bgp-fast` builds
the hold-timer run's global session, and `setup-vrf` adds a second eBGP session to the same
peer address in vrf NCV, on the dot1Q subinterface Ethernet0/1.100, which reuses 1.1.1.1/24 and
1.1.1.2/24. The change is `shutdown` on R1 Ethernet0/1.100 (`change.sh vrf-apply|vrf-undo`).
The capture filters `tcp port 179 or (vlan and tcp port 179)`. The draft intent is
`scripts/lab/intent-bgp-vrf.yaml`.

Predicted findings, pinned on snapshots built through the adapter from a Genie-shaped dict with
the same address under `default` and `NCV`: five, all in vrf NCV. `V_ADJ` R1 1.1.1.2 and R2
1.1.1.1, `V_ROUTE` R1 1.1.1.0/24 and 172.16.102.0/24, and `V_ROUTE` R2 172.16.101.0/24, with
nothing for the default VRF. Nothing has run against a lab and no document claims otherwise.

### Branch `lab/next-runs`, fixes after a design review

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

### Branch `lab/next-runs`, a read-only probe and the SSH path run, prepared and not run

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

`scripts/lab/run-ssh-path.sh` tests that the access path does not change the evidence. After a
port check and `reset`, it captures the routers through the console server and then over SSH
(`testbeds/cml-ssh.yaml.example`, copied to the gitignored `testbeds/lab-ssh.yaml`), and
expects `scripts/lab/compare_captures.py` and `ncv diff` against
`fixtures/lab-2026-09-12/intent-routes.yaml` to both exit 0. When the management addresses do
not accept port 22 it exits 4, "not reachable in this sandbox": a result, not a run that
stopped early.

Prediction: both comparisons exit 0, with no difference between the two paths. Nothing has run
against a lab and no document claims otherwise.

### Branch `lab/next-runs`, the second-platform run, prepared and not run

`scripts/lab/run-second-platform.sh nxosv9000|cat8000v|iosv` adds a third router, R3, on another
platform, and breaks the link from R1's end. `cml_lab.py add-r3 <platform>` checks the image,
the free R1 Ethernet0/3, and the memory, creates R3 with a day-0 configuration (OSPF with a 1 s
hello, eBGP AS 65003 with `timers 3 9`, and an admin login whose password is `NCV_LAB_PASS` and
is never printed), checks that CML kept it, links R3, boots it, and starts the link. Every
failure after the node exists names `cml_lab.py remove-r3`. `labctl.py` configures R1's side
only. The testbed is `testbeds/cml-console-r3.yaml.example`, copied to `testbeds/lab-r3.yaml`.
The run leaves R3 in the lab. One draft intent and one expected-findings file per platform
differ only in R3's interface and its connected-route string (`direct` on NX-OS).

In ncv: NX-OS interface records that carry no status are kept with unknown status, as long as
one record in the learn reports a status (checked against Genie 26.8's NX-OS test data). A
device at a first-boot setup dialog fails the capture at connect instead of Unicon answering it
(checked against Unicon's mock devices only).

Predicted findings, pinned on synthetic snapshots built through the adapter from each
platform's Genie shapes: nine. `V_ADJ` ospf and bgp on R1 and on R3, `V_ROUTE` R1 10.1.3.0/24,
3.3.3.3/32, and 172.16.3.0/24, and `V_ROUTE` R3 1.1.1.0/24 and 10.10.10.0/24. Nothing has run
against a lab and no document claims otherwise.

### Branch `lab/next-runs`, one login for a whole session

`scripts/lab/run-session.sh [name ...]` asks for the logins once and runs the named runs in
order: `probe`, `ospf-deadtimer`, `ibgp`, `bgp-vrf`, `ssh-path`, `second-platform:<platform>`,
`reset`, and `remove-r3` (by default `probe ospf-deadtimer ibgp bgp-vrf reset`). The logins last
only while a script runs, so `reset` and `remove-r3` run `labctl.py reset` and `cml_lab.py
remove-r3` with the logins the session asked for. It refuses an unknown name or platform, or a
testbed file a named run needs (R3's `os` included), before any prompt, asks again until each
password is not empty (the routers' SSH login only when `ssh-path` is named), and checks the CML
login once with `cml_lab.py check-login`. Each run gets its own `NCV_STAMP`, so the closing
table, on the screen and in `output/lab/session-<stamp>.log`, names each run's log and, for a
run that stopped early, its last step before the capture cleanup. A failed run does not stop the session, since the next
run starts with `reset`; a run that could not start (exit 2) or a failed probe does, and the
script prints the names still to run as a ready command. Ctrl-C prints the table so far and the
same command. It has run only against stand-in run scripts in `tests/test_lab_lib.py`.

### Branch `lab/next-runs`, fixes after an examination of the whole branch

Once the eight pieces above were built, the whole branch was examined again before any run, and
a second set of fixes followed. None of it has run against a lab. What changed:

- **The tool**: the capture's first-boot guard also refuses NX-OS's `Do you want to enforce
  secure password standard` question. A failed `show running-config` read names only the
  exception's type, because Unicon's timeout and failure messages quote the device's output so
  far, which there is a running config with its passwords.
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
  the licence's node limit.
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
  console server that replays old output, whose first-boot dialog ncv would refuse without
  naming it. New tests hold `scripts/lab/README.md` to the code: the SSH sentence, each
  prediction table against its expected file, and each configuration block against its
  builder.

## Test count

**573 tests on `lab/next-runs`, 131 on `main`.** The 50 that existed at `11ee5bd` all survive the reorganization, plus
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
byte by byte. PR #14 adds 4 that replay the hold-timer captures, and PR #15 6.

`lab/next-runs` adds 442, in build order: 20 for BGP keyed by VRF (in `tests/test_normalize.py`,
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
`test_lab_scripts.py`); and 76 in the second set of fixes: 19 for the tool and the Python lab
scripts (`test_live.py`, `test_labctl_commands.py`, `test_lab_scripts.py`,
`test_compare_captures.py`, and `test_schema.py`), 15 for the CML client (`test_cml_lab.py`), 35
for the shell (34 in `test_lab_lib.py`, 1 in `test_lab_scripts.py`), and 7 that hold the README
to the code (6 in `test_lab_scripts.py`, 1 in `test_lab_evidence.py`). The 80 tests in
`tests/test_lab_lib.py` run the shell scripts under bash and are skipped on Windows; the Ubuntu
CI jobs run them.

## Verify

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest                      # 573 passed (on Windows: 493 passed, 80 skipped)
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
- **Claims match the evidence.** Four live runs have happened against IOS XE 17.15 IOL in a
  DevNet CML sandbox: two on 2026-09-12 (`fixtures/lab-2026-09-12`), one on static routes and
  one with OSPF, one on 2026-09-18 (`fixtures/lab-2026-09-18`) with eBGP lost to an
  administrative shutdown, and one on 2026-11-20 (`fixtures/lab-2026-11-20`) with the same
  session lost to a hold-timer expiry. Nothing in the repo may
  claim more than that evidence shows, and synthetic fixtures are never relabeled as
  captures.

## Open

The five prepared runs on `lab/next-runs` wait for a reservation: the OSPF dead-timer run, the
iBGP run, the BGP VRF run, the SSH path run, and the second-platform run. The probe has not run
either. Run them from the WSL clone (`~/network-change-validator`) on that branch, in this order
(`scripts/lab/README.md`, "A whole session with one login"):

1. `bash scripts/lab/run-session.sh probe`, and read its three answers.
2. `bash scripts/lab/run-session.sh ospf-deadtimer ibgp bgp-vrf reset`.
3. `ssh-path` only if the probe says both management addresses answer on port 22, and
   `second-platform:<platform>` only if it says R1 Ethernet0/3 is free and that platform has an
   image, with `testbeds/lab-ssh.yaml` or `testbeds/lab-r3.yaml` copied into the clone first.
   `remove-r3` takes R3 out afterwards, one platform per session, for example
   `bash scripts/lab/run-session.sh second-platform:iosv remove-r3`.

What is most likely to differ from each prediction:

- **Probe**: several CML response shapes `cml_lab.py inspect` reads are documented nowhere the
  repo can check, so some answers may come back `unknown`; and the topology may not list R1
  Ethernet0/3 at all.
- **OSPF dead-timer**: whether an inbound ACL drops OSPF hellos (IP protocol 89, multicast) as it
  dropped BGP, and whether Genie reports R2's neighbor in `init` rather than leaving it out (the
  finding is the same; the README's evidence would not be). Also whether CML accepts `ip proto
  89` as a capture filter.
- **iBGP**: the timing. The post capture assumes both sessions and the BGP prefixes are gone
  within `wait-ibgp-down 60`, and that Genie labels the routes `ospf` and `bgp`.
- **BGP VRF**: whether IOL accepts a dot1Q subinterface on Ethernet0/1 and the CML link carries
  the tag, and whether Genie files the VRF neighbor under `vrf NCV` as its test data does.
- **SSH path**: whether the management addresses answer on port 22 at all; if not, the run ends
  with exit 4, which is a result. If they do, whether the routers' SSH server accepts the
  client's key exchange and host key algorithms.
- **Second platform**: which images and how much memory the sandbox has, and whether this login
  may add nodes; whether a custom day-0 configuration still boots NX-OS (it may drop the `boot
  nxos` line and stop at `loader>`); and whether R3's interface stays up when R1 shuts its end,
  or the change comparison has a tenth finding.
- **The session script**: it has driven only stand-in run scripts, and `read -rsp` has been
  tested with piped input, not at a real WSL terminal.

A run that came out as predicted is published as PR #14 published the hold-timer run: sanitize
its captures into `fixtures/lab-<date>/<run>` with `scripts/lab/sanitize_capture.py`, move its
draft intent and `expect-<run>.txt` beside them with a `SOURCE.md`, add tests that replay the
captures to `tests/test_lab_evidence.py`, rebuild `docs/artifacts` if a report is added there,
and update the README, `docs/LIVE.md`, this file, and "Claims match the evidence". If the run
saved a packet capture, copy `captures/<run>-<stamp>/link.pcap` and
`output/lab/<run>-<stamp>-pcap.txt` to `fixtures/lab-<date>/<run>-pcap/link.pcap` and
`summary.txt`, after checking that it holds only lab addresses, as PR #15 published the
hold-timer pcap; `sanitize_capture.py` does not copy it. A run that
did not come out as predicted is published the same way, with what happened: its `SOURCE.md`
and the README say which part of the prediction was wrong, and the expected file stays as the
prediction that was made.

Still open from the design review, which no change on the branch settled:

- OSPF neighbors are still keyed by router id only, so the same router id on two links is still
  refused. Keying them by interface or VRF, as BGP now is by VRF, has not started.
- Whether a CML link capture keeps 802.1Q tags, which the BGP VRF run's packet evidence needs.
- Whether CML allows two captures on one link at once. The capture exit trap stops a capture a
  run leaves behind after an ordinary early exit, but not after a killed shell or a VPN drop.
- `SENDLINE_AFTER_CRED` for R1 and R2 in `testbeds/cml-console.yaml.example`. It was verified
  offline to clear a leftover `Password:` prompt, a possible second cause of the 2026-11-20
  `CredentialsExhaustedError` failures, and not adopted there, because the published path works
  without it. It is used on R3's connection only, in `testbeds/cml-console-r3.yaml.example`
  (checked against Unicon's mock devices only).
- `lab_finish` warns when a password value appears in a run log; a very short password can
  give a false warning.

Ideas not started: the always-on DevNet sandboxes as a capture-only second image, and OSPF
neighbors keyed by interface or VRF (above).
