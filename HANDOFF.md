# Handoff

Working notes for whoever picks this up next. The work is on `main`; fetch it rather
than applying a patch. Read "Patch bases" before trusting any commit hash quoted in an
older note.

## Current state

- Everything below is merged into `main`. PRs [#1](https://github.com/Bryancruzcb/network-change-validator/pull/1) through
  [#7](https://github.com/Bryancruzcb/network-change-validator/pull/7) went in on 2026-09-12, each as a fast-forward, so every hash quoted
  in these notes is the hash the commit carries on `main`. No open PRs, no open issues,
  and every merged branch is deleted locally and on `origin`.
- The oldest work here is built on `11ee5bd` ("Harden offline validation and fail
  incomplete lab captures"), itself based on `716feac`.
- CI is green on all three jobs -- Ubuntu 3.10, Ubuntu 3.12, and Windows 3.11. Windows
  had never been exercised before this work, so that job is the first real signal for
  the platform. Each job now publishes its findings table to the run summary.

## Patch bases -- read this first

This work is on `main` now, so fetch it. What follows is history, kept only
because it explains why the same change carries different hashes in different notes.

Before the push, the branch moved between machines as `git format-patch` files
applied with `git am`. Pushes attempted from the Claude cloud sessions failed with
**403** -- an egress-proxy restriction on that environment, not GitHub refusing the
write. The same push succeeded from the Windows machine on 2026-09-12.

`git am` re-commits, so **the same change has a different hash on each machine.**
The Windows clone's first applied patch became `11ee5bd`; the cloud workspace knew
that same content as `f95af0e`. Do not match patches to commits by hash.

Exactly one patch had been applied on Windows before this round of work. A second
cloud-side commit (`dc775ce`) and a set of uncommitted changes never left the cloud
container, and that container was reclaimed before they were committed or exported.
**They are gone.** The work they described was redone on top of `11ee5bd` and is
now in the work recorded below; there is nothing left to recover, and no patch
numbered after the first was ever applied.

If a patch is ever needed again, base it on the current tip of `main`, not on
`716feac` or any hash from a previous session's workspace.

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
VRFs. A device with no BGP normalizes to no neighbors, because absence of the feature
is not a failed capture.

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

## Test count

**90 tests.** The 50 that existed at `11ee5bd` all survive the reorganization, plus
the 2 policy regressions from PR #1, the 21 that came with BGP support and feature
selection, 3 covering report provenance and the version flag, 1 that loads both
bundled intents so the lab template cannot rot unnoticed, 2 covering the interface shape
Genie actually learns, 6 that replay the lab evidence, 2 that pin the lab sanitizer, and 3
that pin the BGP run's parsers, draft intent, and predicted findings.

An earlier note claimed a 59-test baseline and a 61-test target. That was wrong for
this tree: `11ee5bd`'s own commit message records 50 passing, and the extra 9 tests
belonged to the lost uncommitted work. Do not treat 59/61 as a regression target.

## Verify

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest                      # 90 passed
git diff --check                       # clean

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
- **Claims match the evidence.** Two live runs have happened, both on 2026-09-12
  against IOS XE 17.15 IOL in a DevNet CML sandbox (`fixtures/lab-2026-09-12`): one on static
  routes and one with OSPF. Nothing in the repo may
  claim more than that evidence shows, and synthetic fixtures are never relabeled as
  captures.

## Open

The BGP run is prepared and not run. `scripts/lab/run-bgp.sh` needs a reserved DevNet CML
sandbox and the VPN; when it has run, record it the way the 2026-09-12 runs were
(`scripts/lab/README.md`, "BGP run"), and only then may any document say BGP was exercised
live. Other ideas that would widen the evidence, none of them started: a second image or
platform (IOS XE on Cat8kv, NX-OS), and the management SSH path instead of a console server.
