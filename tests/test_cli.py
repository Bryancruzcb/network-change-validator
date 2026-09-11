from pathlib import Path

from ncv.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_diff_demo_exits_one(tmp_path):
    code = main(
        [
            "diff",
            str(ROOT / "fixtures" / "pre"),
            str(ROOT / "fixtures" / "post"),
            "--intent",
            str(ROOT / "intents" / "demo.yaml"),
            "--report",
            str(tmp_path / "report"),
        ]
    )
    assert code == 1
    assert (tmp_path / "report" / "report.json").exists()


def test_diff_clean_exits_zero(tmp_path):
    code = main(
        [
            "diff",
            str(ROOT / "fixtures" / "pre"),
            str(ROOT / "fixtures" / "pre"),
            "--intent",
            str(ROOT / "intents" / "demo.yaml"),
            "--report",
            str(tmp_path / "report"),
        ]
    )
    assert code == 0
