from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from . import __version__
from .policy import Finding, findings_to_dicts

# Bump only when the JSON layout changes in a way a reader must notice.
REPORT_VERSION = 1


def write_report(out_dir: str | Path, intent_id: str, findings: list[Finding]) -> Path:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "ncv_version": __version__,
        "intent_id": intent_id,
        "finding_count": len(findings),
        "by_policy": _count(findings),
        "findings": findings_to_dicts(findings),
    }
    json_path = root / "report.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md = [f"# Change validation — {_escape(intent_id)}", "", f"Findings: **{len(findings)}**", ""]
    if not findings:
        md.append("No intent violations.")
    else:
        md.append("| policy | device | path | why |")
        md.append("|---|---|---|---|")
        for f in findings:
            md.append(
                "| " + " | ".join(_escape(value) for value in (f.policy_id, f.device, f.path, f.why)) + " |"
            )
    md += ["", f"_ncv {__version__}, report format {REPORT_VERSION}._"]
    (root / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path


def _count(findings: list[Finding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.policy_id] = out.get(f.policy_id, 0) + 1
    return out


def _escape(value: str) -> str:
    text = html.escape(value).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#"):
        text = text.replace(char, "\\" + char)
    return text
