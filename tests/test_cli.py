"""Exit codes and argument handling for the `ncv` command line."""

from __future__ import annotations

import json
from importlib.metadata import version

import pytest

from ncv import __version__
from ncv.cli import main
from ncv.report import finding_identity
from scripts.check_demo_findings import main as check_findings


def test_version_flag_prints_the_package_version(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--version"])
    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == f"ncv {__version__}"


def test_packaging_metadata_matches_the_module_version():
    # The two versions are declared in different files; a report that stamps one of
    # them is only useful while they agree.
    assert version("network-change-validator") == __version__


def test_diff_demo_exits_one(tmp_path, root):
    code = main(
        [
            "diff",
            str(root / "fixtures" / "pre"),
            str(root / "fixtures" / "post"),
            "--intent",
            str(root / "intents" / "demo.yaml"),
            "--report",
            str(tmp_path / "report"),
        ]
    )
    assert code == 1
    report_json = tmp_path / "report" / "report.json"
    assert report_json.exists()
    got = json.loads(report_json.read_text(encoding="utf-8"))["findings"]
    expected_path = root / "docs" / "artifacts" / "demo-report.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))["findings"]
    assert [finding_identity(row) for row in got] == [finding_identity(row) for row in expected]
    assert check_findings(["check_demo_findings.py", str(report_json), str(expected_path)]) == 0


@pytest.mark.parametrize("field", ["device", "path", "why"])
def test_demo_lock_rejects_a_swapped_field(tmp_path, root, field):
    expected_path = root / "docs" / "artifacts" / "demo-report.json"
    report = json.loads(expected_path.read_text(encoding="utf-8"))
    report["findings"][0][field], report["findings"][1][field] = (
        report["findings"][1][field],
        report["findings"][0][field],
    )
    swapped = tmp_path / "report.json"
    swapped.write_text(json.dumps(report), encoding="utf-8")
    assert check_findings(["check_demo_findings.py", str(swapped), str(expected_path)]) == 1


def test_diff_clean_exits_zero(tmp_path, root):
    code = main(
        [
            "diff",
            str(root / "fixtures" / "pre"),
            str(root / "fixtures" / "pre"),
            "--intent",
            str(root / "intents" / "demo.yaml"),
            "--report",
            str(tmp_path / "report"),
        ]
    )
    assert code == 0


def test_invalid_input_cli_is_exit_two_without_traceback(tmp_path, root, capsys):
    assert (
        main(
            [
                "diff",
                str(tmp_path),
                str(tmp_path),
                "--intent",
                str(root / "intents/demo.yaml"),
                "--report",
                str(tmp_path / "report"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "no snapshot device data" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report").exists()


def test_features_is_refused_for_a_directory_copy(tmp_path, root, capsys):
    code = main(
        [
            "snapshot",
            "--from-dir",
            str(root / "fixtures/pre"),
            "--output",
            str(tmp_path / "out"),
            "--features",
            "ospf",
        ]
    )
    assert code == 2
    assert "--features applies to a --testbed capture only" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("value", ["", ",", " , "])
def test_an_empty_features_list_is_refused(tmp_path, capsys, value):
    out = tmp_path / "out"
    code = main(
        ["snapshot", "--testbed", "lab.yaml", "--output", str(out), "--features", value, "--i-am-in-a-lab"]
    )
    assert code == 2
    assert "--features needs at least one of ospf, bgp, routing, interface" in capsys.readouterr().err
    assert not out.exists()


def test_a_repeated_feature_is_learned_once(tmp_path, fake_lab):
    device, _ = fake_lab
    out = tmp_path / "out"
    code = main(
        [
            "snapshot",
            "--testbed",
            "lab.yaml",
            "--output",
            str(out),
            "--features",
            "interface, interface",
            "--i-am-in-a-lab",
        ]
    )
    assert code == 0
    assert [call.args[0] for call in device.learn.call_args_list] == ["interface"]


@pytest.mark.parametrize("sources", [[], ["--from-dir", "fixtures/pre", "--testbed", "lab.yaml"]])
def test_snapshot_requires_exactly_one_source(tmp_path, sources):
    with pytest.raises(SystemExit) as error:
        main(["snapshot", "--output", str(tmp_path / "out"), *sources])
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()
