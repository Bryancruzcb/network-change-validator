"""Whether two ncv snapshots hold the same data: the check that an access path changes nothing.

run-ssh-path.sh captures the same routers twice in a row, once through the CML console server
and once over SSH to their management addresses, and this compares the two. It reads the five
section files (ospf, bgp, routing, interface, config) as parsed JSON and ignores SOURCE.json
and raw/, which name the testbed and so differ by design.

Usage: compare_captures.py <snapshot dir> <snapshot dir>

Exit 0 when the two hold the same data, 1 when they differ, printing each difference as
`<section>.<path>: <a> != <b>` (at most 40 lines, then the count), and 2 on bad usage or a
section file it cannot read. A running config holds passwords, so the config section is
compared line by line and a differing line is shown only when neither side looks like a
secret; every printed value is cut to 100 characters. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from itertools import zip_longest
from pathlib import Path

USAGE = "usage: compare_captures.py <snapshot dir> <snapshot dir>"
SECTIONS = ("ospf", "bgp", "routing", "interface", "config")
MAX_LINES = 40
WIDTH = 100
# A config line naming one of these may carry a secret, so neither side of it is printed.
SECRET = re.compile(r"password|secret|key|community", re.IGNORECASE)
MISSING = "<missing>"


def cut(text: str) -> str:
    return text[:WIDTH]


def _shown(value) -> str:
    return cut(json.dumps(value, sort_keys=True))


def differences(a, b, path: str = "") -> list[str]:
    """`<path>: <a> != <b>` for each leaf that differs, walking objects key by key in sorted
    order; a key on one side only shows `<missing>` on the other. Anything that is not an
    object on both sides, lists included, is compared whole."""
    if isinstance(a, dict) and isinstance(b, dict):
        lines = []
        for key in sorted(set(a) | set(b), key=str):
            where = f"{path}.{key}" if path else str(key)
            if key not in a:
                lines.append(f"{where}: {MISSING} != {_shown(b[key])}")
            elif key not in b:
                lines.append(f"{where}: {_shown(a[key])} != {MISSING}")
            else:
                lines += differences(a[key], b[key], where)
        return lines
    return [] if a == b else [f"{path}: {_shown(a)} != {_shown(b)}"]


def _running(record) -> list[str]:
    running = record.get("running") if isinstance(record, dict) else None
    return running.splitlines() if isinstance(running, str) else []


def config_differences(a: dict, b: dict) -> list[str]:
    """The config section: each device's running config compared line by line, never printing
    a line that may hold a secret."""
    lines = []
    for device in sorted(set(a) | set(b), key=str):
        if device not in a or device not in b:
            sides = ("present", MISSING) if device in a else (MISSING, "present")
            lines.append(f"config.{device}: {sides[0]} != {sides[1]}")
            continue
        pairs = zip_longest(_running(a[device]), _running(b[device]))
        for number, (left, right) in enumerate(pairs, 1):
            if left == right:
                continue
            where = f"config.{device}.running line {number} differs"
            if any(line is not None and SECRET.search(line) for line in (left, right)):
                lines.append(f"{where}: <removed>")
            else:
                shown = [MISSING if line is None else cut(line) for line in (left, right)]
                lines.append(f"{where}: {shown[0]} != {shown[1]}")
    return lines


def compare(a: dict, b: dict) -> list[str]:
    """Every difference between two snapshots given as section name -> parsed section."""
    lines = []
    for section in SECTIONS:
        if section == "config":
            lines += config_differences(a[section], b[section])
        else:
            lines += differences(a[section], b[section], section)
    return lines


def read_snapshot(directory: str) -> dict:
    """Section name -> parsed JSON. Raises ValueError naming the file it cannot read."""
    sections = {}
    for section in SECTIONS:
        path = Path(directory) / f"{section}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise ValueError(f"{path}: {err}") from err
        if not isinstance(value, dict):
            raise ValueError(f"{path}: not a JSON object")
        sections[section] = value
    return sections


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(USAGE)
        return 2
    try:
        first, second = read_snapshot(argv[1]), read_snapshot(argv[2])
    except ValueError as err:
        print(f"compare_captures.py: {err}")
        return 2
    lines = compare(first, second)
    if not lines:
        print(f"{argv[1]} and {argv[2]} hold the same data")
        return 0
    for line in lines[:MAX_LINES]:
        print(line)
    shown = "" if len(lines) <= MAX_LINES else f", the first {MAX_LINES} shown"
    print(f"{len(lines)} differences{shown}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
