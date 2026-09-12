from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .intent import load_intent
from .policy import evaluate
from .report import write_report
from .schema import LEARNED_FEATURES
from .snapshot import copy_snapshot, load_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ncv",
        description="Intent-based pre/post validator. Fixture path is default. Live pyATS is opt-in.",
    )
    parser.add_argument("--version", action="version", version=f"ncv {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    diff = sub.add_parser("diff", help="compare two snapshot dirs against intent")
    diff.add_argument("pre")
    diff.add_argument("post")
    diff.add_argument("--intent", required=True)
    diff.add_argument("--report", required=True)

    snap = sub.add_parser("snapshot", help="capture a snapshot from a copied dir or a live lab")
    snap.add_argument("--output", required=True)
    source = snap.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-dir", help="copy an existing snapshot directory")
    source.add_argument("--testbed", help="pyATS testbed YAML (live path)")
    snap.add_argument(
        "--features",
        help="comma-separated learned features for --testbed; default is all of "
        f"{', '.join(LEARNED_FEATURES)}. Narrow it when a device does not run one of them.",
    )
    snap.add_argument(
        "--i-am-in-a-lab",
        action="store_true",
        help="required for --testbed. Confirms this is not production.",
    )

    args = parser.parse_args(argv)
    try:
        if args.cmd == "diff":
            return _diff(args)
        return _snapshot(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ncv: error: {exc}", file=sys.stderr)
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
    if args.testbed:
        from .live import snapshot_live

        features = tuple(part.strip() for part in (args.features or "").split(",") if part.strip())
        snapshot_live(
            args.testbed,
            str(out),
            i_am_in_a_lab=args.i_am_in_a_lab,
            features=features or LEARNED_FEATURES,
        )
        mode = "live"
    else:
        if args.features is not None:
            raise ValueError("--features applies to a --testbed capture only")
        copy_snapshot(args.from_dir, out)
        mode = "copy"
    print(json.dumps({"output": str(out), "mode": mode}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
