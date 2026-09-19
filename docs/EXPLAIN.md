# What to say about this project

One sentence: I built a Python checker that compares network state before and after a change against a written checklist, and reports which rule broke.

The README opens with the flow, the four policies, and the reports `ncv` actually wrote.
Point at those pictures rather than narrating them.

## What to explain

1. Intent is the checklist. Snapshots are evidence. A raw diff is not the same thing.
2. Four rules: adjacency up (OSPF neighbor FULL on its intended interface, BGP peer Established in its VRF), route present, error counters under a limit, config lines present or absent.
3. CI runs on saved fixtures so it does not need a live router.
4. Live capture is optional, requires `--testbed`, `--output`, and `--i-am-in-a-lab`, and is never aimed at production. Automated tests for that path use mocks. The demo snapshots in `fixtures/pre` and `fixtures/post` are synthetic. The snapshots under `fixtures/lab-2026-09-12` and `fixtures/lab-2026-09-18` are sanitized captures from three DevNet CML runs.

## What not to say

- That it manages home Wi-Fi.
- That it ran on a company production network.
- That it is Cisco pyATS itself. It uses the same idea; the live path calls Genie if you install pyATS.
- That the demo fixtures came off a router. They did not.

## Demo commands

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/demo
```

The demo exits 1 with eight findings across four classes. Open `output/demo/report.md`
or the checked-in copy at [docs/artifacts/demo-report.md](artifacts/demo-report.md).

Be precise: this checks post-state against intent and shows pre-state evidence. It does not prove causation, end-to-end reachability, or compatibility with a router image you have not tested.
