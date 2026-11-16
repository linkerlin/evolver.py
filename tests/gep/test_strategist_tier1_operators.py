"""Strategist Tier 1 tests: S-1 slots/dedup, S-2 DAG, P2-1 seeds, S-8b gate, P2-2 synth."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from evolver.gep import distill
from evolver.gep.asset_store import genes_seed_path, load_genes, upsert_gene
from evolver.gep.lenses import BUILTIN_LENSES, run_lens
from evolver.gep.operator_sandbox import (
    audit_operator_ast,
    detect_operator_dag_cycle,
    run_lens_code_sandboxed,
    scrub_operator_env,
)
from evolver.gep.operator_slots import (
    apply_slot_overrides,
    deduplicate_or_bind_operator,
    list_operator_slots,
    render_with_overrides,
    structural_hash,
    validate_slot_overrides,
)
from evolver.gep.operator_synthesizer import synthesize_operator_from_fix
from evolver.gep.policy_check import detect_anti_cheat_violations
from evolver.gep.schemas.gene import Gene
from evolver.gep.solidify import solidify, write_state_for_solidify


@pytest.fixture
def isolated_op_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated workspace + GEP assets + EVOLVER_HOME."""
    home = tmp_path / ".evomap-home"
    gep = tmp_path / ".evolver" / "gep"
    evo = tmp_path / ".evolver" / "evolution"
    gep.mkdir(parents=True, exist_ok=True)
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return tmp_path


class TestS1OperatorSlotsAndDedup:
    def test_structural_hash_invariant_to_slot_literals_and_docstrings(self) -> None:
        src_a = '''
def run(ctx, target=".", args=None):
    """Docstring alpha version."""
    SLOT_MSG = "Found risky pattern in alpha"
    hits = []
    for rel, txt in ctx.iter_py(target):
        if "eval(" in txt:
            hits.append({"file": rel, "msg": f"{SLOT_MSG}: {rel}"})
    return {"summary": "done alpha", "items": hits}
'''
        src_b = '''
def run(ctx, target=".", args=None):
    """Completely different docstring beta."""
    SLOT_MSG = "Detected dangerous call in beta"
    hits = []
    for rel, txt in ctx.iter_py(target):
        if "exec(" in txt:
            hits.append({"file": rel, "msg": f"{SLOT_MSG}: {rel}"})
    return {"summary": "finished beta", "items": hits}
'''
        src_diff_flow = """
def run(ctx, target=".", args=None):
    SLOT_MSG = "Detected dangerous call in beta"
    hits = []
    for rel, txt in ctx.iter_py(target):
        if "exec(" in txt and len(txt) > 10:
            hits.append({"file": rel, "msg": f"{SLOT_MSG}: {rel}"})
    return {"summary": "finished beta", "items": hits}
"""
        h_a = structural_hash(src_a)
        h_b = structural_hash(src_b)
        h_c = structural_hash(src_diff_flow)
        assert h_a is not None and h_a == h_b
        assert h_c is not None and h_c != h_a

    def test_slot_listing_validation_and_override_rendering(self) -> None:
        src = """
def run(ctx, target=".", args=None):
    SLOT_PAT = "bare_except"
    return {"summary": f"Check {target} for {SLOT_PAT}", "items": []}
"""
        slots = list_operator_slots(src)
        assert len(slots) >= 2
        fslot = next(s for s in slots if s["fstring"])
        assert set(fslot["placeholders"]) == {"SLOT_PAT", "target"}

        assert validate_slot_overrides(src, {fslot["id"]: "Audit {target} :: {SLOT_PAT}"}) == []
        bad_unknown = validate_slot_overrides(src, {"s99": "nope"})
        assert any("unknown slot" in msg for msg in bad_unknown)
        bad_ph = validate_slot_overrides(src, {fslot["id"]: "Missing placeholders"})
        assert any("must preserve placeholders" in msg for msg in bad_ph)

        tree = apply_slot_overrides(
            src, {"s1": "custom_token", fslot["id"]: "Scan {target}:{SLOT_PAT}"}
        )
        rendered = render_with_overrides(src, {"s1": "custom_token"})
        assert rendered is not None and "custom_token" in rendered
        assert isinstance(tree.body[0], object)

    def test_deduplicate_and_distill_merge_slot_bindings_zero_clone_growth(
        self, isolated_op_ws: Path
    ) -> None:
        code_1 = """
def run(ctx, target=".", args=None):
    SLOT_NEEDLE = "alpha_bug"
    out = []
    for rel, txt in ctx.iter_py(target):
        if SLOT_NEEDLE in txt:
            out.append({"file": rel, "needle": SLOT_NEEDLE})
    return {"summary": "scan one", "items": out}
"""
        code_2 = """
def run(ctx, target=".", args=None):
    SLOT_NEEDLE = "beta_bug"
    out = []
    for rel, txt in ctx.iter_py(target):
        if SLOT_NEEDLE in txt:
            out.append({"file": rel, "needle": SLOT_NEEDLE})
    return {"summary": "scan two", "items": out}
"""
        canonical = {
            "type": "Gene",
            "id": "gene_op_canon",
            "category": "repair",
            "signals_match": ["alpha_bug"],
            "strategy": ["run op"],
            "operator_kind": "new",
            "lens": code_1,
        }
        upsert_gene(canonical)
        res = deduplicate_or_bind_operator(
            {**canonical, "id": "gene_op_clone_1", "lens": code_2},
            load_genes(),
            run_id="run_1",
            signals=["beta_bug"],
        )
        assert res["duplicate"] is True
        assert res["canonical_id"] == "gene_op_canon"
        assert len(res["merged_gene"]["slot_bindings"]) == 1
        assert res["slot_binding"]["slots"]

        # Now go through distill.install_distilled and confirm gene count stays constant
        before_count = len(load_genes())
        distill_res = distill.install_distilled(
            {
                "genes": [
                    {
                        "type": "Gene",
                        "id": "gene_distilled_clone_2",
                        "category": "repair",
                        "signals_match": ["gamma_bug"],
                        "strategy": ["run op", "fix minimally"],
                        "operator_kind": "new",
                        "lens": code_2.replace("beta_bug", "gamma_bug"),
                    }
                ],
                "capsules": [],
            },
            strict_transferable=False,
        )
        assert distill_res["ok"] is True
        assert distill_res["installed"][0]["action"] == "merged_slot_binding"
        assert len(load_genes()) == before_count


