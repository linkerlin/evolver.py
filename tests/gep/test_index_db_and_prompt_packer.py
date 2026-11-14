"""Tests for P1-4: unified WAL index.sqlite + utility-aware prompt packer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep import episode_record
from evolver.gep.index_db import (
    index_db_path,
    index_summary,
    query_attribution_summary,
    query_operator_stats,
    query_top_signals,
    sync_index_db,
)
from evolver.gep.prompt import (
    PROMPT_TOKEN_BUDGET,
    PromptSection,
    build_gep_prompt,
    estimate_tokens,
    pack_prompt_sections,
)


class TestUnifiedIndexDb:
    def test_wal_mode_incremental_idempotent_sync_and_queries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = tmp_path / "repo"
        ws.mkdir()
        (ws / ".git").mkdir()
        evo_dir = tmp_path / "state" / "evolution"
        gep_dir = tmp_path / "state" / "gep"
        evo_dir.mkdir(parents=True)
        gep_dir.mkdir(parents=True)

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(ws))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
        monkeypatch.setenv("EVOLUTION_DIR", str(evo_dir))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(gep_dir))
        monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))

        events_file = gep_dir / "events.jsonl"
        ev1 = {
            "type": "EvolutionEvent",
            "id": "evt_idx_1",
            "run_id": "run_idx_1",
            "timestamp": "2026-11-13T10:00:00Z",
            "gene_id": "gene_alpha",
            "signals": ["ImportError:foo", "test_failure"],
            "outcome": {"status": "success", "score": 1.0},
        }
        ev2 = {
            "type": "EvolutionEvent",
            "id": "evt_idx_2",
            "run_id": "run_idx_2",
            "timestamp": "2026-11-13T10:05:00Z",
            "gene_id": "gene_beta",
            "signals": ["ImportError:bar"],
            "outcome": {"status": "failed", "score": 0.0},
        }
        events_file.write_text(
            json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n",
            encoding="utf-8",
        )
        (evo_dir / "daily_budget.json").write_text(
            json.dumps({"date": "2026-11-13", "used": 2, "cap": 20}),
            encoding="utf-8",
        )

        # Record one real boundary episode (via episode_record test entry)
        ep_body = episode_record.build_episode(
            {
                "event": {
                    **ev1,
                    "mutation": {"id": "mut_1", "category": "repair"},
                    "diff_snapshot": "--- a/x.py\n+++ b/x.py\n+fixed\n",
                },
                "validation_result": {"ok": True, "results": [{"command": "pytest", "ok": True}]},
                "fitness_verdict": None,
                "gate": {"accepted": True, "reason": "improved"},
            }
        )
        episode_record.record_episode(ep_body)

        first = sync_index_db(repo_root=ws)
        assert first["ok"] is True
        assert first["journal_mode"] == "wal"
        assert first["new_events"] == 2
        assert first["new_episodes"] == 1
        assert index_db_path(ws).is_file()

        # Second sync with no changes is strictly idempotent (zero new rows)
        second = sync_index_db(repo_root=ws)
        assert second["new_events"] == 0
        assert second["new_episodes"] == 0

        sigs = query_top_signals(limit=5, repo_root=ws, auto_sync=False)
        assert sigs[0]["signal"] == "ImportError"
        assert sigs[0]["total_count"] == 2
        assert sigs[0]["success_count"] == 1
        assert sigs[0]["failure_count"] == 1

        ops = {r["gene_id"]: r for r in query_operator_stats(repo_root=ws, auto_sync=False)}
        assert ops["gene_alpha"]["dispatches"] == 1
        assert ops["gene_alpha"]["promoted"] == 1
        assert ops["gene_alpha"]["helped"] == 1
        assert ops["gene_alpha"]["hit_rate"] == 1.0
        assert ops["gene_beta"]["dispatches"] == 1
        assert ops["gene_beta"]["promoted"] == 0
        assert ops["gene_beta"]["failed"] == 1
        assert ops["gene_beta"]["hit_rate"] == 0.0

        # Append one more event and verify incremental byte-cursor picks up ONLY the new line
        ev3 = {
            "type": "EvolutionEvent",
            "id": "evt_idx_3",
            "run_id": "run_idx_3",
            "timestamp": "2026-11-13T10:10:00Z",
            "gene_id": "gene_alpha",
            "signals": ["mypy_error"],
            "outcome": {"status": "success", "score": 1.0},
        }
        with events_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev3) + "\n")

        third = sync_index_db(repo_root=ws)
        assert third["new_events"] == 1
        assert third["new_episodes"] == 0

        ops_after = {r["gene_id"]: r for r in query_operator_stats(repo_root=ws, auto_sync=False)}
        assert ops_after["gene_alpha"]["dispatches"] == 2
        assert ops_after["gene_alpha"]["promoted"] == 2

        attr = query_attribution_summary(repo_root=ws, auto_sync=False)
        assert attr["helped"] == 1
        assert attr["total"] == 1

        summary = index_summary(repo_root=ws, auto_sync=False)
        assert summary["ok"] is True
        assert summary["signals_tracked"] == 3
        assert summary["operators_tracked"] == 2
        assert summary["episodes_indexed"] == 1
        assert summary["daily_budget"] == {"date": "2026-11-13", "used": 2, "cap": 20}

    def test_index_db_is_pure_read_projection(self) -> None:
        src = Path(__file__).resolve().parents[2] / "src" / "evolver" / "gep" / "index_db.py"
        text = src.read_text(encoding="utf-8")
        assert "record_episode(" not in text
        assert "record_round(" not in text
        assert "append_clue(" not in text
        assert 'os.environ.get("EVOLVER_' not in text


class TestUtilityAwarePromptPacker:
    def test_pack_prompt_sections_prefers_high_density_and_never_slices_mid_section(self) -> None:
        sections = [
            PromptSection(name="Header", text="# Header\n", pinned=True),
            PromptSection(
                name="BloatedLowUtility",
                text="## Low\n" + ("noise " * 600) + "\n",
                utility=0.5,
                pinned=False,
            ),
            PromptSection(
                name="CompactHighUtility",
                text='## High\n```json\n[{"id": "op_precise"}]\n```\n',
                utility=5.0,
                pinned=False,
            ),
            PromptSection(name="Task", text="## Task\nEmit valid JSON.", pinned=True),
        ]
        packed, omitted = pack_prompt_sections(sections, max_tokens=200)
        assert "## High" in packed
        assert '[{"id": "op_precise"}]' in packed
        assert "## Low" not in packed
        assert omitted == ["BloatedLowUtility"]
        assert "prompt_packer: omitted 1 low-utility section(s)" in packed
        assert packed.endswith("## Task\nEmit valid JSON.")
        assert "...[TRUNCATED]..." not in packed

    def test_build_gep_prompt_stays_under_4000_tokens_under_heavy_bloat(self) -> None:
        bloated_external = "\n".join(
            f"- unrelated external candidate {i}: " + ("x" * 120) for i in range(120)
        )
        bloated_hub = "\n".join(f"- hub item {i}: " + ("y" * 120) for i in range(120))
        relevant_genes = json.dumps(
            [
                {
                    "id": "gene_importerror_guard",
                    "category": "repair",
                    "signals_match": ["ImportError"],
                    "summary": "Resolve circular ImportError via lazy import",
                }
            ],
            indent=2,
        )

        prompt = build_gep_prompt(
            now_iso="2026-11-13T12:00:00Z",
            context="line\n" * 1000,
            signals=["ImportError"],
            selector={"selectedBy": "score_ranked"},
            parent_event_id="evt_prev",
            selected_gene={
                "id": "gene_importerror_guard",
                "category": "repair",
                "summary": "Resolve circular ImportError",
                "strategy": ["Inspect import_impact lens"],
            },
            capsule_candidates="(none)",
            genes_preview=f"```json\n{relevant_genes}\n```",
            capsules_preview="[]",
            capability_candidates_preview=bloated_external,
            external_candidates_preview=bloated_external,
            hub_matched_block=bloated_hub,
            cycle_id="0099",
            recent_history="recentImportError fix worked",
            failed_capsules=[],
            hub_lessons=[{"lesson": "z" * 4000}],
            strategy_policy=None,
            initial_user_prompt=None,
            episode_block="## Previous Episode\n- outcome: draft_preserved",
            evidence_pack="## Evidence Pack\n- [failed] evt_1 | validation_failed",
            clue_block="## Host Clues\n- [host_working] checked circular import",
        )

        tokens = estimate_tokens(prompt)
        assert tokens <= PROMPT_TOKEN_BUDGET < 4_000, f"expected < 4000 tokens, got {tokens}"
        assert "...[TRUNCATED]..." not in prompt

        # Mandatory sections and canonical ordering strictly preserved
        idx_ep = prompt.index("## Previous Episode")
        idx_ev = prompt.index("## Evidence Pack")
        idx_cl = prompt.index("## Host Clues")
        idx_sg = prompt.index("## Selected Gene")
        idx_tk = prompt.index("## Task")
        assert idx_ep < idx_ev < idx_cl < idx_sg < idx_tk

        # High-utility signal-matched Gene Preview survived whole, with valid JSON fence
        assert "## Gene Preview" in prompt
        assert "gene_importerror_guard" in prompt
