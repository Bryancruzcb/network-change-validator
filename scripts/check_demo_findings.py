"""Fail when a demo report changes a finding's device, path, or why.

The checked-in demo report is the lock. This script does not render pictures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ncv.report import finding_identity


def identities(path: Path) -> list[tuple[str, str, str]]:
    findings = json.loads(path.read_text(encoding="utf-8"))["findings"]
    return [finding_identity(row) for row in findings]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check_demo_findings.py <got.json> <expected.json>", file=sys.stderr)
        return 2
    got = identities(Path(argv[1]))
    expected = identities(Path(argv[2]))
    if got != expected:
        print("fixture diff: a finding changed device, path, or why", file=sys.stderr)
        print(f"got:      {got}", file=sys.stderr)
        print(f"expected: {expected}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
