from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .policy import Finding


def write_report(out_dir: str | Path, intent_id: str, findings: list[Finding]) -> Path:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "intent_id": intent_id,
        "finding_count": len(findings),
        "by_policy": _count(findings),
        "findings": [
            {
                "policy_id": f.policy_id,
                "device": f.device,
                "path": f.path,
                "before": f.before,
                "after": f.after,
                "why": f.why,
                "action": f.action,
            }
            for f in findings
        ],
    }
    json_path = root / "report.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md = [f"# Change validation — {intent_id}", "", f"Findings: **{len(findings)}**", ""]
    if not findings:
        md.append("No intent violations.")
    else:
        md.append("| policy | device | path | why |")
        md.append("|---|---|---|---|")
        for f in findings:
            md.append(f"| `{f.policy_id}` | `{f.device}` | `{f.path}` | {f.why} |")
    (root / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path


def _count(findings: list[Finding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.policy_id] = out.get(f.policy_id, 0) + 1
    return out
