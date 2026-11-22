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

   Leave out every protocol the lab does not run: `--features ospf,routing,interface`
   without BGP, `--features routing,interface` with neither OSPF nor BGP. A learned
   feature the device does not run fails the capture and names that feature.

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
| `lab capture failed ... during learn <feature>: learn returned no info` | The device does not run that feature, or its show commands did not parse; Genie reports both the same way. If the lab does not run it, leave it out of `--features`. |
| `unsupported <feature> data` | Genie learned a shape the adapter does not know. Keep the raw capture and extend the adapter with a test, the way PR #5 did for interfaces. |
| `--features needs at least one of ...` | The value was empty. Name at least one feature, or drop the flag to learn all four. |
| `ambiguous OSPF neighbor` / `ambiguous BGP neighbor` | The same OSPF neighbor appears on two interfaces or VRFs, or the same BGP peer address appears twice in one VRF (two instances). The same BGP address in two different VRFs is kept apart, not refused; an intent adjacency that names no `vrf` checks the one in the default VRF. The adapter refuses to guess; narrow the topology or extend the adapter with evidence. |
| `unsupported lab device name` | Testbed device names allow letters, digits, `_`, and `-` only. |
| Connect timeouts | VPN down, wrong port, or a console that needs a terminal-server port. Prove `ssh` works by hand first. |
| `snapshot output must be a new or empty directory` | Captures are never overwritten. Use `captures/pre-2`, and keep the first one. |

### What the sandbox runs needed

The first real run followed this runbook with a few differences worth knowing:

- The reservation email showed one VPN password web-encoded: `%3C` stood for `<`.
- From WSL, `openconnect --useragent="AnyConnect Linux_64 4.7.00136"` connected when run as
  root (`wsl -u root`). Leave that terminal open for the whole session.
- The sandbox's preloaded `default-lab` (CML 2.7.2) has IOL XE routers whose management
  addresses did not answer over the VPN, while the CML controller did. The routers were
  reached through the CML console server with
  [testbeds/cml-console.yaml.example](../testbeds/cml-console.yaml.example). The 2026-11-21
  probe, below, recorded what the management addresses do.
- `default-lab` runs static routes and neither OSPF nor BGP, so the first run captured
  `--features routing,interface`. For the adjacency check, a second run set up OSPF area 0
  on the R1-R2 link with pinned router IDs and captured `--features ospf,routing,interface`.
  R2 kept its neighbor until its dead timer expired, so that run waited for both neighbor
  entries to clear before the post capture.
- The first real interface learn exposed an adapter gap, fixed in PR #5.
- A third run, on 2026-09-18 in a fresh reservation of the same sandbox, set up eBGP between R1
  and R2 and captured `--features bgp,routing,interface`. The real BGP learn normalized with no
  adapter change, and an administrative `neighbor 1.1.1.2 shutdown` on R1 showed up as `V_ADJ`
  on both routers plus `V_DRIFT` on R1, the findings predicted the day before
  (`fixtures/lab-2026-09-18/SOURCE.md`).
- A fourth run, on 2026-11-20, lost the same session to a hold-timer expiry instead
  (`fixtures/lab-2026-11-20/SOURCE.md`). The sandbox had changed how it hands out logins,
  and three things cost time before the run worked:
  - The reservation's **Access Details** list two logins. The VPN user is generated per
    reservation; the CML login, which the console-server path uses, is still `developer`,
    with its own password. Giving the VPN login at the CML prompt fails with
    `CredentialsExhaustedError ... ['default']` before anything changes.
  - Pasting a password into a hidden prompt in an embedded terminal did not deliver it;
    typing it, or pasting in Windows Terminal, did. Prove the CML login by hand first:
    `ssh developer@10.10.20.161 "open /default-lab/R1/0"` should reach `R1>`.
  - Closing the terminal that runs openconnect ends the VPN; the run scripts then stop at
    their tunnel check.
  - With the VPN inside WSL, a Windows browser cannot reach the CML web UI, so its capture
    button is out of reach. `scripts/lab/cml_capture.py` captures the link through the CML
    API instead, and `run-bgp-holdtimer.sh` calls it.
