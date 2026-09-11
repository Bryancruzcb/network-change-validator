# network-change-validator

Automatically check that a lab network change did not break rules you wrote first.

Two paths:

- **Fixtures (default, CI)** — saved before/after snapshots. No SSH.
- **Live (opt-in)** — `pyats`/`Genie` learn from a lab you own. Requires `--i-am-in-a-lab`.

This is not a home Wi-Fi tool and not a production change window tool.

## Fixture path (always works)

```bash
python3 -m pip install -e ".[dev]"
python3 -m ncv diff fixtures/pre fixtures/post --intent intents/demo.yaml --report output/demo
python3 -m pytest
```

The demo post snapshot is planted to fail four rules: neighbor down, route missing, interface errors too high, config line drift.

## Live path

See [docs/LIVE.md](docs/LIVE.md).

## What it showcases

You can write intent, collect device state, and report which rule failed on which device.