class TestS2ComposedOperatorDAG:
    def test_composed_seed_runs_child_lenses_via_run_lens(self, isolated_op_ws: Path) -> None:
        (isolated_op_ws / "src").mkdir(exist_ok=True)
        (isolated_op_ws / "src" / "broken.py").write_text(
            "def boom(x):\n    return x / 0\n", encoding="utf-8"
        )
        (isolated_op_ws / "tests").mkdir(exist_ok=True)
        (isolated_op_ws / "tests" / "test_broken.py").write_text(
            "from src.broken import boom\n\ndef test_it():\n    boom(1)\n", encoding="utf-8"
        )
        raw_seed = json.loads(genes_seed_path().read_text(encoding="utf-8"))
        for seed in raw_seed.get("genes", []):
            if str(seed.get("id", "")).startswith("op_"):
                upsert_gene(seed)

        tb = 'Traceback:\n  File "src/broken.py", line 2, in boom\n    return x / 0'
        res = run_lens(
            name="op_traceback_blast_audit",
            target=".",
            args={"traceback": tb},
            repo_root=isolated_op_ws,
        )
        assert res["ok"] is True
        assert res["read_only"] is True
        assert len(res.get("items") or []) >= 1

    def test_cycle_and_dependency_audit_blocks_invalid_dags(self) -> None:
        cyc = detect_operator_dag_cycle("op_a", ["op_b"], {"op_b": ["op_c"], "op_c": ["op_a"]})
        assert cyc == ["op_a", "op_b", "op_c", "op_a"]

        # Undeclared ctx.call_lens call
        code_undeclared = """
def run(ctx, target=".", args=None):
    return ctx.call_lens("ast_hotspot", target)
"""
        aud1 = audit_operator_ast(
            code_undeclared,
            operator_id="op_bad",
            operator_kind="composed",
            declared_deps=["trace_locator"],
            known_lenses=BUILTIN_LENSES,
        )
        assert aud1["ok"] is False
        assert any("never called" in v for v in aud1["violations"])
        assert any("undeclared" in v for v in aud1["violations"])

        # Retired dependency
        aud2 = audit_operator_ast(
            """
def run(ctx, target=".", args=None):
    return ctx.call_lens("trace_locator", target)
""",
            operator_id="op_ret",
            operator_kind="composed",
            declared_deps=["trace_locator"],
            known_lenses=BUILTIN_LENSES,
            retired_ids={"trace_locator"},
        )
        assert aud2["ok"] is False
        assert any("retired" in v for v in aud2["violations"])


