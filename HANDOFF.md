# Handoff

Working notes for whoever picks this up next. The work is on `main`; fetch it rather
than applying a patch. Read "Patch bases" before trusting any commit hash quoted in an
older note.

## Current state

- `fix/offline-validation-and-lab-capture` merged into `main` on 2026-09-12 as
  [PR #1](https://github.com/Bryancruzcb/network-change-validator/pull/1). The merge was
  a fast-forward from `716feac`, so every hash quoted in these notes is the hash the
  commit carries on `main`.
- Built on `11ee5bd` ("Harden offline validation and fail incomplete lab captures"),
  which is itself based on `716feac`.
- CI is green on all three jobs -- Ubuntu 3.10, Ubuntu 3.12, and Windows 3.11. Windows
  had never been exercised before this branch, so that job is the first real signal for
  the platform.
- The branch was deleted locally and on `origin` after the merge. Nothing is lost: the
  fast-forward kept the commits themselves.

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
3. **CI action majors** -- `actions/checkout` and `actions/setup-python` moved off the
   versions that target the deprecated Node 20, so the jobs no longer lean on the
   runner's Node 24 fallback. The matrix, `fail-fast: false`, and the bash-pinned gate
   are untouched.

## Test count

**73 tests.** The 50 that existed at `11ee5bd` all survive the reorganization, plus
the 2 policy regressions added in that round and the 21 that came with BGP support.

An earlier note claimed a 59-test baseline and a 61-test target. That was wrong for
this tree: `11ee5bd`'s own commit message records 50 passing, and the extra 9 tests
belonged to the lost uncommitted work. Do not treat 59/61 as a regression target.

## Verify

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest                      # 73 passed
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
- **No real lab run has occurred.** Nothing in the repo may claim otherwise.

## Open

- The live path is still covered only by mocked connections, because no real lab run
  has happened. That is the one claim in this repo that only a lab you own can change.
