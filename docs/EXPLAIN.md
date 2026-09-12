# What to say about this project

One sentence: I built a Python checker that compares network state before and after a change against a written checklist, and reports which rule broke.

## What to explain

1. Intent is the checklist. Snapshots are evidence. A raw diff is not the same thing.
2. Four rules: adjacency up (OSPF neighbor FULL on its intended interface, BGP peer Established in its VRF), route present, error counters under a limit, config lines present or absent.
3. CI runs on saved fixtures so it does not need a live router.
4. Live capture is optional, requires `--testbed`, `--output`, and `--i-am-in-a-lab`, and is never aimed at production. Its automated tests use mocks; bundled snapshots are synthetic.

## What not to say

- That it manages home Wi-Fi.
- That it ran on a company production network.
- That it is Cisco pyATS itself. It uses the same idea; the live path calls Genie if you install pyATS.

## Demo commands

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/demo
```

The demo intentionally exits 1 with eight findings across four classes. Open `output/demo/report.md`.

Be precise: this checks post-state against intent and shows pre-state evidence. It does not prove causation, end-to-end reachability, or compatibility with a router image you have not tested.
