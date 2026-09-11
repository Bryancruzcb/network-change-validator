# Optional live lab capture

CI uses saved synthetic fixtures and never connects to devices. This path is for
an isolated Cisco lab you own or are authorized to use. Every capture requires
`--i-am-in-a-lab`; that acknowledgement does not verify network isolation.
Never point it at production.

## Setup and capture

Use a trusted testbed and device plugins with an authorized CML, reserved sandbox,
or physical lab. Install the optional dependency in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[dev,lab]'
cp testbeds/lab.yaml.example testbeds/lab.yaml
# Edit lab addresses; export NCV_LAB_USER and NCV_LAB_PASS.
# Adapt a copy of intents/demo.yaml to your actual devices, neighbors, and routes.
python3 -m ncv snapshot --testbed testbeds/lab.yaml --output captures/pre --i-am-in-a-lab
# Make your planned change manually in the isolated lab.
python3 -m ncv snapshot --testbed testbeds/lab.yaml --output captures/post --i-am-in-a-lab
python3 -m ncv diff captures/pre captures/post --intent intents/lab.yaml --report output/live
```

Create `intents/lab.yaml` from the demo before running the last command. A diff
exits 1 for findings, 0 for a compliant post-state, or 2 for an execution/input error.
Capture outputs must be new or empty directories; use separate paths for reruns.

## Collection behavior

The collector learns `ospf`, `routing`, and `interface`, then executes
`show running-config`. It has no configuration push or fault-application path.
Unicon's initialization command lists are set to empty, including overrides in
connection arguments, to avoid default configuration initialization. Device
plugins and testbeds are trusted executable dependencies: this is not a security
boundary against arbitrary custom plugins.

Connection, learning, unsupported normalization, and config-read errors abort the
capture. Connections are disconnected on success or failure, and a failed capture
does not publish a partial snapshot. Missing individual counters remain unknown
and produce `V_ERR` when requested by intent. Raw collected data is saved alongside
normalized JSON and `SOURCE.json` only after successful collection.

The adapter handles a limited set of Genie shapes. It does not resolve the same
OSPF neighbor occurring on multiple interfaces or in multiple VRFs; those captures
are rejected rather than silently selecting one. A real router image may require
adapter adjustments backed by sanitized evidence and offline regression tests.
Current automated tests use mocks, not a real CML session.

## Evidence handling

Running configs and raw captures can contain credentials and sensitive addressing.
Keep testbeds and captures out of git until reviewed and sanitized. Preserve the
bundled synthetic fixtures and their provenance. If you later add real lab evidence,
use a separate, clearly labeled directory and record the environment, collection
date, and sanitization performed. Do not relabel synthetic fixtures as CML captures.
