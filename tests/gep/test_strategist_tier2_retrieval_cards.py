"""Strategist Tier 2 tests: S-3 dual-view retrieval, S-4 cards & dedup, S-7 delta & mirror."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate
from evolver.gep import blackbox, val_seal
from evolver.gep.asset_store import upsert_gene
from evolver.gep.hybrid_retrieval import (
    compute_idf_weights,
    retrieve_operators_and_inspiration,
)
from evolver.gep.lenses import run_lens
from evolver.gep.multi_proposer import (
    MultiProposerRequest,
    Proposal,
    build_slot_repair_prompt,
    generate_multi_proposals,
    merge_proposal_patch,
)
from evolver.gep.operator_cards import (
    audit_cards_read_before_compose,
    dedupe_seen_cards,
    is_concrete_experience_note,
    render_operator_card,
)
from evolver.gep.prompt import PROMPT_TOKEN_BUDGET, build_gep_prompt


@pytest.fixture
def isolated_tier2_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


class TestS3DualViewHybridRetrieval:
    def test_idf_rare_token_boost_and_cross_family_inspiration(
        self, isolated_tier2_ws: Path
    ) -> None:
        idf = compute_idf_weights(
            {
                "g1": "error ZeroDivisionError clamp denominator",
                "g2": "error generic retry",
                "g3": "error generic log",
                "g4": "error generic parse",
            }
        )
        assert idf["zerodivisionerror"] > idf["error"]

        genes: list[dict[str, Any]] = [
            {
                "id": f"op_err_{i}",
                "category": "repair",
                "signals_match": ["error", "exception"],
                "summary": f"Generic error handler {i}",
                "strategy": ["Handle generic error safely"],
            }
            for i in range(6)
        ]
        genes.append(
            {
                "id": "op_rare_div0",
                "category": "repair",
                "signals_match": ["ZeroDivisionError", "error"],
                "summary": "Clamp denominator before division",
                "when_to_use": "Use on ZeroDivisionError / float division",
                "strategy": ["Guard denominator against zero"],
                "lens": "def run(ctx, target='.', args=None): return {'items': []}",
            }
        )
        genes.extend(
            [
                {
                    "id": "op_cross_path",
                    "category": "repair",
                    "signals_match": ["windows_path", "error"],
                    "summary": "Normalize Windows backslashes before relative prefix strip",
                    "lens": "def run(ctx, target='.', args=None): return {'items': []}",
                },
                {
                    "id": "op_cross_sqlite",
                    "category": "harden",
                    "signals_match": ["sqlite_lock", "resource_leak"],
                    "summary": "Wrap sqlite3 connections in contextlib.closing",
                    "lens": "def run(ctx, target='.', args=None): return {'items': []}",
                },
            ]
        )

        cache_file = isolated_tier2_ws / "vec_cache.json"
        res1 = retrieve_operators_and_inspiration(
            genes,
            ["ZeroDivisionError", "error"],
            k_relevant=3,
            k_inspiration=2,
            cache_path=cache_file,
        )
        assert res1["relevant"][0]["id"] == "op_rare_div0"
        rel_ids = {r["id"] for r in res1["relevant"]}
        insp_ids = {r["id"] for r in res1["inspiration"]}
        assert rel_ids.isdisjoint(insp_ids)
        assert cache_file.is_file()

        # Re-read cache + add extra gene on Windows atomic replace
        genes.append(
            {
                "id": "op_cross_timeout",
                "category": "repair",
                "signals_match": ["timeout", "subprocess"],
                "summary": "Enforce explicit timeout on subprocess.run",
                "lens": "def run(ctx, target='.', args=None): return {'items': []}",
            }
        )
        res2 = retrieve_operators_and_inspiration(
            genes,
            ["ZeroDivisionError", "error"],
            k_relevant=3,
            k_inspiration=2,
            cache_path=cache_file,
        )
        assert res2["relevant"][0]["id"] == "op_rare_div0"
        cached_payload = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "op_cross_timeout" in cached_payload


class TestS4OperatorCardsAndDeduplication:
    def test_card_splits_facts_filters_filler_and_redacts_sealed(
        self, isolated_tier2_ws: Path
    ) -> None:
        pack_path = frozen_gate.frozen_pack_path()
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        secret_tok = "SECRET_VAL_TOKEN_987654"
        pack_path.write_text(
            json.dumps(
                {
                    "pack_version": 1,
                    "tasks": [
                        {
                            "id": "val-1",
                            "split": "val",
                            "title": secret_tok,
                            "prompt": "solve",
                            "sandbox": {"in.txt": "payload"},
                            "grader": {"type": "exact", "file": "out.txt", "expected": "ok"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        assert (
            is_concrete_experience_note("Always be careful and check edge cases thoroughly")
            is False
        )
        assert (
            is_concrete_experience_note("Guarding None before json.loads stopped crash in cfg.py")
            is True
        )

        gene = {
            "id": "op_unguarded_subscript",
            "operator_kind": "new",
            "category": "repair",
            "when_to_use": f"Do not touch {secret_tok}",
            "slot_specs": [{"id": "s1", "default": "dict", "placeholders": []}],
            "learning_history": [
                {
                    "outcome": "helped",
                    "observation": "Always be careful and check edge cases thoroughly",
                },
                {
                    "outcome": "helped",
                    "observation": "Checking isinstance(val, dict) fixed TypeError in cfg.py",
                    "recommendation": "Use fallback {} only when config optional",
                },
            ],
        }
        card = render_operator_card(
            gene,
            {
                "dispatches": 12,
                "passes": 9,
                "helped": 5,
                "confounded": 1,
                "harmed": 0,
                "avg_wall_ms": 48.0,
            },
        )
        assert "Measured (engine)" in card
        assert "dispatches=12" in card and "48ms" in card
        assert "Always be careful" not in card
        assert "Checking isinstance(val, dict)" in card
        assert secret_tok not in card
        assert val_seal.REDACTION_PLACEHOLDER in card
        assert "builds_on: none" in card or "op_unguarded_subscript" in card

    def test_dedupe_seen_cards_audit_and_card_lens(self, isolated_tier2_ws: Path) -> None:
        upsert_gene(
            {
                "type": "Gene",
                "id": "op_demo_card",
                "category": "repair",
                "when_to_use": "Inspect edge guard",
                "signals_match": ["edge"],
                "strategy": ["run lens"],
                "lens": "def run(ctx, target='.', args=None): return {'items': []}",
            }
        )
        # audit before compose
        warnings = audit_cards_read_before_compose(["op_demo_card"], set())
        assert len(warnings) == 1 and "run_lens(name='card'" in warnings[0]
        assert audit_cards_read_before_compose(["op_demo_card"], {"op_demo_card"}) == []

        # dedupe_seen_cards behavior on delta update
        card_v1 = "### `op_demo`\n- **When to use**: check\n- **Measured (engine)**: 1 uses"
        card_v2 = "### `op_demo`\n- **When to use**: check\n- **Measured (engine)**: 2 uses"
        out_unchanged, seen1 = dedupe_seen_cards({"op_demo": card_v1}, {"op_demo": card_v1})
        assert "unchanged since earlier" in out_unchanged
        out_delta, _ = dedupe_seen_cards({"op_demo": card_v2}, seen1)
        assert "new lines only" in out_delta and "2 uses" in out_delta

        # run_lens(name="card") persists swarm_state.json seen_cards and compresses on 2nd read
        first = run_lens(name="card", target="op_demo_card", repo_root=isolated_tier2_ws)
        assert first["ok"] is True
        assert "Inspect edge guard" in first["cards_markdown"]

        second = run_lens(name="card", target="op_demo_card", repo_root=isolated_tier2_ws)
        assert second["ok"] is True
        assert "unchanged since earlier" in second["cards_markdown"]


class TestS7DeltaProposerMirrorAndPrompt:
    def test_slot_repair_delta_patch_preserves_other_slots(self) -> None:
        req = MultiProposerRequest(diagnosis_brief="duplicate check", route_count=2)
        p0 = Proposal(
            slot_index=0,
            decision="propose",
            mechanism_family="guard/early-return",
            target_hook="src/a.py",
            rationale="guard None",
        )
        p1_dup = Proposal(
            slot_index=1,
            decision="propose",
            mechanism_family="guard/early-return",
            target_hook="src/a.py",
            rationale="dup",
        )
        prompt = build_slot_repair_prompt(req, [p0, p1_dup], 1, ["duplicate"])
        assert "Do NOT re-send valid slots" in prompt

        patched = merge_proposal_patch(
            [p0],
            json.dumps(
                {
                    "replace_slots": {
                        "1": {
                            "slot_index": 1,
                            "decision": "propose",
                            "mechanism_family": "try/except wrapping",
                            "target_hook": "src/b.py",
                            "rationale": "different mechanism",
                        }
                    }
                }
            ),
            route_count=2,
            target_slot=1,
        )
        assert len(patched) == 2
        assert patched[0].mechanism_family == "guard/early-return"
        assert patched[1].mechanism_family == "try/except wrapping"

        patched_fields = merge_proposal_patch(
            patched,
            json.dumps({"set_fields": {"1": {"rationale": "updated rationale"}}}),
            route_count=2,
            target_slot=1,
        )
        assert patched_fields[1].rationale == "updated rationale"

        # End-to-end duplicate repair through generate_multi_proposals
        calls: list[str] = []

        def fake_llm(p: str) -> str:
            calls.append(p)
            if len(calls) == 1:
                return json.dumps({"proposals": [p0.model_dump(), p1_dup.model_dump()]})
            if len(calls) == 2:
                return json.dumps({"proposals": [p0.model_dump(), p1_dup.model_dump()]})
            return json.dumps(
                {
                    "replace_slots": {
                        "1": {
                            "slot_index": 1,
                            "decision": "propose",
                            "mechanism_family": "import/routing change",
                            "target_hook": "src/b.py",
                            "rationale": "repaired slot only",
                        }
                    }
                }
            )

        res = generate_multi_proposals(req, fake_llm)
        assert len(res) == 2
        assert res[1].mechanism_family == "import/routing change"

    def test_blackbox_classify_mirror_and_prompt_budget(self, isolated_tier2_ws: Path) -> None:
        evo_dir = isolated_tier2_ws / ".evolver" / "evolution"
        mechs = blackbox.classify_patch_mechanisms(
            "+++ b/src/m.py\n+try:\n+    x()\n+except ValueError:\n+    pass\n"
        )
        assert "try/except wrapping" in mechs

        for idx in range(2):
            blackbox.begin_blackbox(
                f"run_bb_{idx}",
                selected_gene_id="gene_a",
                cwd=isolated_tier2_ws,
                evolution_dir=evo_dir,
            )
            blackbox.settle_blackbox(
                isolated_tier2_ws,
                run_id=f"run_bb_{idx}",
                diff_text=(
                    "+++ b/src/m.py\n+try:\n+    x()\n+except ValueError:\n+    return None\n"
                ),
                outcome_ok=False,
                outcome_label="draft_preserved",
                evolution_dir=evo_dir,
            )

        mirror = blackbox.render_mutation_structure_mirror(evo_dir)
        assert "2 try/except wrapping" in mirror
        assert "0 promoted" in mirror

        prompt = build_gep_prompt(
            now_iso="2026-11-16T00:00:00Z",
            context="ctx",
            signals=["TypeError"],
            selector={"selected": "op_demo", "reason": ["match"]},
            parent_event_id=None,
            selected_gene={"id": "op_demo", "category": "repair", "strategy": ["check"]},
            capsule_candidates="",
            genes_preview="",
            capsules_preview="",
            capability_candidates_preview="",
            external_candidates_preview="",
            hub_matched_block="",
            cycle_id="c1",
            recent_history="",
            failed_capsules=[],
            hub_lessons=[],
            strategy_policy=None,
            initial_user_prompt=None,
            operator_cards_block="### `op_demo`\n- **When to use**: check",
            adjacent_inspiration_block="- `op_other`: normalize path",
            structure_mirror_line=mirror,
        )
        assert "## Mutation Structure Mirror" in prompt
        assert "## Operator Cards" in prompt
        assert "## Adjacent Inspiration" in prompt
        assert len(prompt.split()) <= PROMPT_TOKEN_BUDGET
