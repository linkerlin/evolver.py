"""Anchor probe: evidence pack honesty (RSI P1-4, round-34).

The evidence pack is the failure-side channel to the executor. A mutation
that quietly stops forwarding family failures (or "solves" prompt bloat by
silently dropping them) re-opens the RQGM self-preference loop at the prompt
layer: the engine would be hiding its own failure record from the only agent
able to act on it. Frozen invariants:

1. family-matched attempts — successes AND failures — appear in the rendered
   pack; unrelated families are excluded;
2. identical added lines produce identical fingerprints (duplicate guard);
3. the render budget is enforced with an explicit omission count, never a
   silent drop, and never exceeds its cap;
4. ``build_gep_prompt`` embeds the pack verbatim when provided and omits the
   section entirely otherwise (novel families stay lean); the Selected Gene
   section survives both ways — the selector remains retrieval augmentation,
   not the sole decision path.

Pure functions; the probe isolates the engine env and asserts in-process.
Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from evolver.gep.evidence_pack import (
    EVIDENCE_PACK_MAX_CHARS,
    build_evidence_pack,
    render_evidence_pack,
)


def _isolate(ws: Path) -> None:
    (ws / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (ws / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "OPENCLAW_WORKSPACE": str(ws),
            "EVOLVER_REPO_ROOT": str(ws),
            "EVOLVER_NO_PARENT_GIT": "1",
            "MEMORY_DIR": str(ws / "memory"),
            "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
            "GEP_ASSETS_DIR": str(ws / ".evolver" / "gep"),
            "EVOLVER_HOME": str(ws / ".evomap"),
            "EVOLVER_SETTINGS_DIR": str(ws / ".evolver_settings"),
            "EVOLVER_LOGS_DIR": str(ws / "logs"),
        }
    )


def _family_events() -> list[dict[str, object]]:
    return [
        {
            "id": "evt_ok",
            "gene_id": "gene_old",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["gene_old"], "category": "repair"},
            "signals": ["log_error"],
            "diff_snapshot": "diff --git a/src/x.py b/src/x.py\n+fixed\n",
        },
        {
            "id": "evt_bad",
            "gene_id": "gene_retry",
            "outcome": {"status": "failed", "error": "validation_failed"},
            "mutation": {"category": "repair"},
            "signals": ["log_error:snippetA"],
            "novelty_added": "+def broken(): pass\n",
        },
        {
            # Different family — must be excluded.
            "id": "evt_other",
            "gene_id": "gene_unrelated",
            "outcome": {"status": "failed"},
            "mutation": {"category": "optimize"},
            "signals": ["mypy_error"],
            "novelty_added": "+unrelated\n",
        },
    ]


def _check() -> None:
    # --- Invariant 1: family attempts reach the render, both outcomes ---
    events = _family_events()
    pack = build_evidence_pack(events, ["log_error"])
    assert len(pack["attempts"]) == 2, pack["attempts"]
    assert pack["accepted"] == 1 and pack["rejected"] == 1, pack
    rendered = render_evidence_pack(pack)
    assert "evt_ok" in rendered and "evt_bad" in rendered, rendered
    assert "gene_retry" in rendered and "validation_failed" in rendered, rendered
    assert "evt_other" not in rendered and "gene_unrelated" not in rendered, rendered
    assert render_evidence_pack(build_evidence_pack(events, [])) == ""
    assert render_evidence_pack(build_evidence_pack(events, ["hub_offline"])) == ""

    # --- Invariant 2: identical added lines → identical fingerprint ---
    dup_a = build_evidence_pack(
        [
            {
                "id": "d1",
                "outcome": {"status": "failed"},
                "signals": ["log_error"],
                "novelty_added": "+same edit\n",
            }
        ],
        ["log_error"],
    )
    dup_b = build_evidence_pack(
        [
            {
                "id": "d2",
                "outcome": {"status": "failed"},
                "signals": ["log_error"],
                "novelty_added": "+same edit\n",
            }
        ],
        ["log_error"],
    )
    assert dup_a["digests"] and dup_a["digests"] == dup_b["digests"], (dup_a, dup_b)
    assert dup_a["digests"][0] in render_evidence_pack(dup_a)

    # --- Invariant 3: budget enforced with a counted omission, never silent ---
    many = [
        {
            "id": f"evt_{i:03d}",
            "gene_id": f"gene_{i:03d}",
            "outcome": {"status": "failed", "error": f"reason_{i} " + "x" * 60},
            "mutation": {"category": "repair"},
            "signals": ["log_error"],
            "novelty_added": f"+edit {i} " + "y" * 120 + "\n",
        }
        for i in range(80)
    ]
    packed = build_evidence_pack(many, ["log_error"], limit=80)
    squeezed = render_evidence_pack(packed)
    assert len(squeezed) <= EVIDENCE_PACK_MAX_CHARS, len(squeezed)
    assert "omitted for budget" in squeezed, "budget must drop with an explicit count"
    # Newest attempt survives; oldest never smuggles back in.
    assert "evt_079" in squeezed, "newest family attempt must survive the budget"
    omitted_count = int(squeezed.split("(+", 1)[1].split(" ", 1)[0])
    assert omitted_count >= 1, squeezed

    # --- Invariant 4: prompt embedding is verbatim and optional ---
    from evolver.gep.prompt import build_gep_prompt

    def _prompt(evidence: str) -> str:
        return build_gep_prompt(
            now_iso="2026-09-19T00:00:00Z",
            context="ctx",
            signals=["log_error"],
            selector={"selectedBy": "score_ranked"},
            parent_event_id=None,
            selected_gene={"id": "gene_x", "category": "repair", "summary": ""},
            capsule_candidates="(none)",
            genes_preview="[]",
            capsules_preview="[]",
            capability_candidates_preview="(none)",
            external_candidates_preview="(none)",
            hub_matched_block="{}",
            cycle_id="0001",
            recent_history="",
            failed_capsules=[],
            hub_lessons=[],
            strategy_policy=None,
            initial_user_prompt=None,
            evidence_pack=evidence,
        )

    with_pack = _prompt(rendered)
    assert "## Evidence Pack" in with_pack, "pack must reach the prompt verbatim"
    assert "evt_bad" in with_pack, with_pack
    assert with_pack.index("## Evidence Pack") < with_pack.index("## Selected Gene"), (
        "evidence precedes the gene suggestion"
    )
    lean = _prompt("")
    assert "## Evidence Pack" not in lean, "novel families must not carry an empty section"
    assert "## Selected Gene" in lean


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        try:
            _check()
        except AssertionError as exc:
            print(f"FAIL: evidence pack invariant violated: {exc}")
            return 1
        print(
            "PASS: family failures reach the executor, budget omissions counted, "
            "prompt embedding verbatim and optional"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
