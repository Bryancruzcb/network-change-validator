"""Reports keep JSON evidence verbatim and neutralise Markdown injection."""

from __future__ import annotations

import json

from ncv.policy import Finding
from ncv.report import write_report


def test_report_escapes_markdown_and_keeps_json_evidence(tmp_path):
    finding = Finding("V_DRIFT", "r|1", "config", None, "<tag>", "line\nbreak | <script>", "review")
    path = write_report(tmp_path, "demo\n# injected", [finding])
    assert json.loads(path.read_text())["findings"][0]["after"] == "<tag>"
    md = (tmp_path / "report.md").read_text()
    assert "r\\|1" in md and "&lt;script&gt;" in md
    assert "\n# injected" not in md
