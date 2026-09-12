"""Reports keep JSON evidence verbatim and neutralise Markdown injection."""

from __future__ import annotations

import json

from ncv import __version__
from ncv.policy import Finding
from ncv.report import REPORT_VERSION, write_report


def test_report_escapes_markdown_and_keeps_json_evidence(tmp_path):
    finding = Finding("V_DRIFT", "r|1", "config", None, "<tag>", "line\nbreak | <script>", "review")
    path = write_report(tmp_path, "demo\n# injected", [finding])
    assert json.loads(path.read_text())["findings"][0]["after"] == "<tag>"
    md = (tmp_path / "report.md").read_text()
    assert "r\\|1" in md and "&lt;script&gt;" in md
    assert "\n# injected" not in md


def test_report_records_the_format_and_tool_that_produced_it(tmp_path):
    path = write_report(tmp_path, "demo", [])
    payload = json.loads(path.read_text())
    assert (payload["report_version"], payload["ncv_version"]) == (REPORT_VERSION, __version__)
    markdown = (tmp_path / "report.md").read_text()
    assert f"_ncv {__version__}, report format {REPORT_VERSION}._" in markdown
    assert "No intent violations." in markdown
