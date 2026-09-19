#!/usr/bin/env python3
"""Rebuild docs/artifacts from the committed fixtures.

    python3 scripts/render_artifacts.py

Runs `ncv diff` from this checkout's src/ on the demo pair and on the three lab runs,
copies each report into docs/artifacts, and draws the two SVG summaries from those
reports. The files come out byte for byte the same on every platform, and
tests/test_artifacts.py fails when a checked-in file falls behind what this builds.
"""

from __future__ import annotations

import html
import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "docs" / "artifacts"
FIXTURES = ROOT / "fixtures"

SANS = "ui-sans-serif, system-ui, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, monospace"
WIDTH = 980
PALETTE = {
    "V_ADJ": "#b45309",
    "V_ROUTE": "#1d4ed8",
    "V_ERR": "#b91c1c",
    "V_DRIFT": "#6d28d9",
}


@dataclass(frozen=True)
class Case:
    """One `ncv diff` whose report is checked in, and the finding count it must produce."""

    name: str
    pre: Path
    post: Path
    intent: Path
    findings: int


def lab_case(day: str, run: str, intent: str, findings: int) -> Case:
    lab = FIXTURES / f"lab-{day}"
    return Case(f"lab-{day}-{run}-post", lab / run / "pre", lab / run / "post", lab / intent, findings)


DEMO = Case("demo-report", FIXTURES / "pre", FIXTURES / "post", ROOT / "intents" / "demo.yaml", 8)
# (case, title, the one change the operator made)
LAB_RUNS = (
    (
        lab_case("2026-09-12", "routes", "intent-routes.yaml", 2),
        "2026-09-12 routes",
        "shutdown R1 Ethernet0/1",
    ),
    (
        lab_case("2026-09-12", "ospf", "intent-ospf.yaml", 4),
        "2026-09-12 OSPF",
        "same shutdown after OSPF area 0",
    ),
    (
        lab_case("2026-09-18", "bgp", "intent-bgp.yaml", 3),
        "2026-09-18 BGP",
        "neighbor 1.1.1.2 shutdown on R1",
    ),
)
CASES = (DEMO, *(case for case, _, _ in LAB_RUNS))


def run_ncv_diff(case: Case, dest: Path) -> tuple[str, str]:
    """Write the case's report into dest and return the text of report.json and report.md."""
    from ncv.cli import main as ncv

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ncv(
            ["diff", str(case.pre), str(case.post), "--intent", str(case.intent), "--report", str(dest)]
        )
    expected = 1 if case.findings else 0
    if code != expected:
        raise RuntimeError(f"{case.name}: expected exit {expected}, got {code} {err.getvalue().strip()}")
    report_json = (dest / "report.json").read_text(encoding="utf-8")
    count = json.loads(report_json)["finding_count"]
    if count != case.findings:
        raise RuntimeError(f"{case.name}: expected {case.findings} findings, got {count}")
    return report_json, (dest / "report.md").read_text(encoding="utf-8")


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def summarize_state(val: object) -> str:
    if val is None:
        return "missing"
    if isinstance(val, dict):
        if "state" in val:
            extra = []
            if val.get("interface"):
                extra.append(str(val["interface"]))
            if val.get("vrf"):
                extra.append(f"vrf {val['vrf']}")
            if val.get("remote_as") is not None:
                extra.append(f"AS {val['remote_as']}")
            return str(val["state"]) + ((" · " + ", ".join(extra)) if extra else "")
        if "in_errors" in val or "crc" in val:
            parts = []
            if "in_errors" in val:
                parts.append(f"in_errors={val['in_errors']}")
            if "crc" in val:
                parts.append(f"crc={val['crc']}")
            return ", ".join(parts)
        return ", ".join(f"{key}={item}" for key, item in val.items())
    if val is True:
        return "true"
    if val is False:
        return "false"
    return str(val)


def _svg(height: int, label: str, fill: str, body: list[str]) -> str:
    head = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}"'
        f' viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{esc(label)}">',
        f'  <rect width="{WIDTH}" height="{height}" fill="{fill}"/>',
    ]
    return "\n".join([*head, *body, "</svg>"]) + "\n"


def findings_svg(report: dict[str, Any], title: str, subtitle: str) -> str:
    """One row per finding: policy chip, device and evidence path, why, and before -> after."""
    findings = report["findings"]
    row_h, header_h, footer_h = 44, 92, 36
    height = header_h + 28 + len(findings) * row_h + footer_h
    chips = "   ".join(f"{key} {value}" for key, value in (report.get("by_policy") or {}).items())
    body = [
        f'  <rect x="0" y="0" width="{WIDTH}" height="{header_h}" fill="#0f172a"/>',
        f'  <text x="24" y="36" font-size="20" font-family="{SANS}" fill="#f8fafc"'
        f' font-weight="700">{esc(title)}</text>',
        f'  <text x="24" y="60" font-size="13" font-family="{SANS}" fill="#cbd5e1">{esc(subtitle)}</text>',
        f'  <text x="24" y="80" font-size="12" font-family="{SANS}" fill="#94a3b8">'
        f"ncv {esc(report.get('ncv_version'))} · report format {esc(report.get('report_version'))}"
        f" · intent {esc(report.get('intent_id'))} · {chips}</text>",
    ]
    y = header_h + 8
    for i, finding in enumerate(findings):
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        color = PALETTE.get(finding["policy_id"], "#334155")
        before = summarize_state(finding.get("before"))
        after = summarize_state(finding.get("after"))
        body += [
            f'  <rect x="16" y="{y}" width="{WIDTH - 32}" height="{row_h - 6}" rx="8" fill="{bg}"'
            ' stroke="#e2e8f0"/>',
            f'  <rect x="28" y="{y + 10}" width="86" height="22" rx="6" fill="{color}"/>',
            f'  <text x="71" y="{y + 26}" text-anchor="middle" font-size="11" font-family="{SANS}"'
            f' fill="#fff" font-weight="700">{esc(finding["policy_id"])}</text>',
            f'  <text x="128" y="{y + 18}" font-size="12" font-family="{MONO}" fill="#0f172a">'
            f"{esc(finding['device'])} · {esc(finding['path'])}</text>",
            f'  <text x="128" y="{y + 34}" font-size="11" font-family="{SANS}" fill="#334155">'
            f"{esc(finding['why'])}</text>",
            f'  <text x="{WIDTH - 28}" y="{y + 26}" text-anchor="end" font-size="11" font-family="{SANS}"'
            f' fill="#475569">{esc(before)} → {esc(after)}</text>',
        ]
        y += row_h
    body.append(
        f'  <text x="24" y="{height - 14}" font-size="11" font-family="{SANS}" fill="#64748b">'
        "Generated from the committed fixtures by python3 -m ncv diff. Not a mock.</text>"
    )
    return _svg(height, title, "#ffffff", body)


