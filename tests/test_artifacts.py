"""docs/artifacts: the reports ncv writes for the committed fixtures, and the SVG summaries
drawn from them.

The README shows these files, so they must stay what the current code produces. The test
rebuilds them with scripts/render_artifacts.py and compares every file, which fails when a
change to ncv, a fixture, or the renderer leaves a checked-in copy behind. Rebuild with
`python3 scripts/render_artifacts.py`.
"""

from __future__ import annotations

import importlib.util
import sys


def _renderer(root):
    path = root / "scripts" / "render_artifacts.py"
    spec = importlib.util.spec_from_file_location("render_artifacts", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves the script's annotations through it
    spec.loader.exec_module(module)
    return module


def test_checked_in_artifacts_are_what_the_code_produces(root, tmp_path):
    built = _renderer(root).build_artifacts(tmp_path)
    art = root / "docs" / "artifacts"
    assert sorted([*built, "SOURCE.md"]) == sorted(path.name for path in art.iterdir())
    for name, content in built.items():
        checked_in = (art / name).read_text(encoding="utf-8")
        assert content == checked_in, (
            f"docs/artifacts/{name} is stale: run python3 scripts/render_artifacts.py"
        )
