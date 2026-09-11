# Handoff

Working notes for whoever picks this up next. Read the "Patch bases" section
before generating or applying any patch.

## Current state

- Branch: `fix/offline-validation-and-lab-capture`
- Built on `11ee5bd` ("Harden offline validation and fail incomplete lab captures"),
  which is itself based on `origin/main` at `716feac`.
- Nothing on this branch has ever been pushed. `origin` has only `main` at `716feac`.

## Patch bases -- read this first

GitHub writes from the cloud workspace return **403**, so this branch has only ever
moved between machines as `git format-patch` files applied with `git am`.

`git am` re-commits, so **the same change has a different hash on each machine.**
The Windows clone's first applied patch became `11ee5bd`; the cloud workspace knew
that same content as `f95af0e`. Do not match patches to commits by hash.

Exactly one patch had been applied on Windows before this round of work. A second
cloud-side commit (`dc775ce`) and a set of uncommitted changes never left the cloud
container, and that container was reclaimed before they were committed or exported.
**They are gone.** The work they described was redone on top of `11ee5bd` and is
now in the two commits below; there is nothing left to recover, and no patch numbered
after the first was ever applied.

When exporting the next patch, base it on the current branch tip, not on `716feac`
or any hash from a previous session's workspace.

## Done in this round

On top of `11ee5bd`:

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

## Test count

**52 tests.** The 50 that existed at `11ee5bd` all survive the reorganization, plus
the 2 new policy regressions.

An earlier note claimed a 59-test baseline and a 61-test target. That was wrong for
this tree: `11ee5bd`'s own commit message records 50 passing, and the extra 9 tests
belonged to the lost uncommitted work. Do not treat 59/61 as a regression target.

## Verify

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest                      # 52 passed
git diff --check                       # clean

python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/ci
# exits 1, 7 findings: V_ADJ 2, V_ROUTE 2, V_ERR 1, V_DRIFT 2

python3 -m ncv diff fixtures/pre fixtures/pre --intent intents/demo.yaml --report output/clean
# exits 0, 0 findings
```

## Invariants -- do not regress

- **Offline-first.** `genie`/`pyats` are imported inside `snapshot_live` only, after the
  lab flag check. The suite must pass with neither installed, and CI asserts their absence.
- **Live capture is opt-in.** `--i-am-in-a-lab` is mandatory; `snapshot_live` raises
  `PermissionError` without it, before importing Genie and before creating output.
- **No configuration push.** There is no `configure`/push path, and the fake-lab test
  asserts `device.configure` is never called.
- **No real lab run has occurred.** Nothing in the repo may claim otherwise.

## Open

- Push the branch to `origin` and open a PR. Still blocked on the 403; until it clears,
  this branch exists only as local commits plus exported patches, on one machine.
