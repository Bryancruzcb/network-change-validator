# network-change-validator

A Python portfolio tool for Cisco-style change validation: compare saved pre/post
network snapshots against a YAML intent checklist and report which rule failed.

- **Fixtures (default and CI):** synthetic, hand-authored snapshots; no SSH or pyATS needed.
- **Live (optional):** collect from a lab you own using pyATS/Genie. Requires
  `--i-am-in-a-lab` on every capture.

This is not a home Wi-Fi tool or a production change tool. It has no configuration
push or fault-application command. The bundled evidence is not a CML capture and
does not demonstrate a production deployment. See [fixture provenance](fixtures/SOURCE.md).

## Run the offline demo

Use Python 3.10+ from the repository root, preferably in a virtual environment:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/demo
```

The last command intentionally exits **1** and writes `output/demo/report.json`
and `output/demo/report.md`. Expect **7 findings across all four violation classes**:

| Policy | Demo findings | What it checks |
|---|---:|---|
| `V_ADJ` | 2 | Required OSPF neighbor is FULL on the specified interface |
| `V_ROUTE` | 2 | Required prefix exists in the VRF, with the specified protocol if provided |
| `V_ERR` | 1 | Required interface counters exist and do not exceed their limits |
| `V_DRIFT` | 2 | Required devices and config evidence exist; required/forbidden lines match intent |

A clean comparison produces zero findings and exits **0**:

```bash
python3 -m ncv diff fixtures/pre fixtures/pre --intent intents/demo.yaml --report output/clean
```

Exit codes: **0** = no findings / successful snapshot; **1** = policy findings;
**2** = invalid arguments, unreadable/malformed input, collection failure, or output error.
A report is meaningful only when its command exits 0 or 1; a failed rerun does not
remove reports from a previous run.

## Intent and evidence

Start with [intents/demo.yaml](intents/demo.yaml). Version 1 validates declared
devices and optional `adjacencies`, `routes`, `interfaces`, and `config` sections.
Unknown intent fields, unsupported adjacency protocols, invalid prefixes, and
invalid counter limits are rejected with field context.

Snapshots use up to four JSON files: `ospf.json`, `routing.json`, `interface.json`,
and `config.json`. Each maps device names to normalized evidence; the bundled
fixtures show their layout. Malformed data is an input error. Missing evidence
for a requested post-state check is a finding, never an assumed zero or successful
absence check. An entirely empty snapshot is an input error.

Policy details:

- Rules evaluate **post-state compliance**. Pre-state is context in the findings;
  this is not a raw diff or proof that the change caused every violation.
- OSPF checks require FULL (including `FULL/DR`-style states), not merely UP.
  Interface names match exactly; omit `interface` to check state alone.
- Route checks cover presence and optional protocol, not reachability or next-hop correctness.
- Counter limits are inclusive maxima for **absolute post counters**, not pre/post
  deltas. Missing counters fail the check. Interface operational status is not a rule.
- Config rules compare complete lines after trimming leading/trailing whitespace.
  They do not use substring, regex, or configuration-hierarchy matching.
- `exclude_volatile` is accepted for compatibility but performs no filtering.
  Only explicitly implemented policy fields are inspected; unrelated timers and
  octet counters do not affect results.

Copy a validated snapshot without connecting to devices:

```bash
python3 -m ncv snapshot --from-dir fixtures/pre --output captures/example
```

Snapshot output must be a new or empty directory. Copying validates the input and
preserves `SOURCE.json` when supplied. Snapshot publication occurs only after all
collection and writes succeed, avoiding a partial snapshot after a failed capture.

## Optional live path and limitations

See [docs/LIVE.md](docs/LIVE.md). Live collection uses a deliberately small Genie
adapter for OSPF, routing, and interface state plus `show running-config`.
Unsupported shapes and ambiguous OSPF neighbors across interfaces/VRFs are rejected.
It is not a general multi-vendor framework.

Tests use synthetic data and mocked connections. They verify the lab flag,
initialization safeguards, normalization, cleanup, and failure reporting **without
pyATS installed**. They do not establish compatibility with a particular router
image or claim a successful live lab run.

For an interview walkthrough, see [docs/EXPLAIN.md](docs/EXPLAIN.md).
