# network-change-validator

A Python portfolio tool for Cisco-style change validation: compare saved pre/post
network snapshots against a YAML intent checklist and report which rule failed.

- **Fixtures (default and CI):** synthetic, hand-authored snapshots; no SSH or pyATS needed.
- **Lab evidence:** sanitized captures from two live runs against a Cisco DevNet CML sandbox,
  replayed by the tests. See [fixtures/lab-2026-09-12](fixtures/lab-2026-09-12/SOURCE.md).
- **Live (optional):** collect from a lab you own using pyATS/Genie. Requires
  `--i-am-in-a-lab` on every capture.

This is not a home Wi-Fi tool or a production change tool. It has no configuration
push or fault-application command. The demo fixtures are synthetic
([provenance](fixtures/SOURCE.md)); the lab evidence comes from one simulated lab. Neither
demonstrates a production deployment.

## Run the offline demo

Use Python 3.10+ from the repository root, preferably in a virtual environment:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/demo
```

The last command intentionally exits **1** and writes `output/demo/report.json`
and `output/demo/report.md`. Expect **8 findings across all four violation classes**:

| Policy | Demo findings | What it checks |
|---|---:|---|
| `V_ADJ` | 3 | Required OSPF neighbor is FULL on the specified interface; required BGP peer is Established |
| `V_ROUTE` | 2 | Required prefix exists in the VRF, with the specified protocol if provided |
| `V_ERR` | 1 | Required interface counters exist and do not exceed their limits |
| `V_DRIFT` | 2 | Required devices and config evidence exist; required/forbidden lines match intent |

Each finding names the rule that failed, the device, the evidence path, and both
states, so the report is readable without the snapshots beside it:

```json
{
  "policy_id": "V_ADJ",
  "device": "r1",
  "path": "bgp.neighbors.203.0.113.1",
  "before": {
    "state": "Established",
    "vrf": "default",
    "remote_as": 65100
  },
  "after": {
    "state": "Idle",
    "vrf": "default",
    "remote_as": 65100
  },
  "why": "required BGP neighbor 203.0.113.1 must be Established in vrf default with remote AS 65100",
  "action": "inspect the peer session, its vrf, and its remote AS in the lab"
}
```

A clean comparison produces zero findings and exits **0**:

```bash
python3 -m ncv diff fixtures/pre fixtures/pre --intent intents/demo.yaml --report output/clean
```

Exit codes: **0** = no findings / successful snapshot; **1** = policy findings;
**2** = invalid arguments, unreadable/malformed input, collection failure, or output error.
A report is meaningful only when its command exits 0 or 1; a failed rerun does not
remove reports from a previous run.

Both reports record the JSON format version and the `ncv` version that wrote them,
so a saved report stays readable once the tool moves on. `python3 -m ncv --version`
prints the same version.

## Intent and evidence

Start with [intents/demo.yaml](intents/demo.yaml). Version 1 validates declared
devices and optional `adjacencies`, `routes`, `interfaces`, and `config` sections.
Unknown intent fields, unsupported adjacency protocols, invalid prefixes, and
invalid counter limits are rejected with field context.

Snapshots use up to five JSON files: `ospf.json`, `bgp.json`, `routing.json`,
`interface.json`, and `config.json`. Each maps device names to normalized evidence; the bundled
fixtures show their layout. Malformed data is an input error. Missing evidence
for a requested post-state check is a finding, never an assumed zero or successful
absence check. An entirely empty snapshot is an input error.

Policy details:

- Rules evaluate **post-state compliance**. Pre-state is context in the findings;
  this is not a raw diff or proof that the change caused every violation.
- OSPF checks require FULL (including `FULL/DR`-style states), not merely UP.
  Interface names match exactly; omit `interface` to check state alone.
- BGP checks require an Established session, matched case-insensitively. `vrf` and
  `remote_as` are optional discriminators, checked only when the intent declares them.
  An adjacency carries the fields of its own protocol: `interface` belongs to `ospf`,
  `vrf` and `remote_as` to `bgp`, and the wrong pairing is rejected by name.
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
adapter for OSPF, BGP, routing, and interface state plus `show running-config`.
Pass `--features` to narrow that set to what a given lab actually runs.
Unsupported shapes are rejected, as is the same neighbor seen twice: an OSPF peer
across interfaces or VRFs, or a BGP peer across VRFs or instances.
It is not a general multi-vendor framework.

A step-by-step runbook for a first capture against a Cisco DevNet sandbox, including
the reason it cannot run on native Windows, is in [docs/LIVE.md](docs/LIVE.md).
[intents/lab.yaml.example](intents/lab.yaml.example) is the intent template to copy, and
[testbeds/cml-console.yaml.example](testbeds/cml-console.yaml.example) is the testbed for
reaching CML nodes through the console server.

Tests use synthetic data and mocked connections. They verify the lab flag,
initialization safeguards, normalization, cleanup, and failure reporting **without
pyATS installed**. Two live runs have happened, both on
2026-09-12 against two IOS XE 17.15 routers (IOL) in a Cisco DevNet CML sandbox, reached
through its console server. Each caught a deliberate link shutdown: as two missing routes
on static routing, and, with OSPF on the link, as both lost adjacencies plus those routes.
`tests/test_lab_evidence.py` replays the sanitized captures. That is evidence about that
image in that lab, not about routers in general.

## Development

Lint and formatting are enforced by [Ruff](https://docs.astral.sh/ruff/), which the
`dev` extra installs and `pyproject.toml` configures (line length 110, target
py310, `E`/`F`/`I`/`UP`/`B`/`SIM`):

```bash
python3 -m ruff check .
python3 -m ruff format --check .
```

Tests mirror the module under test -- `tests/test_policy.py` covers `ncv/policy.py`,
and so on -- with the shared repository paths, demo intent/snapshots, and fake-lab
fixtures in `tests/conftest.py`. Snapshot section validation lives in `ncv/schema.py`
so the snapshot loader and the Genie normalizer share one definition.

CI runs both Ruff checks, the test suite, and the fixture diff gates on Ubuntu
(Python 3.10 and 3.12) and Windows (Python 3.11), always with pyATS and Genie
absent so the offline path is what gets exercised. Each job publishes the findings
table from its own fixture gate to the run summary, so what CI checked is readable
without opening a log.

For an interview walkthrough, see [docs/EXPLAIN.md](docs/EXPLAIN.md).