- Runs five to eight, on 2026-11-21, used the same reservation as 2026-11-20
  (`fixtures/lab-2026-11-21/SOURCE.md`). What that day showed:
  - `scripts/lab/run-session.sh` asks for the lab logins once, checks the CML login, and then
    runs its named steps unattended, each with its own log, ending with a table of exit
    statuses. Three sessions ran (Pacific time, from the collector's clock):
    - `run-session.sh` with its default steps, `probe ospf-deadtimer ibgp bgp-vrf reset`:
      12:58:57 to 13:27:03, about 28 minutes. The probe took about a minute, and the three runs
      about 7, 10, and 9 minutes.
    - `run-session.sh second-platform:iosv reset`: 13:34:25 to 13:49:46, about 15 minutes, of
      which adding and booting R3 took about 3.
    - `run-session.sh remove-r3 second-platform:nxosv9000 reset`: 21:18:27 to 21:40:02, about
      22 minutes.
  - The VPN tunnel had been up since about 12:51. Its last lab traffic was the second session,
    which ended at 13:49:46. openconnect then printed that the server had disconnected it with
    the reason `Idle Timeout`, 1 h 38 min after it connected, so about 40 minutes after that
    session ended. The session logs do not record this; it was read from openconnect's own
    output. Check the tunnel before the next session; `run-session.sh` checks it before it asks
    for any login.
  - The probe (`scripts/lab/probe.sh`, read-only) answered the management-address question.
    10.10.20.171 (R1) and 10.10.20.172 (R2) gave no answer on ports 22 and 23 within 3 s, and
    no ping reply, over the VPN. On the routers, `show ip ssh` reports SSH disabled, with no
    RSA or EC host keys. So the SSH path run (`run-ssh-path.sh`) was not started. The probe
    also found R1 Ethernet0/3 free, and node definitions for `iosv`, `cat8000v`, and
    `nxosv9000` that ask for 512, 4096, and 12288 MiB.
  - `scripts/lab/cml_lab.py add-r3 iosv` created R3 through the CML API with a day-0
    configuration, which CML kept, and linked R1 Ethernet0/3 to R3 GigabitEthernet0/0 while R1
    was running. `add-r3`'s poll saw R3 BOOTED after 181 s. CML's lab events, read later, put
    BOOTED 177 s after R3 started (181 s after it was queued); the `iosv` node definition's boot
    timeout is 180 s. ncv connected to R3's console through the same console server with the
    CML login alone, and captured it three times with no connect error.
  - The NX-OS attempt. `cml_lab.py remove-r3` ran for the first time and worked: it stopped
    the IOSv R3, wiped its disks, deleted its link, and deleted the node. `add-r3 nxosv9000`
    then created R3 (12288 MiB asked, 29757 MiB free). CML kept the day-0 configuration,
    linked R1 Ethernet0/3 to R3 Ethernet1/1, and `add-r3`'s poll saw R3 BOOTED after 483 s and
    the link STARTED. R1's side was configured and R1 Ethernet0/3 was up/up, but for 600 s R1
    saw no OSPF neighbor and no BGP peer on that link, and R1's CDP table listed only R2. The
    run stopped before any capture (exit 1), and ncv never connected to R3. R3 was left in the
    lab.
  - A read-only look at that R3 afterwards, about 36 to 44 minutes after CML started it,
    showed that its virtual machine never loaded NX-OS. Two ad-hoc scripts outside the repo
    made that look: GET calls to the CML API, and one console connection made the way ncv
    makes it. They configured nothing.
    - CML's lab events put BOOTED 478 s after R3 started (481 s after it was queued). The
      `nxosv9000` node definition's boot timeout is 480 s, so BOOTED came from the timeout, not
      from a console line.
    - 44 minutes after its start, R3's virtual machine had read 512 bytes from its disk,
      written none, kept one of its two virtual CPUs busy, and sent no packet on the R1-R3
      link. CML's console log for R3 held 12 characters.
    - The console connection timed out with an empty buffer.
    - So the day-0 configuration, the link, and ncv are not the cause. NX-OS reads its day-0
      configuration only once it runs, the link was up, and ncv never reached a prompt.
    - Inference, not proven here: the machine is stuck in its firmware, before the NX-OS boot
      loader. The likely reason is that the sandbox's CML host has an AMD processor. A Cisco
      employee wrote on the Cisco Community on 2024-12-04 that some CML reference platform
      images, NX-OSv 9000 among them, have boot issues on AMD
      ([thread](https://community.cisco.com/t5/cisco-modeling-labs-discussions/which-cml-nodes-are-not-compatible-with-amd/m-p/5232504)).
    - Still open: whether NX-OS 9000v can boot in this sandbox at all, after one attempt, and
      everything about ncv on NX-OS: the console login with two credentials, a first-boot
      dialog, and Genie's NX-OS output through the adapter.
- The scripts that drove the runs, and the sanitizer that prepared their evidence for
  publishing, are in [scripts/lab](../scripts/lab/README.md).

### When CML says BOOTED

A node definition's boot section names console lines that mean the boot is done, and a
timeout. CML also marks the node BOOTED when that timeout runs out before any of those lines
has appeared on the console. In this controller's node definitions the timeout is 180 s for
`iosv`, 480 s for `nxosv9000`, and 250 s for `cat8000v`. The NX-OS R3 on 2026-11-21 shows it:
CML's events put its BOOTED 478 s after it started, and it never loaded its system. The IOSv R3
went BOOTED 177 s after it started by CML's events, 181 s after it was queued, so its BOOTED
may have come from the timeout too. That is an inference from the timing only: its console log
was not read before the node was deleted. That R3 did run: R1 saw it as its OSPF neighbor and
BGP peer, and ncv captured it. So BOOTED is not proof that a node booted, and
`cml_lab.py add-r3`'s `R3 BOOTED` line says only what CML's state was.

Two GET calls of the CML 2.7.2 API show what a node has done:

- `GET /labs/{lab_id}/simulation_stats` returns each node's disk bytes read and written and
  its CPU and memory use, and each link's packet counts. The NX-OS R3 had sent no packet on its
  link to R1 after 44 minutes. Disk bytes alone do not tell a running node: R1 and R2, which run
  as IOL processes, showed 0 bytes read and written, while R3's virtual machine showed 512 bytes
  read, none written, and one of its two virtual CPUs busy. No booted virtual-machine node was
  sampled for comparison.
- `GET /labs/{lab_id}/nodes/{node_id}/consoles/{console_id}/log` returns what the node printed
  on that console. For the NX-OS R3 it returned 12 characters on each of its two consoles; for
  R1 and R2 it returned over a million each.

In those samples the console log and the link counters told the stuck node from the running
ones.

The `developer` login gets HTTP 403 from the `/diagnostics` calls, so it cannot see the
hypervisor's view of a node. `scripts/lab` makes neither call today; the 2026-11-21 checks were
ad-hoc read-only scripts outside the repo.

### After a real run

Raw captures hold credentials and real addressing. `captures/` and `output/` are
gitignored; keep them that way until you have read what is in them.

If you decide to publish lab evidence, run it through `scripts/lab/sanitize_capture.py`,
read what it left, put it in its own directory such as `fixtures/lab-2026-10-01/`, and
write a `SOURCE.md` beside it recording the
environment, the collection date, and exactly what was sanitized. Never relabel the
synthetic fixtures as a capture.

The 2026-09-12, 2026-09-18, 2026-11-20, and 2026-11-21 runs are recorded that way. When a new run adds evidence, update the places
that describe it: `README.md` (the evidence bullet and the paragraph on what the tests
establish), this file, and `HANDOFF.md`. Say what actually happened, with the image and
platform named. A capture against one image is evidence about that image, not about
routers in general.

## Collection behavior

The collector learns `ospf`, `bgp`, `routing`, and `interface`, then executes
`show running-config`. It has no configuration push or fault-application path.
`--features` narrows the learned set, for example `--features ospf,interface` on a
lab with no BGP; `show running-config` is always collected, and an empty value is
refused. A device that does not run a learned feature fails the capture during that
learn: Genie returns nothing for it, exactly as it does when every show command for the
feature fails to parse, and `ncv` does not guess which happened or record the
feature as empty. Leave such a feature out of `--features`.
Unicon's initialization command lists are set to empty, including overrides in
connection arguments, to avoid default configuration initialization. A device
sitting at a first-boot setup dialog (NX-OS POAP, its secure-password or
admin-password prompt, the IOS setup dialog, or `Enter enable secret`) fails the
capture at connect with
`device is at a first-boot setup dialog; ncv will not answer it`, because Unicon
would otherwise answer that dialog and so change the device; this was checked against
Unicon's mock devices only, not a real device at a first-boot dialog. On 2026-11-21 ncv
connected to an IOSv console with the CML login alone and captured it three times with no
connect error. ncv has not reached an NX-OS console; one ad-hoc read-only connection to the
NX-OS R3's console got an empty buffer. A return can
still reach the dialog before `ncv` stops the connect: Unicon's prompt recovery sends
one when a console stays silent, and a connection that sets `SENDLINE_AFTER_CRED`
sends one after its password. On the mock devices that only printed the prompt again;
what a real device does with a bare return there is its own default. One more gap was found
offline, against Unicon 26.8's mock n9k device only: with ncv's connect arguments, Unicon's
NX-OS plugin answers a device that sits at a loader prompt by sending `boot`, and one at a
boot-mode prompt by sending `load-nxos`, and the first-boot guard does not cover those
prompts. No real device was affected. It is an open item for `src/ncv/live.py`. Device plugins
and testbeds are trusted executable dependencies: this is not a security boundary
against arbitrary custom plugins.

Connection, learning, unsupported normalization, and config-read errors abort the
capture. When the `show running-config` read itself fails, the error names only the
exception's type: Unicon's timeout and failure messages quote the device's output so
far, and during that read the output is a running config with its passwords. Connections are
disconnected on success or failure, and a failed capture does not publish a partial
snapshot. Missing individual counters remain unknown
and produce `V_ERR` when requested by intent. NX-OS interface records that carry no
status (ports only `show vrf all interface` lists, and switchport-only records) are
kept as interfaces whose status is unknown; that was prepared from Genie's NX-OS test
data and has not yet been seen in a capture. Raw collected data is saved alongside
normalized JSON and `SOURCE.json` only after successful collection.

The adapter handles a limited set of Genie shapes. It does not resolve the same
OSPF neighbor occurring on multiple interfaces or in multiple VRFs; those captures
are rejected rather than silently selecting one. BGP neighbors are keyed by VRF
(`vrfs.<vrf>.neighbors.<address>`); that shape was prepared from Genie 26.8's Ops
model and its shipped test data. The 2026-11-21 iBGP capture was the first in that layout,
the bgp-vrf capture the first with peers in two VRFs (vrf NCV beside the default, on IOS XE),
and the second-platform capture wrote it for IOSv too. In it, an
intent adjacency that names no `vrf` is checked in the default VRF, as routes are; in
older flat snapshots it matches the address whatever VRF its record names. A real
router image may require adapter adjustments backed by sanitized evidence and offline
regression tests. Classic IOS 15.9 on IOSv needed none: Genie's output for it normalized
into the same snapshot layout as IOS XE.
Live-capture tests use mocks; `tests/test_lab_evidence.py` replays sanitized
captures from real CML sessions.

## Evidence handling

Running configs and raw captures can contain credentials and sensitive addressing.
Keep testbeds and captures out of git until reviewed and sanitized. Preserve the
bundled synthetic fixtures and their provenance. If you later add real lab evidence,
use a separate, clearly labeled directory and record the environment, collection
date, and sanitization performed. Do not relabel synthetic fixtures as CML captures.