def lab_svg(runs: list[tuple[str, str, dict[str, Any]]]) -> str:
    """One block per lab run, (title, change, report), listing the findings of pre vs post."""
    header_h, block_gap = 88, 16
    height = header_h + sum(56 + 28 * len(report["findings"]) + block_gap for _, _, report in runs) + 28
    first = runs[0][2]
    body = [
        f'  <rect x="0" y="0" width="{WIDTH}" height="{header_h}" fill="#0f172a"/>',
        f'  <text x="24" y="34" font-size="20" font-family="{SANS}" fill="#f8fafc"'
        ' font-weight="700">Lab evidence — three DevNet CML runs</text>',
        f'  <text x="24" y="56" font-size="13" font-family="{SANS}" fill="#cbd5e1">'
        "IOS XE 17.15 IOL R1–R2 in Cisco Modeling Labs 2.7.2 default-lab."
        " Sanitized captures replayed by tests/test_lab_evidence.py.</text>",
        f'  <text x="24" y="76" font-size="12" font-family="{SANS}" fill="#94a3b8">'
        "pre vs pre and pre vs restored were clean (exit 0) on every run."
        f" ncv {esc(first.get('ncv_version'))}, report format {esc(first.get('report_version'))}.</text>",
    ]
    y = header_h + 8
    for title, change, report in runs:
        count = report["finding_count"]
        block_h = 48 + 26 * len(report["findings"])
        body += [
            f'  <rect x="16" y="{y}" width="{WIDTH - 32}" height="{block_h}" rx="10" fill="#ffffff"'
            ' stroke="#e2e8f0"/>',
            f'  <text x="32" y="{y + 22}" font-size="15" font-family="{SANS}" font-weight="700"'
            f' fill="#0f172a">{esc(title)} — {count} finding{"s" if count != 1 else ""}</text>',
            f'  <text x="32" y="{y + 40}" font-size="12" font-family="{SANS}" fill="#475569">'
            f"Change: {esc(change)} · intent {esc(report['intent_id'])}</text>",
        ]
        fy = y + 58
        for finding in report["findings"]:
            color = PALETTE.get(finding["policy_id"], "#334155")
            body += [
                f'  <rect x="32" y="{fy - 12}" width="72" height="18" rx="5" fill="{color}"/>',
                f'  <text x="68" y="{fy + 1}" text-anchor="middle" font-size="10" font-family="{SANS}"'
                f' fill="#fff" font-weight="700">{esc(finding["policy_id"])}</text>',
                f'  <text x="114" y="{fy + 2}" font-size="12" font-family="{SANS}" fill="#0f172a">'
                f"{esc(finding['device'])} — {esc(finding['why'])}</text>",
            ]
            fy += 26
        y += block_h + block_gap
    body.append(
        f'  <text x="24" y="{height - 10}" font-size="11" font-family="{SANS}" fill="#64748b">'
        "Rows are the findings ncv wrote from fixtures/lab-2026-09-12 and fixtures/lab-2026-09-18."
        " One image, one simulated lab — not routers in general.</text>"
    )
    return _svg(height, "Lab evidence findings", "#f8fafc", body)


def build_artifacts(workdir: Path) -> dict[str, str]:
    """Run every case under workdir and return each docs/artifacts file name with its content."""
    files: dict[str, str] = {}
    reports: dict[str, dict[str, Any]] = {}
    for case in CASES:
        report_json, report_md = run_ncv_diff(case, workdir / case.name)
        files[f"{case.name}.json"] = report_json
        files[f"{case.name}.md"] = report_md
        reports[case.name] = json.loads(report_json)
    demo = reports[DEMO.name]
    files["demo-findings.svg"] = findings_svg(
        demo,
        f"Offline demo — {demo['finding_count']} findings",
        "fixtures/pre vs fixtures/post against intents/demo.yaml (synthetic snapshots)",
    )
    files["lab-findings.svg"] = lab_svg(
        [(title, change, reports[case.name]) for case, title, change in LAB_RUNS]
    )
    return files


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))  # render with this checkout's ncv, installed or not
    try:
        with tempfile.TemporaryDirectory(prefix="ncv-render-") as workdir:
            files = build_artifacts(Path(workdir))
    except RuntimeError as exc:
        print(f"render_artifacts: {exc}", file=sys.stderr)
        return 1
    for name, content in files.items():
        (ART / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote docs/artifacts/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
