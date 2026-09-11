# What to say about this project

One sentence: I built a Python checker that compares network state before and after a change against a written checklist, and reports which rule broke.

## What to explain

1. Intent is the checklist. Snapshots are evidence. A raw diff is not the same thing.
2. Four rules: neighbor up, route present, error counters under a limit, config lines present or absent.
3. CI runs on saved fixtures so it does not need a live router.
4. Live capture exists (`ncv snapshot --i-am-in-a-lab`) but is optional and never aimed at production.

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

Open `output/demo/report.md`.