class TestP21SeedsAndSandbox:
    def test_all_8_seed_operators_validate_and_run_in_sandbox(self, isolated_op_ws: Path) -> None:
        (isolated_op_ws / "sample.py").write_text(
            "import subprocess, json\n\n"
            "def f(raw, p):\n"
            "    subprocess.run(['echo', 'hi'])\n"
            "    return json.loads(raw)\n",
            encoding="utf-8",
        )
        raw_seed = json.loads(genes_seed_path().read_text(encoding="utf-8"))
        seeds = raw_seed.get("genes", [])
        op_seeds = [g for g in seeds if str(g.get("id", "")).startswith("op_")]
        expected_ids = {
            "op_unguarded_subscript",
            "op_swallowed_exception_audit",
            "op_platform_path_audit",
            "op_atomic_write_audit",
            "op_subprocess_timeout_audit",
            "op_sqlite_handle_leak_audit",
            "op_boundary_clamp_audit",
            "op_traceback_blast_audit",
        }
        assert {str(g["id"]) for g in op_seeds} == expected_ids

        known = set(BUILTIN_LENSES) | {str(g["id"]) for g in op_seeds}
        for seed in op_seeds:
            validated = Gene.model_validate(seed)
            assert validated.id == seed["id"]
            upsert_gene(seed)

        for seed in op_seeds:
            code = str(seed["lens"])
            audit = audit_operator_ast(
                code,
                operator_id=str(seed["id"]),
                operator_kind=str(seed.get("operator_kind") or "new"),
                declared_deps=list(seed.get("builds_on") or []),
                known_lenses=known,
            )
            assert audit["ok"] is True, f"{seed['id']} audit failed: {audit}"
            res = run_lens(name=str(seed["id"]), target=".", repo_root=isolated_op_ws)
            assert res["ok"] is True, f"{seed['id']} runtime failed: {res}"

    def test_sandbox_blocks_network_and_file_writes_and_scrubs_secrets(self) -> None:
        for bad_code in (
            "import socket\ndef run(ctx, target='.', args=None):\n    return {'items': []}\n",
            (
                "from urllib.request import urlopen\n"
                "def run(ctx, target='.', args=None):\n    return {'items': []}\n"
            ),
            (
                "def run(ctx, target='.', args=None):\n"
                "    open('x.txt', 'w').write('z')\n    return {'items': []}\n"
            ),
            (
                "from pathlib import Path\n"
                "def run(ctx, target='.', args=None):\n"
                "    Path('x.txt').write_text('z')\n    return {'items': []}\n"
            ),
            (
                "def run(ctx, target='.', args=None):\n"
                "    g = ctx.resolve_safe.__globals__\n"
                "    return {'items': [list(g.keys())]}\n"
            ),
            (
                "def run(ctx, target='.', args=None):\n"
                "    subs = ().__class__.__bases__[0].__subclasses__()\n"
                "    return {'items': [len(subs)]}\n"
            ),
            (
                "def run(ctx, target='.', args=None):\n"
                "    return ctx._call_lens_fn('ast_hotspot', '.', None, 0)\n"
            ),
        ):
            res = run_lens_code_sandboxed(bad_code, ctx=object(), operator_id="bad_op")
            assert res["ok"] is False
            assert res["error"] == "sandbox_audit_failed"

        # Daemon timeout stops blocking caller and never leaves non-daemon join hangs
        loop_code = (
            "def run(ctx, target='.', args=None):\n"
            "    n = 0\n"
            "    while n < 40_000_000:\n"
            "        n += 1\n"
            "    return {'items': [n]}\n"
        )
        t_res = run_lens_code_sandboxed(loop_code, ctx=object(), operator_id="hang", timeout_s=0.1)
        assert t_res["ok"] is False
        assert t_res["error"] == "operator_timeout"
        hang_threads = [t for t in threading.enumerate() if t.name == "evolver-op-lens"]
        assert all(t.daemon for t in hang_threads)

        scrubbed = scrub_operator_env(
            {
                "PATH": "/usr/bin",
                "OPENAI_API_KEY": "sk-secret",
                "ANTHROPIC_API_KEY": "sk-ant-secret",
                "EVOMAP_HUB_SECRET": "hub-secret",
                "EVOLVER_RUN_ID": "run_1",
            }
        )
        assert "PATH" in scrubbed
        assert "EVOLVER_RUN_ID" in scrubbed
        assert "OPENAI_API_KEY" not in scrubbed
        assert "ANTHROPIC_API_KEY" not in scrubbed
        assert "EVOMAP_HUB_SECRET" not in scrubbed


