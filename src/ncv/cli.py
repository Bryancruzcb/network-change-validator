from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .intent import load_intent
from .policy import evaluate
from .report import write_report
from .snapshot import load_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ncv",
        description="Intent-based pre/post validator. Fixture path is default. Live pyATS is opt-in.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    diff = sub.add_parser("diff", help="compare two snapshot dirs against intent")
    diff.add_argument("pre")
    diff.add_argument("post")
    diff.add_argument("--intent", required=True)
    diff.add_argument("--report", required=True)

    snap = sub.add_parser("snapshot", help="capture a snapshot from a copied dir or a live lab")
    snap.add_argument("--output", required=True)
    snap.add_argument("--from-dir", help="copy an existing snapshot directory")
    snap.add_argument("--testbed", help="pyATS testbed YAML (live path)")
    snap.add_argument(
        "--i-am-in-a-lab",
        action="store_true",
        help="required for --testbed. Confirms this is not production.",
    )

    args = parser.parse_args(argv)
    if args.cmd == "diff":
        return _diff(args)
    if args.cmd == "snapshot":
        return _snapshot(args)
    return 2


def _diff(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    pre = load_snapshot(args.pre)
    post = load_snapshot(args.post)
    findings = evaluate(intent, pre, post)
    path = write_report(args.report, intent.intent_id, findings)
    print(json.dumps({"report": str(path), "finding_count": len(findings)}, indent=2))
    return 1 if findings else 0


def _snapshot(args: argparse.Namespace) -> int:
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.testbed:
        from .live import snapshot_live

        snapshot_live(args.testbed, str(out), i_am_in_a_lab=args.i_am_in_a_lab)
        print(json.dumps({"output": str(out), "mode": "live"}))
        return 0
    if args.from_dir:
        src = Path(args.from_dir)
        for name in ("ospf", "routing", "interface", "config"):
            fp = src / f"{name}.json"
            if fp.exists():
                (out / f"{name}.json").write_text(fp.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps({"output": str(out), "mode": "copy"}))
        return 0
    print("snapshot needs --from-dir or --testbed --i-am-in-a-lab", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
