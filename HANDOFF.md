# Handoff

Working notes for whoever picks this up next. The work is on `main`; fetch it.

## Current state

- Everything below is on `main`. PRs [#1](https://github.com/Bryancruzcb/network-change-validator/pull/1)
  through [#11](https://github.com/Bryancruzcb/network-change-validator/pull/11) went in as
  fast-forwards, so every hash quoted in these notes is the hash the commit carries on
  `main`. Six commits on 2026-09-18 went straight to `main` without a PR (see "Direct
  commits"). No open PRs, no open issues, and every merged branch is deleted.
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

## Test count

**105 tests.** The 50 that existed at `11ee5bd` all survive the reorganization, plus
the 2 policy regressions from PR #1, the 21 that came with BGP support and feature
selection, 3 covering report provenance and the version flag, 1 that loads both
bundled intents so the lab template cannot rot unnoticed, 2 covering the interface shape
Genie actually learns, 6 that replay the lab evidence, 2 that pin the lab sanitizer, 3
that pin the BGP run's parsers, intent, and predicted findings, 3 that replay the BGP
evidence, and 12 more from PR #11 (13 new, one replaced): the artifact rebuild, a learn
with no `info` in the adapter and in a capture, a BGP shape with no neighbors in place of
the old empty-mapping test, an empty mapping refused for each of the five feature names,
three empty `--features` values, and a repeated feature.

## Verify

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest                      # 105 passed
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
  asserts `device.configure` is never called.
- **A learn that returns nothing fails the capture.** Never turn a missing Genie `info`
  into an empty section: it would hide a parser failure as a lost neighbor.
- **`docs/artifacts` is what the code writes.** Rebuild it with
  `scripts/render_artifacts.py` whenever a report changes; `tests/test_artifacts.py`
  enforces it.
- **Claims match the evidence.** Three live runs have happened against IOS XE 17.15 IOL in a
  DevNet CML sandbox: two on 2026-09-12 (`fixtures/lab-2026-09-12`), one on static routes and
  one with OSPF, and one on 2026-09-18 (`fixtures/lab-2026-09-18`) with eBGP. Nothing in the repo may
  claim more than that evidence shows, and synthetic fixtures are never relabeled as
  captures.

## Open

Nothing is open. Ideas that would widen the evidence, none of them started: a second image
or platform (IOS XE on Cat8kv, NX-OS), the management SSH path instead of a console server,
and BGP beyond one eBGP session in the default VRF (iBGP, a VRF, a hold-timer loss).
