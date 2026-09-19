#!/usr/bin/env python3
"""Rebuild docs/artifacts from the committed fixtures.

Run from the repository root:

    PYTHONPATH=src python3 scripts/render_artifacts.py
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "docs" / "artifacts"

CASES = [
    (
        "demo-report",
        ROOT / "fixtures" / "pre",
        ROOT / "fixtures" / "post",
        ROOT / "intents" / "demo.yaml",
        1,
        8,
    ),
    (
        "lab-2026-09-12-routes-post",
        ROOT / "fixtures" / "lab-2026-09-12" / "routes" / "pre",
        ROOT / "fixtures" / "lab-2026-09-12" / "routes" / "post",
        ROOT / "fixtures" / "lab-2026-09-12" / "intent-routes.yaml",
        1,
        2,
    ),
    (
        "lab-2026-09-12-ospf-post",
        ROOT / "fixtures" / "lab-2026-09-12" / "ospf" / "pre",
        ROOT / "fixtures" / "lab-2026-09-12" / "ospf" / "post",
        ROOT / "fixtures" / "lab-2026-09-12" / "intent-ospf.yaml",
        1,
        4,
    ),
    (
        "lab-2026-09-18-bgp-post",
        ROOT / "fixtures" / "lab-2026-09-18" / "bgp" / "pre",
        ROOT / "fixtures" / "lab-2026-09-18" / "bgp" / "post",
        ROOT / "fixtures" / "lab-2026-09-18" / "intent-bgp.yaml",
        1,
        3,
    ),
]

PALETTE = {
    "V_ADJ": "#b45309",
    "V_ROUTE": "#1d4ed8",
    "V_ERR": "#b91c1c",
    "V_DRIFT": "#6d28d9",
}


def run_diff(pre: Path, post: Path, intent: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ncv",
            "diff",
            str(pre),
            str(post),
            "--intent",
            str(intent),
            "--report",
            str(dest),
        ],
        cwd=ROOT,
        check=False,
    )
    report = json.loads((dest / "report.json").read_text())
    return completed.returncode, report


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
            return str(val["state"]) + ((" \u00b7 " + ", ".join(extra)) if extra else "")
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


def write_findings_svg(report: dict, title: str, subtitle: str, path: Path) -> None:
    findings = report["findings"]
    row_h = 44
    header_h = 92
    footer_h = 36
    width = 980
    height = header_h + 28 + len(findings) * row_h + footer_h
    rows = []
    y = header_h + 8
    for i, finding in enumerate(findings):
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        color = PALETTE.get(finding["policy_id"], "#334155")
        before = summarize_state(finding.get("before"))
        after = summarize_state(finding.get("after"))
        rows.append(
            f"""
  <rect x=\"16\" y=\"{y}\" width=\"{width-32}\" height=\"{row_h-6}\" rx=\"8\" fill=\"{bg}\" stroke=\"#e2e8f0\"/>
  <rect x=\"28\" y=\"{y+10}\" width=\"86\" height=\"22\" rx=\"6\" fill=\"{color}\"/>
  <text x=\"71\" y=\"{y+26}\" text-anchor=\"middle\" font-size=\"11\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#fff\" font-weight=\"700\">{esc(finding['policy_id'])}</text>
  <text x=\"128\" y=\"{y+18}\" font-size=\"12\" font-family=\"ui-monospace, SFMono-Regular, Menlo, monospace\" fill=\"#0f172a\">{esc(finding['device'])} \u00b7 {esc(finding['path'])}</text>
  <text x=\"128\" y=\"{y+34}\" font-size=\"11\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#334155\">{esc(finding['why'])}</text>
  <text x=\"{width-28}\" y=\"{y+26}\" text-anchor=\"end\" font-size=\"11\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#475569\">{esc(before)} \u2192 {esc(after)}</text>
"""
        )
        y += row_h
    by = report.get("by_policy") or {}
    chips = "   ".join(f"{key} {value}" for key, value in by.items())
    path.write_text(
        f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{esc(title)}\">
  <rect width=\"{width}\" height=\"{height}\" fill=\"#ffffff\"/>
  <rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{header_h}\" fill=\"#0f172a\"/>
  <text x=\"24\" y=\"36\" font-size=\"20\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#f8fafc\" font-weight=\"700\">{esc(title)}</text>
  <text x=\"24\" y=\"60\" font-size=\"13\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#cbd5e1\">{esc(subtitle)}</text>
  <text x=\"24\" y=\"80\" font-size=\"12\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#94a3b8\">ncv {esc(report.get('ncv_version'))} \u00b7 report format {esc(report.get('report_version'))} \u00b7 intent {esc(report.get('intent_id'))} \u00b7 {chips}</text>
  {''.join(rows)}
  <text x=\"24\" y=\"{height-14}\" font-size=\"11\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#64748b\">Generated from the committed fixtures by python3 -m ncv diff. Not a mock.</text>
</svg>
"""
    )


