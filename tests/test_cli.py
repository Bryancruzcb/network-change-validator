"""Exit codes and argument handling for the `ncv` command line."""

from __future__ import annotations

from importlib.metadata import version

import pytest

from ncv import __version__
from ncv.cli import main


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
    assert (tmp_path / "report" / "report.json").exists()


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


@pytest.mark.parametrize("sources", [[], ["--from-dir", "fixtures/pre", "--testbed", "lab.yaml"]])
def test_snapshot_requires_exactly_one_source(tmp_path, sources):
    with pytest.raises(SystemExit) as error:
        main(["snapshot", "--output", str(tmp_path / "out"), *sources])
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()
