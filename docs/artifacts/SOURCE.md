# Artifact provenance

These files are the reports `ncv` wrote from the committed fixtures, plus SVG
summaries built from those same JSON reports. They are not hand-typed findings
and not a live capture taken while writing the README.

## Commands

From the repository root, with `ncv` 0.1.0 on the `PYTHONPATH` (or installed
editable):

```bash
python3 -m ncv --version
# 0.1.0

python3 -m ncv diff fixtures/pre fixtures/post \
  --intent intents/demo.yaml --report output/artifacts-demo
# exit 1, finding_count 8

python3 -m ncv diff fixtures/lab-2026-09-12/routes/pre \
  fixtures/lab-2026-09-12/routes/post \
  --intent fixtures/lab-2026-09-12/intent-routes.yaml \
  --report output/artifacts-routes
# exit 1, finding_count 2

python3 -m ncv diff fixtures/lab-2026-09-12/ospf/pre \
  fixtures/lab-2026-09-12/ospf/post \
  --intent fixtures/lab-2026-09-12/intent-ospf.yaml \
  --report output/artifacts-ospf
# exit 1, finding_count 4

python3 -m ncv diff fixtures/lab-2026-09-18/bgp/pre \
  fixtures/lab-2026-09-18/bgp/post \
  --intent fixtures/lab-2026-09-18/intent-bgp.yaml \
  --report output/artifacts-bgp
# exit 1, finding_count 3
```

`scripts/render_artifacts.py` runs those diffs and overwrites this directory.

## What each file is

| File | Source |
|---|---|
| `demo-report.json`, `demo-report.md` | synthetic `fixtures/pre` vs `fixtures/post` |
| `lab-2026-09-12-routes-post.*` | sanitized CML capture, route run |
| `lab-2026-09-12-ospf-post.*` | sanitized CML capture, OSPF run |
| `lab-2026-09-18-bgp-post.*` | sanitized CML capture, BGP run |
| `demo-findings.svg`, `lab-findings.svg` | rendered from the JSON files above |

The demo snapshots are hand-authored. The lab snapshots are sanitized copies of
captures taken on 2026-09-12 and 2026-09-18; see
[fixtures/lab-2026-09-12/SOURCE.md](../../fixtures/lab-2026-09-12/SOURCE.md) and
[fixtures/lab-2026-09-18/SOURCE.md](../../fixtures/lab-2026-09-18/SOURCE.md).
Password and certificate bodies were stripped before publish. The collector's
`raw/` directory is not in this repository.