class TestS8bAntiCheatAndSolidify:
    def test_detect_anti_cheat_violations_all_four_classes(self, tmp_path: Path) -> None:
        diff_skip = (
            "+++ b/tests/test_calc.py\n+@pytest.mark.skip(reason='flaky')\n+def test_hard():\n"
        )
        assert any(
            v.rule == "anti_cheat_test_skip"
            for v in detect_anti_cheat_violations(
                tmp_path, ["tests/test_calc.py"], diff_text=diff_skip
            )
        )

        diff_del = (
            "+++ b/src/calc.py\n"
            "+def f(): return 1\n"
            "+++ b/tests/test_calc.py\n"
            "-def test_edge_case():\n"
        )
        assert any(
            v.rule == "anti_cheat_deleted_test"
            for v in detect_anti_cheat_violations(
                tmp_path, ["src/calc.py", "tests/test_calc.py"], diff_text=diff_del
            )
        )

        diff_weak = "+++ b/tests/test_calc.py\n-    assert result == 42\n+    assert True\n"
        assert any(
            v.rule == "anti_cheat_weakened_assert"
            for v in detect_anti_cheat_violations(
                tmp_path, ["tests/test_calc.py"], diff_text=diff_weak
            )
        )

        diff_hardcode = "+++ b/src/calc.py\n+if task_id == 'tc-in-hid-1':\n+    return {'a': 1}\n"
        assert any(
            v.rule == "anti_cheat_hardcoded_lookup" and v.severity == "critical"
            for v in detect_anti_cheat_violations(
                tmp_path, ["src/calc.py"], diff_text=diff_hardcode
            )
        )

        legit_guard = "+++ b/src/calc.py\n+if reason == 'unmeasured': return None\n"
        legit_hits = detect_anti_cheat_violations(tmp_path, ["src/calc.py"], diff_text=legit_guard)
        assert all(v.severity != "critical" for v in legit_hits)

        clean_diff = "+++ b/src/calc.py\n+if x is None:\n+    return {}\n"
        assert detect_anti_cheat_violations(tmp_path, ["src/calc.py"], diff_text=clean_diff) == []

    def test_solidify_blocks_anti_cheat_as_draft_preserved(self, isolated_op_ws: Path) -> None:
        def _git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=isolated_op_ws, check=True, capture_output=True, text=True
            )

        _git("init")
        _git("config", "user.email", "test@test.com")
        _git("config", "user.name", "Test")
        (isolated_op_ws / "src").mkdir(exist_ok=True)
        (isolated_op_ws / "tests").mkdir(exist_ok=True)
        (isolated_op_ws / "src" / "app.py").write_text(
            "def run():\n    return 1\n", encoding="utf-8"
        )
        (isolated_op_ws / "tests" / "test_app.py").write_text(
            "def test_run():\n    assert 1 == 1\n", encoding="utf-8"
        )
        _git("add", "-A")
        _git("-c", "commit.gpgsign=false", "commit", "-m", "init")

        upsert_gene(
            {
                "type": "Gene",
                "id": "gene_ac_test",
                "category": "repair",
                "signals_match": ["test"],
                "strategy": ["fix app"],
                "validation": [],
            }
        )
        from evolver.gep import hypothesis as hypothesis_mod

        hypothesis_mod.record_hypothesis(
            {
                "hypothesis": "Fix app.py return value while keeping real test assertions",
                "dimension": "content",
                "mechanism_family": "bugfix",
                "target_hook": "src/app.py",
                "mechanism_check": [
                    {
                        "id": "train-0",
                        "before": "run() returned 1",
                        "after": "run() returns 2 without skipping tests",
                    }
                ],
            }
        )
        write_state_for_solidify(
            {
                "run_id": "run_ac_1",
                "selected_gene_id": "gene_ac_test",
                "signals": ["test"],
                "mutation": {
                    "type": "Mutation",
                    "id": "mut_ac_1",
                    "category": "repair",
                    "validation": [],
                },
            }
        )

        # Introduce cheat: skip test while altering src/app.py
        (isolated_op_ws / "src" / "app.py").write_text(
            "def run():\n    return 2\n", encoding="utf-8"
        )
        (isolated_op_ws / "tests" / "test_app.py").write_text(
            "import pytest\n\n"
            "@pytest.mark.skip(reason='bypass')\n"
            "def test_run():\n"
            "    assert 1 == 1\n",
            encoding="utf-8",
        )
        res = solidify()
        assert res["ok"] is False
        assert res["error"] == "anti_cheat_violation"
        assert res["outcome"] == "draft_preserved"
        assert res["failure_mode"]["mode"] == "soft"


