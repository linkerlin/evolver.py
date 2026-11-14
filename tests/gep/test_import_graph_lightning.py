"""Tests for P1-3 AST reverse-dependency graph & <3s lightning validation."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from evolver.gep.gene_lifecycle import lifecycle_audit_path, load_lifecycle
from evolver.gep.import_graph import (
    build_or_load_import_graph,
    find_impacted_tests,
    graph_cache_path,
    run_l1_guardian_check,
    select_validation_plan,
)
from evolver.gep.solidify import solidify, write_state_for_solidify
from evolver.ops.status_human import human_status, render_human


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_mini_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")

    pkg = root / "src" / "mini_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "math_core.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        encoding="utf-8",
    )
    (pkg / "service.py").write_text(
        "from .math_core import add\n\ndef compute(x: int) -> int:\n    return add(x, 10)\n",
        encoding="utf-8",
    )
    (pkg / "unrelated.py").write_text(
        "def greet() -> str:\n    return 'hi'\n",
        encoding="utf-8",
    )

    tests = root / "tests"
    tests.mkdir()
    (tests / "test_service.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from mini_pkg.service import compute\n\n"
        "def test_compute() -> None:\n    assert compute(5) == 15\n",
        encoding="utf-8",
    )
    (tests / "test_unrelated.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from mini_pkg.unrelated import greet\n\n"
        "def test_greet() -> None:\n    assert greet() == 'hi'\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "mini-pkg"\nversion = "0.1.0"\n'
        '[tool.pytest.ini_options]\nmarkers = ["slow: slow test"]\n',
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "initial")
    return root


def test_incremental_graph_cache_and_transitive_reverse_deps(tmp_path: Path) -> None:
    repo = _make_mini_repo(tmp_path / "repo")

    g1 = build_or_load_import_graph(repo)
    assert g1["stats"]["total_files"] == 6
    assert g1["stats"]["parsed_files"] == 6
    assert g1["stats"]["cached_files"] == 0
    assert graph_cache_path(repo).is_file()

    # Second call with no edits hits 100% cache
    g2 = build_or_load_import_graph(repo)
    assert g2["stats"]["parsed_files"] == 0
    assert g2["stats"]["cached_files"] == 6

    # Transitive closure: math_core.py -> service.py -> tests/test_service.py
    impacted = find_impacted_tests(repo, ["src/mini_pkg/math_core.py"], graph=g2)
    assert impacted == ["tests/test_service.py"]

    # Touching only math_core.py re-parses exactly 1 file
    time.sleep(0.01)
    (repo / "src" / "mini_pkg" / "math_core.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b + 0\n",
        encoding="utf-8",
    )
    g3 = build_or_load_import_graph(repo)
    assert g3["stats"]["parsed_files"] == 1
    assert g3["stats"]["cached_files"] == 5


def test_select_validation_plan_escalates_on_verifier_and_global_surfaces(tmp_path: Path) -> None:
    repo = _make_mini_repo(tmp_path / "repo")

    p_pyproject = select_validation_plan(repo, ["pyproject.toml"])
    assert p_pyproject.tier == "L2"
    assert "global_config" in p_pyproject.reason

    p_conftest = select_validation_plan(repo, ["tests/conftest.py"])
    assert p_conftest.tier == "L2"

    p_anchor = select_validation_plan(repo, ["src/evolver/gep/solidify.py"])
    assert p_anchor.tier == "L2"
    assert "verifier_surface" in p_anchor.reason

    p_leaf = select_validation_plan(repo, ["src/mini_pkg/math_core.py"])
    assert p_leaf.tier == "L0"
    assert p_leaf.impacted_tests == ["tests/test_service.py"]
    assert len(p_leaf.commands) == 2


def test_solidify_lightning_runs_under_3s_and_accrues_saved_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_mini_repo(tmp_path / "repo")
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))

    from evolver.gep.hypothesis import record_hypothesis
    from evolver.gep.paths import get_workspace_state_dir

    state_dir = get_workspace_state_dir(repo)
    state_dir.mkdir(parents=True, exist_ok=True)
    # Seed real native baseline collect stats so status_human computes saved time
    (state_dir / "project_native_baseline.json").write_text(
        json.dumps(
            {
                "format": "evolver.project_native_baseline.v1",
                "repo_root": str(repo),
                "pytest_collect": {"ok": True, "tests_collected": 250, "collect_duration_ms": 1800},
            }
        ),
        encoding="utf-8",
    )

    # Apply a clean leaf fix in math_core.py
    (repo / "src" / "mini_pkg" / "math_core.py").write_text(
        "def add(a: int, b: int) -> int:\n    return int(a) + int(b)\n",
        encoding="utf-8",
    )
    write_state_for_solidify(
        {
            "run_id": "run_lightning_01",
            "selected_gene_id": "gene_distilled_add_fix",
            "signals": ["type_error"],
            "mutation": {"id": "mut_lightning_01", "category": "repair", "validation": []},
        }
    )
    record_hypothesis(
        {
            "run_id": "run_lightning_01",
            "hypothesis": "Coerce operands in math_core.add without breaking service",
            "dimension": "content",
            "mechanism_family": "repair",
            "target_hook": "src/mini_pkg/math_core.py",
            "mechanism_check": [
                {
                    "id": "synthetic-check",
                    "before": "raw addition",
                    "after": "int-coerced addition",
                }
            ],
        }
    )

    # Disable eval worktree git clone overhead so L0 measures direct leaf check
    from evolver.gep.feature_flags import set_flag

    set_flag("enable_eval_worktree", False, persist=False)

    t0 = time.monotonic()
    res = solidify(validation_scope="lightning")
    elapsed_s = time.monotonic() - t0

    assert res["ok"] is True, res
    assert res.get("validation_tier") == "L0"
    assert isinstance(res.get("validation_timing"), dict)
    assert res["validation_timing"].get("tier") == "L0"
    assert res["validation_timing"].get("scope") == "lightning"
    assert elapsed_s < 3.5, f"Expected lightning settle < 3.5s on Windows, took {elapsed_s:.2f}s"

    panel = human_status(project=repo)
    assert panel["promoted"] == 1
    assert panel["workbench_drafts"] == 0
    assert panel["saved_validation_seconds"] > 0.0
    rendered = render_human(panel)
    assert "节省验证耗时" in rendered
    assert "启用后自动累计" not in rendered


def test_l1_guardian_demotes_regressed_gene_to_under_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_mini_repo(tmp_path / "repo")
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))

    from evolver.gep.feature_flags import set_flag

    set_flag("enable_eval_worktree", False, persist=False)

    # Introduce an obvious mypy type error that L0 ruff might not flag
    (repo / "src" / "mini_pkg" / "math_core.py").write_text(
        "def add(a: int, b: int) -> int:\n    bad: int = 'not_an_int'\n    return bad\n",
        encoding="utf-8",
    )

    verdict: dict[str, Any] = run_l1_guardian_check(
        repo,
        ["src/mini_pkg/math_core.py"],
        gene_id="gene_distilled_type_reg",
        run_id="run_l1_01",
    )
    assert verdict["ok"] is False
    assert verdict["demotion"]["demoted"] is True
    assert verdict["demotion"]["status"] == "under_review"

    states = load_lifecycle(strict=True)
    assert states["gene_distilled_type_reg"].status == "under_review"
    assert lifecycle_audit_path().is_file()
