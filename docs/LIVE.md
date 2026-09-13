# Optional live lab capture

CI uses saved synthetic fixtures and never connects to devices. This path is for
an isolated Cisco lab you own or are authorized to use. Every capture requires
`--i-am-in-a-lab`; that acknowledgement does not verify network isolation.
Never point it at production.

## Setup and capture

Use a trusted testbed and device plugins with an authorized CML, reserved sandbox, or
physical lab. The whole sequence, which the runbook below walks through one step at a
time:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[dev,lab]'
cp testbeds/lab.yaml.example testbeds/lab.yaml   # edit addresses, keep it out of git
cp intents/lab.yaml.example intents/lab.yaml     # edit to match the PRE capture
export NCV_LAB_USER=... NCV_LAB_PASS=...
python3 -m ncv snapshot --testbed testbeds/lab.yaml --output captures/pre --i-am-in-a-lab
# Add --features ospf,interface (for example) if a device does not run every feature.
# Make your planned change manually in the isolated lab.
python3 -m ncv snapshot --testbed testbeds/lab.yaml --output captures/post --i-am-in-a-lab
python3 -m ncv diff captures/pre captures/post --intent intents/lab.yaml --report output/live
```

A diff exits 1 for findings, 0 for a compliant post-state, or 2 for an execution or
input error. Capture outputs must be new or empty directories; use separate paths for
reruns. Both `testbeds/lab.yaml` and `intents/lab.yaml` are gitignored.

## Runbook: a first capture against a Cisco DevNet sandbox

This is the path the first live run followed on 2026-09-12 (evidence in
`fixtures/lab-2026-09-12`), written so it can be followed in order.

**Before anything else: pyATS does not install on native Windows.** Run the live path
from WSL, Linux, or macOS. The offline path in this repo runs fine on Windows, and CI
proves that on every commit; only the `lab` extra is the problem.

1. **Pick a sandbox with more than one router.** At
   [developer.cisco.com/site/sandbox](https://developer.cisco.com/site/sandbox), an
   always-on sandbox is a single device: enough for interface counters and config
   drift, but it has no neighbor, so no adjacency rule can pass or fail there. A
   reserved sandbox with a multi-node topology (the Modeling Labs ones) is what an
   adjacency check needs. Reserved sandboxes are time-boxed and reached over VPN with
   the credentials in the reservation mail.
2. **Install the lab extra in the environment that will do the capturing.**

   ```bash
   python3 -m venv .venv
   ./.venv/bin/python -m pip install -e '.[lab]'
   ```

3. **Write the testbed, keep the password out of it.**

   ```bash
   cp testbeds/lab.yaml.example testbeds/lab.yaml   # gitignored
   # Edit the device names, addresses, and ports to match the sandbox topology.
   export NCV_LAB_USER=... NCV_LAB_PASS=...
   ssh "$NCV_LAB_USER"@<device-address>             # prove reachability by hand first
   ```

   Device names must be letters, digits, `_`, or `-`. Console ports on a Modeling Labs
   topology are terminal-server ports, not always 22; take them from the topology page.

4. **Capture the pre-change state.**

   ```bash
   ./.venv/bin/python -m ncv snapshot --testbed testbeds/lab.yaml        --output captures/pre --i-am-in-a-lab
   ```

   Add `--features ospf,routing,interface` if the lab runs no BGP.

5. **Write the intent from that capture, not from memory.**

   ```bash
   cp intents/lab.yaml.example intents/lab.yaml    # gitignored
   cat captures/pre/ospf.json captures/pre/bgp.json captures/pre/routing.json
   ```

   Copy the neighbor addresses, interface names, and VRF names exactly as the device
   reported them.

6. **Prove the intent matches reality before changing anything.**

   ```bash
   ./.venv/bin/python -m ncv diff captures/pre captures/pre        --intent intents/lab.yaml --report output/lab-baseline
   ```

   This must exit **0**. If it exits 1, the intent is wrong, not the network. Fix the
   intent here, where nothing has changed yet, or every later finding is suspect.

7. **Make one change by hand in the lab.** One is the point: `shutdown` on the link
   interface, or clearing a neighbor. `ncv` has no configuration push and never will.

8. **Capture the post-change state and compare.**

   ```bash
   ./.venv/bin/python -m ncv snapshot --testbed testbeds/lab.yaml        --output captures/post --i-am-in-a-lab
   ./.venv/bin/python -m ncv diff captures/pre captures/post        --intent intents/lab.yaml --report output/lab
   ```

   Expect exit **1**, and expect the findings to name the thing you changed. A finding
   you cannot explain is the interesting result: read `output/lab/report.md`, then the
   evidence in `captures/post/`.

9. **Undo the change and re-capture** if you want the clean pass on record too.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `lab capture failed ... during learn bgp` | The image reports no usable BGP shape. Re-run with `--features` minus `bgp`. |
| `ambiguous OSPF neighbor` / `ambiguous BGP neighbor` | The same peer appears on two interfaces, VRFs, or instances. The adapter refuses to guess; narrow the topology or extend the adapter with evidence. |
| `unsupported lab device name` | Testbed device names allow letters, digits, `_`, and `-` only. |
| Connect timeouts | VPN down, wrong port, or a console that needs a terminal-server port. Prove `ssh` works by hand first. |
| `snapshot output must be a new or empty directory` | Captures are never overwritten. Use `captures/pre-2`, and keep the first one. |

### What the 2026-09-12 sandbox run needed

The first real run followed this runbook with a few differences worth knowing:

- The reservation email showed one VPN password web-encoded: `%3C` stood for `<`.
- From WSL, `openconnect --useragent="AnyConnect Linux_64 4.7.00136"` connected when run as
  root (`wsl -u root`). Leave that terminal open for the whole session.
- The sandbox's preloaded `default-lab` (CML 2.7.2) has IOL XE routers whose management
  addresses did not answer over the VPN, while the CML controller did. The routers were
  reached through the CML console server with
  [testbeds/cml-console.yaml.example](../testbeds/cml-console.yaml.example).
- `default-lab` runs static routes and neither OSPF nor BGP, so its captures used
  `--features routing,interface`.
- The first real interface learn exposed an adapter gap, fixed in PR #5.

### After a real run

Raw captures hold credentials and real addressing. `captures/` and `output/` are
gitignored; keep them that way until you have read what is in them.

If you decide to publish lab evidence, sanitize it, put it in its own directory such
as `fixtures/lab-2026-10-01/`, and write a `SOURCE.md` beside it recording the
environment, the collection date, and exactly what was sanitized. Never relabel the
synthetic fixtures as a capture.

The 2026-09-12 run is recorded that way. When a new run adds evidence, update the places
that describe it: `README.md` (the evidence bullet and the paragraph on what the tests
establish), this file, and `HANDOFF.md`. Say what actually happened, with the image and
platform named. A capture against one image is evidence about that image, not about
routers in general.

## Collection behavior

The collector learns `ospf`, `bgp`, `routing`, and `interface`, then executes
`show running-config`. It has no configuration push or fault-application path.
`--features` narrows the learned set, for example `--features ospf,interface` on a
lab with no BGP; `show running-config` is always collected. A device that simply has
no BGP configured returns nothing to normalize and records no neighbors, which is
evidence of absence rather than a failed capture.
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
Live-capture tests use mocks; `tests/test_lab_evidence.py` replays sanitized
captures from one real CML session.

## Evidence handling

Running configs and raw captures can contain credentials and sensitive addressing.
Keep testbeds and captures out of git until reviewed and sanitized. Preserve the
bundled synthetic fixtures and their provenance. If you later add real lab evidence,
use a separate, clearly labeled directory and record the environment, collection
date, and sanitization performed. Do not relabel synthetic fixtures as CML captures.