class TestP22OperatorSynthesizer:
    def test_synthesize_operator_from_helped_fix_and_dedup_second_clone(
        self, isolated_op_ws: Path
    ) -> None:
        diff_guard = "+++ b/src/cfg.py\n+if not isinstance(raw, dict):\n+    return {}\n"
        # Skipped on confounded attribution
        conf = synthesize_operator_from_fix(
            cwd=isolated_op_ws,
            run_id="r0",
            signals=["TypeError"],
            diff_text=diff_guard,
            attribution={"status": "confounded"},
            validation_ok=True,
        )
        assert conf["skipped"] is True and "confounded" in conf["reason"]

        # Skipped on anti-cheat diff
        cheat = synthesize_operator_from_fix(
            cwd=isolated_op_ws,
            run_id="r_ac",
            signals=["TypeError"],
            diff_text="+++ b/tests/test_cfg.py\n+@pytest.mark.skip('nope')\n",
            attribution={"status": "helped"},
            validation_ok=True,
        )
        assert cheat["skipped"] is True and cheat["reason"] == "anti_cheat_blocked"

        # Synthesized on clean helped fix
        syn1 = synthesize_operator_from_fix(
            cwd=isolated_op_ws,
            run_id="r1",
            signals=["TypeError", "json_non_dict"],
            diff_text=diff_guard,
            attribution={"status": "helped", "deltas": {"pass_rate": 0.2}},
            validation_ok=True,
        )
        assert syn1["ok"] is True
        assert syn1["action"] == "synthesized_new"
        gene_count_after_1 = len(load_genes())

        # Second structurally identical synthesis binds slot instead of adding clone
        syn2 = synthesize_operator_from_fix(
            cwd=isolated_op_ws,
            run_id="r2",
            signals=["TypeError", "json_loads_list"],
            diff_text=diff_guard,
            attribution={"status": "helped", "deltas": {"pass_rate": 0.3}},
            validation_ok=True,
        )
        assert syn2["ok"] is True
        assert syn2["action"] == "merged_slot_binding"
        assert len(load_genes()) == gene_count_after_1
