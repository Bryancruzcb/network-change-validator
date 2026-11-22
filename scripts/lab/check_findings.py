"""Check a lab comparison's findings against the prediction written before the run.

A comparison that exits 1 has found something, but not necessarily what the run predicted:
one V_ADJ in place of two, or an extra V_DRIFT, exits 1 all the same. So each run that
sources _lib.sh keeps the predicted findings of its change comparison in an expect file, one
per line as `<policy> <device> <path>`, with `#` starting a comment and blank lines ignored: a
recorded run's next to its evidence (fixtures/lab-2026-11-21/expect-<run>.txt), and the
second-platform run's for a platform with no recorded run in
scripts/lab/expect-second-platform-<platform>.txt. The
run script checks its report against that file through _lib.sh's expect_findings, and
tests/test_lab_scripts.py reads the same file to pin the prediction on synthetic snapshots, so
the two can never drift apart.

Exit 0 when the report's (policy_id, device, path) set equals the file's, 1 when it does not
(each difference printed as a `missing:` or `unexpected:` line), and 2 on bad usage or input
that cannot be read. Standard library only, and outside ncv like the rest of scripts/lab.

Usage:
  check_findings.py <report.json> <expected file>
  check_findings.py output/lab/ibgp-<stamp>-change/report.json fixtures/lab-2026-11-21/expect-ibgp.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = "usage: check_findings.py <report.json> <expected file>"

Finding = tuple[str, str, str]


def parse_expected(text: str, source: str) -> frozenset[Finding]:
    """The findings an expected file names. A line that is not exactly three fields once its
    comment is cut off is refused with its file and line number, so a typo cannot quietly turn
    into a prediction nobody meant."""
    findings = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) != 3:
            raise ValueError(f"{source}:{number}: expected '<policy> <device> <path>', got {raw.strip()!r}")
        findings.add((fields[0], fields[1], fields[2]))
    return frozenset(findings)


def report_findings(report: object, source: str) -> frozenset[Finding]:
    """The (policy_id, device, path) of every finding in an ncv report.json."""
    rows = report.get("findings") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{source}: not an ncv report: no findings list")
    try:
        return frozenset((row["policy_id"], row["device"], row["path"]) for row in rows)
    except (KeyError, TypeError) as error:
        raise ValueError(f"{source}: a finding lacks policy_id, device, or path") from error


def differences(got: frozenset[Finding], expected: frozenset[Finding]) -> list[str]:
    """One line per finding predicted but not found, then one per finding found but not
    predicted, each sorted; empty when the two sets are equal."""
    missing = [f"missing: {' '.join(finding)}" for finding in sorted(expected - got)]
    unexpected = [f"unexpected: {' '.join(finding)}" for finding in sorted(got - expected)]
    return missing + unexpected


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{path}: cannot read: {error}") from error


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) != 3:
        print(USAGE, file=sys.stderr)
        return 2
    report_path, expected_path = Path(argv[1]), Path(argv[2])
    try:
        got = report_findings(json.loads(_read(report_path)), str(report_path))
        expected = parse_expected(_read(expected_path), str(expected_path))
    except json.JSONDecodeError as error:
        print(f"check_findings.py: {report_path}: not JSON: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"check_findings.py: {error}", file=sys.stderr)
        return 2
    lines = differences(got, expected)
    for line in lines:
        print(line)
    if lines:
        print(f"{len(got)} findings in {report_path}; {expected_path} predicts {len(expected)}")
        return 1
    print(f"{len(got)} findings, as {expected_path} predicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
