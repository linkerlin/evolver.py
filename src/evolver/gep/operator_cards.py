"""Dynamic Operator Cards with fact/narrative separation & session delta dedup (S-4).

Adapts Strategist's ``cards.py`` and ``search.py::dedupe_cards`` while strictly
honoring evolver.py's record-layering and ``val_seal`` invariants:
- ``Measured (engine)`` is populated strictly from ``index_db`` / ``episode_index``
  telemetry (never fabricated by host notes).
- ``Experience notes`` filters out generic one-word filler (``good``, ``fast``).
- Every rendered card passes through ``val_seal.redact(..., where="dispatch")``.
- ``dedupe_seen_cards`` collapses unchanged cards in an active session to a
  1-line pointer and emits only fresh lines when a card grew slightly.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Any, Final

from evolver.gep.val_seal import redact

_MIN_CONCRETE_NOTE_CHARS: Final[int] = 16
_GENERIC_FILLER_RE: Final = re.compile(
    r"^(?:good|great|nice|fast|ok|fine|worked|worked well|looks good|lgtm)[.!]?$",
    re.IGNORECASE,
)
_VAGUE_ADVICE_RE: Final = re.compile(
    r"\b(?:always\s+be\s+careful|check\s+edge\s+cases|be\s+thorough|test\s+carefully|write\s+clean\s+code)\b",
    re.IGNORECASE,
)
_CONCRETE_ANCHOR_RE: Final = re.compile(r"(?:[`_./\\()]|\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b|\d)")


def is_concrete_experience_note(observation: str, recommendation: str = "") -> bool:
    """Return True when note carries substantive signal rather than generic filler."""
    obs = " ".join((observation or "").split()).strip()
    rec = " ".join((recommendation or "").split()).strip()
    if not obs or len(obs) < _MIN_CONCRETE_NOTE_CHARS or _GENERIC_FILLER_RE.match(obs):
        return False
    if _VAGUE_ADVICE_RE.search(obs) and not _CONCRETE_ANCHOR_RE.search(obs):
        return False
    return not (rec and _GENERIC_FILLER_RE.match(rec))


def _format_slots(gene: Mapping[str, Any]) -> str:
    specs = gene.get("slot_specs") or []
    if not isinstance(specs, list) or not specs:
        return "(none)"
    parts: list[str] = []
    for s in specs[:4]:
        if not isinstance(s, Mapping):
            continue
        sid = str(s.get("id") or "?")
        default_preview = " ".join(str(s.get("default") or "").split())[:28]
        ph = s.get("placeholders") or []
        ph_txt = f", keep {{{', '.join(str(p) for p in ph)}}}" if ph else ""
        parts.append(f"`{sid}` ({default_preview!r}{ph_txt})")
    return ", ".join(parts) or "(none)"


def _format_measured_line(stats: Mapping[str, Any] | None) -> str:
    if not isinstance(stats, Mapping):
        return "dispatches=0 | helped=0 | hurt=0 | confounded=0 | avg_ms=n/a"
    disp = int(stats.get("dispatches") or 0)
    helped = int(stats.get("helped") or 0)
    hurt = int(stats.get("hurt") or 0)
    confounded = int(stats.get("confounded") or 0)
    avg_ms = stats.get("avg_wall_ms")
    avg_txt = f"{float(avg_ms):.0f}ms" if isinstance(avg_ms, (int, float)) else "n/a"
    rate = f" ({helped / disp:.0%})" if disp > 0 else ""
    return (
        f"dispatches={disp} | helped={helped}{rate} | "
        f"hurt={hurt} | confounded={confounded} | avg_ms={avg_txt}"
    )


def _format_experience_notes(gene: Mapping[str, Any], max_notes: int = 3) -> list[str]:
    notes: list[str] = []
    for lh in reversed(gene.get("learning_history") or []):
        if not isinstance(lh, Mapping):
            continue
        outcome = str(lh.get("outcome") or "unknown")
        sigs = ", ".join(str(s) for s in (lh.get("signals") or [])[:4])
        obs = str(lh.get("observation") or f"outcome={outcome} on [{sigs}]").strip()
        rec = str(lh.get("recommendation") or "").strip()
        if not is_concrete_experience_note(obs, rec):
            continue
        line = f"  - {obs[:110]}" + (f" -> {rec[:70]}" if rec else "")
        notes.append(line)
        if len(notes) >= max_notes:
            break
    for ap in reversed(gene.get("anti_patterns") or []):
        if len(notes) >= max_notes:
            break
        if isinstance(ap, Mapping):
            rc = str(ap.get("reasonClass") or "failure")
            sigs = ", ".join(str(s) for s in (ap.get("signals") or [])[:3])
            notes.append(f"  - [avoid] {rc}: {sigs}"[:140])
        elif isinstance(ap, str) and len(ap.strip()) >= 4:
            notes.append(f"  - [avoid] {ap.strip()[:120]}")
    return notes


def render_operator_card(
    gene: Mapping[str, Any],
    stats: Mapping[str, Any] | None = None,
    *,
    max_notes: int = 3,
) -> str:
    """Render a compact, val-sealed Operator Card separating facts from narrative."""
    gid = str(gene.get("id") or "unknown")
    kind = str(gene.get("operator_kind") or ("executable" if gene.get("lens") else "guidance"))
    category = str(gene.get("category") or "unknown")
    deps = [
        str(d) for d in (gene.get("builds_on") or gene.get("dependencies") or []) if str(d).strip()
    ]
    deps_txt = ", ".join(deps) if deps else "none"
    when = str(gene.get("when_to_use") or gene.get("summary") or "(no guidance)").strip()[:160]

    lines = [
        f"### `{gid}` (kind: {kind} | category: {category} | builds_on: {deps_txt})",
        f"- **When to use**: {when}",
        f"- **Slots**: {_format_slots(gene)}",
        f"- **Measured (engine)**: {_format_measured_line(stats)}",
    ]
    notes = _format_experience_notes(gene, max_notes=max_notes)
    if notes:
        lines.append("- **Experience notes**:")
        lines.extend(notes)
    else:
        lines.append("- **Experience notes**: (none yet)")

    raw = "\n".join(lines)
    clean, _ = redact(raw, where="dispatch")
    return clean


def dedupe_seen_cards(
    cards: Mapping[str, str],
    seen: Mapping[str, str],
) -> tuple[str, dict[str, str]]:
    """Deduplicate rendered cards against *seen* session snapshots.

    Returns ``(rendered_markdown, updated_seen_map)``.
    """
    if not cards:
        return "", dict(seen)
    updated_seen = dict(seen)
    parts: list[str] = []
    for name, body in cards.items():
        old = seen.get(name)
        updated_seen[name] = body
        if old is None:
            parts.append(body)
            continue
        if body == old:
            parts.append(f"### `{name}`\n(card unchanged since earlier in this session)")
            continue
        old_lines = set(old.splitlines())
        cur_lines = [ln for ln in body.splitlines() if ln.strip() and not ln.startswith("### ")]
        fresh = [ln for ln in cur_lines if ln not in old_lines]
        if 0 < len(fresh) <= max(1, len(cur_lines) // 2):
            parts.append(f"### `{name}`\n(card updated; new lines only:)\n" + "\n".join(fresh))
        else:
            parts.append(body)
    return "\n\n---\n\n".join(parts), updated_seen


def audit_cards_read_before_compose(
    builds_on: Sequence[str],
    seen_cards: AbstractSet[str],
) -> list[str]:
    """Warn if a composed proposal wraps an operator whose card has not been read."""
    missing = [str(dep) for dep in builds_on if str(dep).strip() and str(dep) not in seen_cards]
    if not missing:
        return []
    return [
        f"read-card-before-compose: call `run_lens(name='card', target='{','.join(missing)}')` "
        f"before composing on {missing}"
    ]


def _load_seen_cards_from_state() -> dict[str, str]:
    from evolver.gep.paths import get_evolution_dir

    path = get_evolution_dir() / "swarm_state.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        seen = data.get("seen_cards") if isinstance(data, dict) else None
        return {str(k): str(v) for k, v in seen.items()} if isinstance(seen, dict) else {}
    except Exception:
        return {}


def _save_seen_cards_to_state(seen: Mapping[str, str]) -> None:
    from evolver.gep.asset_store import atomic_write_json
    from evolver.gep.paths import get_evolution_dir

    path = get_evolution_dir() / "swarm_state.json"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    data["seen_cards"] = dict(seen)
    atomic_write_json(path, data)


def render_cards_for_lens(
    target: str = ".",
    args: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Read-only handler for ``run_lens(name='card', target='op_id_or_csv')``."""
    from evolver.gep.asset_store import load_genes
    from evolver.gep.index_db import query_operator_stats

    extra = dict(args or {})
    raw_names = extra.get("names")
    requested: list[str] = []
    if isinstance(raw_names, list):
        requested.extend(str(n).strip() for n in raw_names if str(n).strip())
    elif target and target != ".":
        requested.extend(part.strip() for part in str(target).split(",") if part.strip())

    genes = [g for g in load_genes() if isinstance(g, dict) and g.get("id")]
    by_id = {str(g["id"]): g for g in genes}

    if not requested:
        # Default to all executable/operator genes, else top 5 genes
        requested = [
            str(g["id"])
            for g in genes
            if g.get("lens") is not None or g.get("operator_kind") is not None
        ][:6] or [str(g["id"]) for g in genes[:5]]

    stats_rows: dict[str, dict[str, Any]] = {}
    try:
        for row in query_operator_stats(limit=100, repo_root=repo_root, auto_sync=False):
            gid = str(row.get("gene_id") or "")
            if gid:
                stats_rows[gid] = row
    except Exception:
        stats_rows = {}

    cards_map: dict[str, str] = {}
    missing: list[str] = []
    for name in requested[:10]:
        gene = by_id.get(name)
        if gene is None:
            missing.append(name)
            continue
        cards_map[name] = render_operator_card(gene, stats_rows.get(name))

    seen = _load_seen_cards_from_state()
    if extra.get("dedupe", True):
        rendered_block, updated_seen = dedupe_seen_cards(cards_map, seen)
    else:
        rendered_block = "\n\n---\n\n".join(cards_map.values())
        updated_seen = {**seen, **cards_map}

    if extra.get("mark_seen", True) and cards_map:
        with contextlib.suppress(Exception):
            _save_seen_cards_to_state(updated_seen)

    return {
        "summary": (
            f"Rendered {len(cards_map)} operator card(s)"
            + (f" ({len(missing)} not found: {', '.join(missing)})" if missing else "")
            + "."
        ),
        "cards_markdown": rendered_block,
        "card_ids": list(cards_map.keys()),
        "missing_ids": missing,
        "items": [{"id": cid, "card": txt} for cid, txt in cards_map.items()],
    }


__all__ = [
    "audit_cards_read_before_compose",
    "dedupe_seen_cards",
    "is_concrete_experience_note",
    "render_cards_for_lens",
    "render_operator_card",
]
