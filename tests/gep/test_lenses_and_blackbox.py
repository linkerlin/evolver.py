"""Tests for built-in read-only lenses (P1-1) and in-band cycle blackbox (P1-2)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import episode_record
from evolver.gep.asset_store import upsert_gene
from evolver.gep.blackbox import (
    active_blackbox_path,
    begin_blackbox,
    compute_ast_delta,
    find_blackbox_for_round,
    load_active_blackbox,
    load_blackbox_telemetry,
    record_lens_call,
    settle_blackbox,
)
from evolver.gep.lenses import BUILTIN_LENSES, run_lens
from evolver.ops.meta_report import build_meta_report


def _init_mini_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@evolver.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Evolver Test"], cwd=repo, check=True)

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('__all__ = ["compute_score"]\n', encoding="utf-8")
    (pkg / "core.py").write_text(
        "__all__ = ['compute_score']\n\n"
        "def compute_score(items: list[int]) -> int:\n"
        "    total = 0\n"
        "    for x in items:\n"
        "        if x > 0:\n"
        "            total += x\n"
        "    try:\n"
        "        risky = 1 / 1\n"
        "    except Exception:\n"
        "        pass\n"
        "    return total\n",
        encoding="utf-8",
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text(
        "from pkg.core import compute_score\n\n"
        "def test_compute_score() -> None:\n"
        "    assert compute_score([1, -2, 3]) == 4\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )
    return repo


class TestReadOnlyLenses:
    def test_builtin_lenses_list_and_operator_delegation(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_mini_repo(temp_workspace / "repo")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))

        upsert_gene(
            {
                "type": "Gene",
                "id": "op_swallowed_exc_lens",
                "category": "repair",
                "summary": "Locate swallowed exception handlers in Python modules",
                "lens": {"builtin": "ast_hotspot", "default_target": "pkg"},
            }
        )

        listed = run_lens("list", repo_root=repo)
        assert listed["ok"] is True
        names = {item["name"] for item in listed["items"]}
        assert set(BUILTIN_LENSES) <= names
        assert "op_swallowed_exc_lens" in names

        # Operator gene lens delegates cleanly to its declared built-in lens
        delegated = run_lens("op_swallowed_exc_lens", target="", repo_root=repo)
        assert delegated["ok"] is True
        assert delegated["lens"] == "ast_hotspot"
        assert len(delegated.get("swallowed_exceptions") or []) == 1

    def test_ast_hotspot_import_impact_trace_and_contract_surface(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_mini_repo(temp_workspace / "repo")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))

        hotspot = run_lens("ast_hotspot", target="pkg", repo_root=repo)
        assert hotspot["ok"] is True
        assert any(i["symbol"] == "compute_score" for i in hotspot["items"])
        assert hotspot["swallowed_exceptions"][0]["location"] == "pkg/core.py:10"

        impact = run_lens("import_impact", target="pkg/core.py", repo_root=repo)
        assert impact["ok"] is True
        assert impact["tier"] == "L0"
        assert "tests/test_core.py" in impact["impacted_tests"]

        tb_text = (
            "Traceback (most recent call last):\n"
            f'  File "{repo / "pkg" / "core.py"}", line 6, in compute_score\n'
            "    if x > 0:\n"
            "TypeError: '>' not supported\n"
        )
        located = run_lens(
            "trace_locator",
            target=".",
            args={"traceback": tb_text},
            repo_root=repo,
        )
        assert located["ok"] is True
        assert located["items"][0]["location"] == "pkg/core.py:6"
        assert ">    6 |" in located["items"][0]["snippet"]

        surface = run_lens("contract_surface", target="pkg", repo_root=repo)
        assert surface["ok"] is True
        core_item = next(x for x in surface["items"] if x["file"] == "pkg/core.py")
        assert "compute_score" in core_item["dunder_all"]
        assert "compute_score" in core_item["public_symbols"]

        unknown = run_lens("no_such_lens", repo_root=repo)
        assert unknown["ok"] is False
        assert unknown["error"] == "unknown_lens"

    def test_lens_output_redacts_sealed_val_literals(
        self, temp_workspace: Path, armed_pack: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.conftest import SYNTHETIC_VAL_PACK

        _ = armed_pack
        repo = _init_mini_repo(temp_workspace / "repo_sealed")
        val_tasks = [t for t in SYNTHETIC_VAL_PACK["tasks"] if t.get("split") == "val"]
        assert val_tasks
        secret_title = str(val_tasks[0]["title"])
        (repo / "pkg" / "leak.py").write_text(
            f"def f():\n    # {secret_title}\n    return 1\n",
            encoding="utf-8",
        )
        located = run_lens(
            "trace_locator",
            args={"traceback": "pkg/leak.py:2"},
            repo_root=repo,
        )
        dumped = json.dumps(located, ensure_ascii=False)
        assert secret_title not in dumped
        assert "[sealed:val]" in dumped.lower()


class TestInBandBlackboxAndMetaReport:
    def test_blackbox_lifecycle_attaches_to_episode_and_drives_100pct_meta_coverage(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_mini_repo(temp_workspace / "repo_bb")
        evo_dir = temp_workspace / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
        monkeypatch.setenv("EVOLUTION_DIR", str(evo_dir))

        opened = begin_blackbox(
            "run_bb_001",
            repo,
            hypothesis="Remove swallowed exception and add helper clamp",
            selected_gene_id="gene_clean_exc",
            evolution_dir=evo_dir,
        )
        assert opened["run_id"] == "run_bb_001"
        assert active_blackbox_path(evo_dir).is_file()

        assert record_lens_call(
            "ast_hotspot",
            "pkg",
            ok=True,
            duration_ms=14,
            summary="1 swallowed handler",
            evolution_dir=evo_dir,
        )
        assert record_lens_call(
            "import_impact",
            "pkg/core.py",
            ok=True,
            duration_ms=9,
            summary="1 test impacted",
            evolution_dir=evo_dir,
        )
        active = load_active_blackbox(evo_dir)
        assert active is not None and len(active["lens_calls"]) == 2

        # Modify existing symbol compute_score and add a new symbol clamp_positive
        (repo / "pkg" / "core.py").write_text(
            "__all__ = ['compute_score', 'clamp_positive']\n\n"
            "def clamp_positive(v: int) -> int:\n"
            "    return v if v > 0 else 0\n\n"
            "def compute_score(items: list[int]) -> int:\n"
            "    return sum(clamp_positive(x) for x in items)\n",
            encoding="utf-8",
        )

        delta = compute_ast_delta(repo, {}, ["pkg/core.py"])
        assert "pkg/core.py::fn:clamp_positive" in delta["added"]
        assert "pkg/core.py::fn:compute_score" in delta["modified"]

        val_res = {
            "ok": True,
            "tier": "L0",
            "duration_ms": 420,
            "results": [
                {"command": "ruff check pkg/core.py", "ok": True},
                {"command": "pytest tests/test_core.py", "ok": True},
            ],
        }
        settled_bb = settle_blackbox(
            repo,
            run_id="run_bb_001",
            event_id="evt_bb_001",
            outcome_ok=True,
            outcome_label="promoted",
            validation_result=val_res,
            evolution_dir=evo_dir,
        )
        assert not active_blackbox_path(evo_dir).exists()
        assert settled_bb["lens_calls_count"] == 2
        assert settled_bb["lens_names"] == ["ast_hotspot", "import_impact"]
        assert settled_bb["ast_delta"]["added_count"] == 1
        assert settled_bb["ast_delta"]["modified_count"] == 1
        assert settled_bb["validation"]["checks_passed"] == 2
        assert find_blackbox_for_round(event_id="evt_bb_001", evolution_dir=evo_dir) is not None
        assert len(load_blackbox_telemetry(evo_dir)) == 1

        # Settle episode_record at cycle boundary -> blackbox + attribution auto-attached
        from evolver.gep.evidence import save_evidence

        scene: dict[str, Any] = {
            "event": {
                "type": "EvolutionEvent",
                "id": "evt_bb_001",
                "run_id": "run_bb_001",
                "timestamp": "2026-11-13T12:00:00Z",
                "gene_id": "gene_clean_exc",
                "mutation": {"id": "mut_bb_1", "category": "repair"},
                "diff_snapshot": "--- a/pkg/core.py\n+++ b/pkg/core.py\n+def clamp_positive\n",
                "outcome": {"status": "success", "score": 1.0},
            },
            "validation_result": val_res,
            "fitness_verdict": None,
            "gate": {"accepted": True, "reason": "improved"},
        }
        save_evidence("run_bb_001", "evt_bb_001", scene)
        ep = episode_record.record_round(event_id="evt_bb_001", run_id="run_bb_001")
        assert ep["ok"] is True
        body = episode_record.load_episode(ep["id"])
        assert body is not None
        bb_gate = body["gates"]["blackbox"]
        assert bb_gate["lens_calls_count"] == 2
        assert bb_gate["ast_delta"]["added_count"] == 1
        assert body["gates"]["attribution"]["status"] == "helped"

        # Verify meta-report reaches 100% process coverage with ZERO local HTTP proxy
        meta = build_meta_report(
            [scene["event"]],
            blackbox_rows=load_blackbox_telemetry(evo_dir),
        )
        panel = meta["panel"]["process_blackbox"]
        assert panel["proxy_required"] is False
        assert panel["recorded_rounds"] == 1
        assert panel["coverage_rate"] == 1.0
        assert panel["lens_call_rate"] == 1.0
        assert panel["check_pass_rate"] == 1.0
        assert panel["promoted_rounds"] == 1