def write_lab_svg(reports: list, path: Path) -> None:
    width = 980
    header_h = 88
    block_gap = 16
    height = header_h + sum(56 + 28 * len(item[2]["findings"]) + block_gap for item in reports) + 28
    y = header_h + 8
    parts = []
    for title, change, report in reports:
        block_h = 48 + 26 * len(report["findings"])
        parts.append(
            f'<rect x=\"16\" y=\"{y}\" width=\"{width-32}\" height=\"{block_h}\" rx=\"10\" fill=\"#ffffff\" stroke=\"#e2e8f0\"/>'
        )
        plural = "s" if report["finding_count"] != 1 else ""
        parts.append(
            f'<text x=\"32\" y=\"{y+22}\" font-size=\"15\" font-family=\"ui-sans-serif, system-ui, sans-serif\" font-weight=\"700\" fill=\"#0f172a\">{esc(title)} \u2014 {report["finding_count"]} finding{plural}</text>'
        )
        parts.append(
            f'<text x=\"32\" y=\"{y+40}\" font-size=\"12\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#475569\">Change: {esc(change)} \u00b7 intent {esc(report["intent_id"])}</text>'
        )
        fy = y + 58
        for finding in report["findings"]:
            color = PALETTE.get(finding["policy_id"], "#334155")
            parts.append(f'<rect x=\"32\" y=\"{fy-12}\" width=\"72\" height=\"18\" rx=\"5\" fill=\"{color}\"/>')
            parts.append(
                f'<text x=\"68\" y=\"{fy+1}\" text-anchor=\"middle\" font-size=\"10\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#fff\" font-weight=\"700\">{esc(finding["policy_id"])}</text>'
            )
            parts.append(
                f'<text x=\"114\" y=\"{fy+2}\" font-size=\"12\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#0f172a\">{esc(finding["device"])} \u2014 {esc(finding["why"])}</text>'
            )
            fy += 26
        y += block_h + block_gap
    path.write_text(
        f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Lab evidence findings\">
  <rect width=\"{width}\" height=\"{height}\" fill=\"#f8fafc\"/>
  <rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{header_h}\" fill=\"#0f172a\"/>
  <text x=\"24\" y=\"34\" font-size=\"20\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#f8fafc\" font-weight=\"700\">Lab evidence \u2014 three DevNet CML runs</text>
  <text x=\"24\" y=\"56\" font-size=\"13\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#cbd5e1\">IOS XE 17.15 IOL R1\u2013R2 in Cisco Modeling Labs 2.7.2 default-lab. Sanitized captures replayed by tests/test_lab_evidence.py.</text>
  <text x=\"24\" y=\"76\" font-size=\"12\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#94a3b8\">pre vs pre and pre vs restored were clean (exit 0) on every run. ncv 0.1.0, report format 1.</text>
  {''.join(parts)}
  <text x=\"24\" y=\"{height-10}\" font-size=\"11\" font-family=\"ui-sans-serif, system-ui, sans-serif\" fill=\"#64748b\">Rows are the findings ncv wrote from fixtures/lab-2026-09-12 and fixtures/lab-2026-09-18. One image, one simulated lab \u2014 not routers in general.</text>
</svg>
"""
    )


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    reports = {}
    for name, pre, post, intent, expected_exit, expected_count in CASES:
        code, report = run_diff(pre, post, intent, Path("/tmp") / f"ncv-render-{name}")
        if code != expected_exit:
            raise SystemExit(f"{name}: expected exit {expected_exit}, got {code}")
        if report["finding_count"] != expected_count:
            raise SystemExit(
                f"{name}: expected {expected_count} findings, got {report['finding_count']}"
            )
        (ART / f"{name}.json").write_text((Path("/tmp") / f"ncv-render-{name}" / "report.json").read_text())
        (ART / f"{name}.md").write_text((Path("/tmp") / f"ncv-render-{name}" / "report.md").read_text())
        reports[name] = report
        print(f"{name}: exit {code}, {report['finding_count']} findings")

    write_findings_svg(
        reports["demo-report"],
        "Offline demo \u2014 8 findings",
        "fixtures/pre vs fixtures/post against intents/demo.yaml (synthetic snapshots)",
        ART / "demo-findings.svg",
    )
    write_lab_svg(
        [
            ("2026-09-12 routes", "shutdown R1 Ethernet0/1", reports["lab-2026-09-12-routes-post"]),
            ("2026-09-12 OSPF", "same shutdown after OSPF area 0", reports["lab-2026-09-12-ospf-post"]),
            ("2026-09-18 BGP", "neighbor 1.1.1.2 shutdown on R1", reports["lab-2026-09-18-bgp-post"]),
        ],
        ART / "lab-findings.svg",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
