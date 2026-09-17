# Lab scripts

The operator side of the 2026-09-12 lab runs, kept here so the evidence in
`fixtures/lab-2026-09-12` can be reproduced and its sanitization rerun. They are written
for the Cisco DevNet "Cisco Modeling Labs" sandbox and its preloaded `default-lab` (R1 and
R2 joined on Ethernet0/1), for an isolated lab you are authorized to use, and they are
deliberately outside `ncv`: `ncv` never pushes configuration, and these scripts do, to make
the one planned change the captures are meant to catch.

| Script | What it does |
|---|---|
| `run-lab.sh` | The static-route run in one command: pre capture, no-change check, `shutdown` on R1 Ethernet0/1, post capture and compare, `no shutdown`, restored capture and compare. |
| `run-ospf.sh` | The OSPF run: sets up OSPF area 0 on the R1-R2 link, waits for FULL, then the same sequence, waiting for both neighbor entries to clear before the post capture. |
| `run-bgp.sh` | The BGP run, prepared and not yet run (see below): sets up eBGP between R1 and R2, waits for Established, then the same sequence around `neighbor 1.1.1.2 shutdown` on R1. |
| `capture.sh` | One capture (`pre`, `post`, or `restored`) for a run driven by hand. |
| `change.sh` | The planned change by hand: `apply` shuts R1 Ethernet0/1 and `undo` brings it back; `bgp-apply` shuts the R1 peer and `bgp-undo` brings it back. |
| `labctl.py` | The lab actions the scripts above call: `setup-ospf`, `shut`, `noshut`, `wait-full`, `wait-gone`, `setup-bgp`, `bgp-shut`, `bgp-noshut`, `wait-bgp-up`, `wait-bgp-down`. |
| `intent-bgp.yaml` | The draft intent for the BGP run; it moves next to its captures once the run is recorded. |
| `sanitize_capture.py` | Copies a run's `pre/`, `post/`, `restored/` for publishing with passwords and certificate bodies replaced and `raw/` left out. |

The two recorded runs compare against the intents kept with their evidence
(`fixtures/lab-2026-09-12/intent-routes.yaml` and `intent-ospf.yaml`), so a rerun on the
same sandbox is checked against the same rules.

## BGP run, prepared and not yet run

`run-bgp.sh` was written on 2026-09-17 from the recorded captures and has not been run
against a lab, so there is no BGP evidence in this repository. It sets up eBGP between R1
(AS 65001, router-id 1.1.1.1) and R2 (AS 65002, router-id 2.2.2.2) over the 1.1.1.0/24 link,
each router advertising its own LAN, waits for Established, takes the pre capture with
`--features bgp,routing,interface`, and checks it against `intent-bgp.yaml` before anything
changes. The static routes the lab ships with outrank the learned prefixes, so the routing
table does not change with the session, and the route and interface rules are the ones the
route run used. The planned change is `neighbor 1.1.1.2 shutdown` on R1: an administrative
peer shutdown rather than a link shutdown, so both routers drop the session at once, the
routes and interfaces stay compliant, and the findings isolate the BGP path.
`tests/test_lab_scripts.py` pins this prediction on synthetic snapshots shaped like the
recorded captures:

| Comparison | Exit | Findings |
|---|---|---|
| pre vs pre | 0 | none |
| pre vs post (`neighbor 1.1.1.2 shutdown` on R1) | 1 | `V_ADJ` R1 neighbor 1.1.1.2, `V_ADJ` R2 neighbor 1.1.1.1, `V_DRIFT` R1 (the forbidden line is present) |
| pre vs restored | 0 | none |

A real capture can disagree with that prediction, and finding out is the point of running
it: the first real interface learn disagreed with the adapter too (PR #5). If the no-change
check exits 1, the intent or the adapter is wrong, and the script stops before the change.
When the run happens, record it the way the 2026-09-12 runs were: sanitize the captures,
put them in `fixtures/lab-<date>/bgp/` with `intent-bgp.yaml` beside them, write the
`SOURCE.md`, replay the comparisons in `tests/test_lab_evidence.py`, and update the claims in
README, `docs/LIVE.md`, and `HANDOFF.md`. Until then, nothing in the repository may say BGP
was exercised live.

## Running a session

Run from WSL or Linux: pyATS does not install on native Windows, and the VPN check uses
`ip`. The scripts find the repository root from their own location, so any working
directory works.

1. Reserve the sandbox, connect its VPN, and confirm the console server answers.
   `docs/LIVE.md` has the steps and the traps.
2. `cp testbeds/cml-console.yaml.example testbeds/lab.yaml` (gitignored) and adjust it if
   the lab differs.
3. `.venv/bin/python -m pip install -e '.[dev,lab]'` once. The scripts use
   `.venv/bin/python`; set `NCV_PYTHON` to use another interpreter.
4. `bash scripts/lab/run-lab.sh` or `bash scripts/lab/run-ospf.sh`. Each asks for the CML
   username and password and the routers' enable password, keeps them in that terminal's
   environment (`NCV_CML_USER`, `NCV_CML_PASS`, `NCV_LAB_PASS`), and stops before touching
   the lab if the no-change check is not clean.

Captures land in `captures/<run>/`, reports and the log in `output/lab/`. Both directories
are gitignored, and the captures hold the lab's running configs.

## Publishing a run

    .venv/bin/python scripts/lab/sanitize_capture.py captures/run-<stamp> fixtures/lab-<date>/<run>

The sanitizer knows the forms the sandbox routers carried: `enable password|secret`,
`username ... password|secret`, the indented `password` of a console or vty line, and the
body of a `certificate self-signed|ca` block. It changes nothing else, so read the copy
before committing it, and write a `SOURCE.md` beside it recording the environment, the
date, and exactly what was removed, as `fixtures/lab-2026-09-12/SOURCE.md` does.
`tests/test_lab_scripts.py` pins the rules and checks that the published configs are the
script's own fixed point.
