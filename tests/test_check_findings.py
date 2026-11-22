"""scripts/lab/check_findings.py: a run's change report against the findings it predicted.

A run script checks its change comparison's report.json against the expected file next to its
intent (beside the run's evidence once it is recorded), and tests/test_lab_scripts.py reads the
same files. These tests pin the parser and the comparison on small inputs, then the command
line's exit codes.
"""

from __future__ import annotations

import json

import pytest
from test_lab_scripts import _load_script

EXPECTED = """\
# predicted findings of a change comparison
V_ADJ R1 ospf.neighbors.2.2.2.2  # gone

V_ADJ R2 ospf.neighbors.1.1.1.1
"""
TRIPLES = {("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"), ("V_ADJ", "R2", "ospf.neighbors.1.1.1.1")}


@pytest.fixture
def check(root):
    return _load_script(root, "check_findings.py")


def _report(findings):
    return {"findings": [{"policy_id": p, "device": d, "path": path, "why": "w"} for p, d, path in findings]}


def test_the_expected_file_skips_comments_and_blank_lines(check):
    assert check.parse_expected(EXPECTED, "expect.txt") == TRIPLES
    assert check.parse_expected("", "expect.txt") == frozenset()
    assert check.parse_expected("# only a comment\n\n   \n", "expect.txt") == frozenset()


@pytest.mark.parametrize(
    "line",
    ["V_ADJ R1", "V_ADJ R1 ospf.neighbors.2.2.2.2 extra", "V_ADJ", "V_ADJ R1 # path commented out"],
)
def test_a_line_that_is_not_three_fields_is_refused_with_its_file_and_line_number(check, line):
    with pytest.raises(ValueError, match=r"^expect\.txt:3: expected '<policy> <device> <path>'"):
        check.parse_expected(f"# header\n\n{line}\n", "expect.txt")


def test_the_report_gives_policy_device_and_path_of_each_finding(check):
    assert check.report_findings(_report(sorted(TRIPLES)), "report.json") == TRIPLES
    assert check.report_findings({"findings": []}, "report.json") == frozenset()


@pytest.mark.parametrize(
    "report",
    [
        [],
        {"summary": {}},
        {"findings": {}},
        {"findings": [{"device": "R1", "path": "p"}]},
        {"findings": ["x"]},
    ],
)
def test_something_that_is_not_an_ncv_report_is_refused_with_its_file(check, report):
    with pytest.raises(ValueError, match=r"^report\.json: "):
        check.report_findings(report, "report.json")


def test_equal_sets_have_no_differences_and_order_does_not_matter(check):
    assert check.differences(frozenset(TRIPLES), frozenset(TRIPLES)) == []


def test_a_predicted_finding_not_found_is_missing_and_an_extra_one_is_unexpected(check):
    got = {("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"), ("V_DRIFT", "R1", "config.running.must_absent")}
    assert check.differences(frozenset(got), frozenset(TRIPLES)) == [
        "missing: V_ADJ R2 ospf.neighbors.1.1.1.1",
        "unexpected: V_DRIFT R1 config.running.must_absent",
    ]


def _files(tmp_path, findings, expected=EXPECTED):
    report, expect = tmp_path / "report.json", tmp_path / "expect.txt"
    report.write_text(json.dumps(_report(findings)), encoding="utf-8")
    expect.write_text(expected, encoding="utf-8")
    return str(report), str(expect)


def test_cli_exits_0_when_the_report_finds_exactly_the_predicted_findings(check, tmp_path, capsys):
    assert check.main(["check_findings.py", *_files(tmp_path, sorted(TRIPLES))]) == 0
    assert capsys.readouterr().out.startswith("2 findings, as ")


def test_cli_exits_1_and_names_each_difference(check, tmp_path, capsys):
    report, expect = _files(tmp_path, [("V_ADJ", "R1", "ospf.neighbors.2.2.2.2"), ("V_ROUTE", "R1", "r")])
    assert check.main(["check_findings.py", report, expect]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["missing: V_ADJ R2 ospf.neighbors.1.1.1.1", "unexpected: V_ROUTE R1 r"]
    assert out[2] == f"2 findings in {report}; {expect} predicts 2"


def test_cli_exits_1_when_a_change_found_nothing(check, tmp_path, capsys):
    assert check.main(["check_findings.py", *_files(tmp_path, [])]) == 1
    assert capsys.readouterr().out.count("missing: ") == 2


@pytest.mark.parametrize("argv", [["check_findings.py"], ["check_findings.py", "a"], ["c", "a", "b", "c"]])
def test_cli_bad_usage_exits_2(check, argv, capsys):
    assert check.main(argv) == 2
    assert capsys.readouterr().err.strip() == check.USAGE


def test_cli_unreadable_or_malformed_input_exits_2_naming_the_file(check, tmp_path, capsys):
    report, expect = _files(tmp_path, sorted(TRIPLES))
    missing = str(tmp_path / "no-such-report.json")
    assert check.main(["check_findings.py", missing, expect]) == 2
    assert missing in capsys.readouterr().err
    (tmp_path / "report.json").write_text("not json", encoding="utf-8")
    assert check.main(["check_findings.py", report, expect]) == 2
    assert f"{report}: not JSON" in capsys.readouterr().err
    report, expect = _files(tmp_path, sorted(TRIPLES), EXPECTED + "V_ADJ R3\n")
    assert check.main(["check_findings.py", report, expect]) == 2
    assert f"{expect}:5: expected" in capsys.readouterr().err


@pytest.mark.parametrize(
    "name",
    [
        "fixtures/lab-2026-11-21/expect-ospf-deadtimer.txt",
        "fixtures/lab-2026-11-21/expect-ibgp.txt",
        "fixtures/lab-2026-11-21/expect-bgp-vrf.txt",
        "scripts/lab/expect-second-platform-nxosv9000.txt",
        "scripts/lab/expect-second-platform-cat8000v.txt",
        "fixtures/lab-2026-11-21/expect-second-platform-iosv.txt",
    ],
)
def test_each_expected_file_parses_and_says_it_is_a_prediction(check, root, name):
    path = root.joinpath(*name.split("/"))
    text = path.read_text(encoding="utf-8")
    assert check.parse_expected(text, str(path))
    assert "written before any capture exists" in " ".join(text.replace("#", " ").split())
