"""Gene proposals (S29) — structured mutations with mechanical application.

No Node.js equivalent; evolver.py addition.

Wikiskill lesson: an agent must never edit the target directly. It submits a
proposal JSON; the engine applies it mechanically with hard validation:
anchor text must match exactly (a hallucinated patch raises, it does not
"best-effort"), files cannot escape the workspace, and ``no_action`` is a
first-class outcome.

Proposal format::

    {"action": "patch", "gene_id": "gene_x",
     "edits": [{"op": "replace", "file": "src/mod.py",
                "target": "<exact current text>", "content": "<new text>"}]}

ops: ``append`` (no target) / ``replace`` (target required) / ``insert_after``
(target required). ``create`` writes new files (must not already exist).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORBIDDEN_PREFIXES: tuple[str, ...] = (".git/", ".git\\", ".venv/", "node_modules/", ".evolver/")


class ProposalEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["append", "replace", "insert_after"]
    file: str
    target: str | None = None
    content: str

    @model_validator(mode="after")
    def _target_required_for_anchor_ops(self) -> ProposalEdit:
        if self.op in ("replace", "insert_after") and not self.target:
            raise ValueError(f"op={self.op!r} requires non-empty 'target'")
        if self.op == "append" and self.target:
            raise ValueError("op='append' takes no 'target'")
        return self


class GeneProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["patch", "create", "no_action"]
    gene_id: str | None = None
    note: str | None = None
    edits: list[ProposalEdit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edits_match_action(self) -> GeneProposal:
        if self.action == "no_action" and self.edits:
            raise ValueError("no_action must carry no edits")
        if self.action in ("patch", "create") and not self.edits:
            raise ValueError(f"action={self.action!r} requires at least one edit")
        return self


def _safe_relative(root: Path, rel: str) -> Path:
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ValueError(f"proposal file path rejected: {rel!r}")
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"proposal file escapes workspace: {rel!r}")
    for forbidden in FORBIDDEN_PREFIXES:
        if rel.replace("\\", "/").startswith(forbidden):
            raise ValueError(f"proposal touches forbidden path: {rel!r}")
    return candidate


def apply_proposal(proposal: GeneProposal, root: Path) -> dict[str, Any]:
    """Mechanically apply a proposal. Anchors must match exactly — a miss
    raises :class:`ValueError` and NOTHING is written (validate-all-first,
    then write). Returns a report; never partially applies."""
    if proposal.action == "no_action":
        return {"applied": False, "action": "no_action", "files_changed": []}

    root = root.resolve()
    # Pass 1 — validate everything against the current tree.
    planned: list[tuple[ProposalEdit, Path, str]] = []
    for edit in proposal.edits:
        path = _safe_relative(root, edit.file)
        if proposal.action == "create":
            if path.exists():
                raise ValueError(f"create: file already exists: {edit.file}")
            planned.append((edit, path, ""))
            continue
        if not path.exists():
            if edit.op == "append":
                planned.append((edit, path, ""))  # append may create its file
            else:
                raise ValueError(f"patch: file not found: {edit.file}")
            continue
        text = path.read_text(encoding="utf-8")
        if edit.op in ("replace", "insert_after"):
            count = text.count(edit.target or "")
            if count == 0:
                raise ValueError(
                    f"anchor not found in {edit.file}: {edit.target!r:.120} — "
                    "proposal rejected (hallucinated patch)"
                )
            if count > 1:
                raise ValueError(
                    f"anchor ambiguous in {edit.file} ({count} matches) — "
                    "proposal rejected; anchor must be unique"
                )
        planned.append((edit, path, text))

    # Pass 2 — write sequentially. Same-file edits compose: each edit reads
    # the current on-disk text (possibly just written by an earlier edit).
    # Anchors were unique in pass 1; if a prior edit in this batch disturbed
    # one, fail loudly rather than silently skip.
    files_changed: list[str] = []
    for edit, path, _original in planned:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if proposal.action == "create" or edit.op == "append":
            new_text = current + edit.content
        elif edit.op == "replace":
            if current.count(edit.target or "") != 1:
                raise ValueError(
                    f"anchor no longer unique after earlier edits in {edit.file} — "
                    "proposal aborted mid-batch (workspace may hold partial edits)"
                )
            new_text = current.replace(edit.target or "", edit.content, 1)
        else:  # insert_after
            if current.count(edit.target or "") != 1:
                raise ValueError(
                    f"anchor no longer unique after earlier edits in {edit.file} — "
                    "proposal aborted mid-batch (workspace may hold partial edits)"
                )
            new_text = current.replace(edit.target or "", (edit.target or "") + edit.content, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        if rel not in files_changed:
            files_changed.append(rel)

    return {
        "applied": True,
        "action": proposal.action,
        "gene_id": proposal.gene_id,
        "files_changed": files_changed,
    }


def parse_proposal(data: Any) -> GeneProposal:
    """Parse + validate a proposal from arbitrary JSON data."""
    return GeneProposal.model_validate(data)


def _validate_single_edit_on_buffer(
    root: Path,
    edit: ProposalEdit,
    buffers: dict[str, str],
) -> tuple[bool, str, str]:
    """Check whether *edit* can cleanly apply to the simulated file buffer."""
    try:
        path = _safe_relative(root, edit.file)
    except ValueError as exc:
        return False, "invalid_path", str(exc)

    rel = path.relative_to(root.resolve()).as_posix()
    if rel in buffers:
        current = buffers[rel]
        exists = True
    elif path.exists():
        try:
            current = path.read_text(encoding="utf-8")
            exists = True
        except OSError as exc:
            return False, "unreadable_file", str(exc)
    else:
        current = ""
        exists = False

    if edit.op == "append":
        return True, "ok", current + edit.content

    if not exists:
        return False, "file_not_found", f"file not found: {edit.file}"

    target = edit.target or ""
    count = current.count(target)
    if count == 0:
        return False, "anchor_not_found", f"anchor not found in {edit.file}"
    if count > 1:
        return False, "anchor_ambiguous", f"anchor ambiguous in {edit.file} ({count} matches)"

    if edit.op == "replace":
        updated = current.replace(target, edit.content, 1)
    else:
        updated = current.replace(target, target + edit.content, 1)
    return True, "ok", updated


def compose_proposals(
    candidates: Sequence[dict[str, Any] | GeneProposal],
    *,
    root: Path,
    apply: bool = False,
    gene_id: str | None = None,
) -> dict[str, Any]:
    """Harness2 (§3.2 / Appendix H) Mechanical Selective Composer.

    Selectively merges non-conflicting, evidence-backed edits across multiple
    candidate proposals (such as orthogonal ``INV`` + ``DOM`` proposals or
    salvaged single-component edits across sequential rounds) while enforcing:

    1. **Never merge from non-delivering or hurt/confounded candidates**:
       candidates flagged with ``non_delivering=True`` or
       ``verdict in ("hurt", "confounded")`` have all edits dropped.
    2. **Orthogonal Scope Enforcement**: if a candidate declares ``role``
       (``INV`` or ``DOM``), out-of-scope file edits are dropped.
    3. **Conflict & Anchor Verification**: overlapping ``(file, target)`` edits
       or edits whose anchors fail mechanical validation on *root* are dropped
       without aborting valid orthogonal edits.
    4. **First-class ``KEEP_BASE``**: when no candidate edit is supported,
       returns ``decision="keep_base"`` with ``GeneProposal(action="no_action")``.
    """
    from evolver.gep.record_route import validate_proposal_scope

    resolved_root = root.resolve()
    kept_edits: list[ProposalEdit] = []
    ledger: list[dict[str, Any]] = []
    simulated_buffers: dict[str, str] = {}
    claimed_anchors: dict[tuple[str, str], str] = {}
    inferred_gene_id = gene_id

    for idx, entry in enumerate(candidates, start=1):
        if isinstance(entry, GeneProposal):
            prop = entry
            cand_id = f"cand_{idx}"
            role: str | None = None
            verdict = "helped"
            non_delivering = False
            evidence = "direct_proposal"
        elif isinstance(entry, dict):
            raw_prop = entry.get("proposal", entry)
            try:
                prop = raw_prop if isinstance(raw_prop, GeneProposal) else parse_proposal(raw_prop)
            except Exception as exc:
                ledger.append(
                    {
                        "decision": "dropped",
                        "candidate_id": str(entry.get("candidate_id") or f"cand_{idx}"),
                        "role": entry.get("role"),
                        "file": "*",
                        "op": "invalid",
                        "reason": f"invalid_proposal:{exc}",
                        "evidence": str(entry.get("evidence") or "validation_error"),
                    }
                )
                continue
            cand_id = str(entry.get("candidate_id") or prop.gene_id or f"cand_{idx}")
            role = str(entry["role"]) if entry.get("role") else None
            verdict = str(entry.get("verdict") or "helped").lower()
            non_delivering = bool(entry.get("non_delivering", False))
            evidence = str(entry.get("evidence") or f"verdict={verdict}")
        else:
            continue

        if inferred_gene_id is None and prop.gene_id:
            inferred_gene_id = prop.gene_id

        if prop.action == "no_action":
            ledger.append(
                {
                    "decision": "dropped",
                    "candidate_id": cand_id,
                    "role": role,
                    "file": "-",
                    "op": "no_action",
                    "reason": "candidate_no_action",
                    "evidence": evidence,
                }
            )
            continue

        if non_delivering:
            for ed in prop.edits:
                ledger.append(
                    {
                        "decision": "dropped",
                        "candidate_id": cand_id,
                        "role": role,
                        "file": ed.file,
                        "op": ed.op,
                        "reason": "non_delivering_rollout",
                        "evidence": evidence,
                    }
                )
            continue

        if verdict in ("hurt", "confounded"):
            for ed in prop.edits:
                ledger.append(
                    {
                        "decision": "dropped",
                        "candidate_id": cand_id,
                        "role": role,
                        "file": ed.file,
                        "op": ed.op,
                        "reason": f"verdict_{verdict}",
                        "evidence": evidence,
                    }
                )
            continue

        out_of_scope_set: set[str] = set()
        if role:
            try:
                scope_check = validate_proposal_scope(role, [ed.file for ed in prop.edits])
                out_of_scope_set = set(scope_check["out_of_scope_files"])
            except ValueError:
                out_of_scope_set = set()

        for ed in prop.edits:
            norm_file = ed.file.replace("\\", "/").strip("/")
            if norm_file in out_of_scope_set:
                ledger.append(
                    {
                        "decision": "dropped",
                        "candidate_id": cand_id,
                        "role": role,
                        "file": norm_file,
                        "op": ed.op,
                        "reason": f"out_of_scope_for_{role}",
                        "evidence": evidence,
                    }
                )
                continue

            anchor_key = (norm_file, ed.target or f"__append__:{ed.content}")
            if ed.target and (norm_file, ed.target) in claimed_anchors:
                prev_content = claimed_anchors[(norm_file, ed.target)]
                reason = (
                    "duplicate_identical_edit"
                    if prev_content == ed.content
                    else "conflicting_anchor_edit"
                )
                ledger.append(
                    {
                        "decision": "dropped",
                        "candidate_id": cand_id,
                        "role": role,
                        "file": norm_file,
                        "op": ed.op,
                        "reason": reason,
                        "evidence": evidence,
                    }
                )
                continue

            ok, code, updated_buf = _validate_single_edit_on_buffer(
                resolved_root, ed, simulated_buffers
            )
            if not ok:
                ledger.append(
                    {
                        "decision": "dropped",
                        "candidate_id": cand_id,
                        "role": role,
                        "file": norm_file,
                        "op": ed.op,
                        "reason": code,
                        "evidence": evidence,
                    }
                )
                continue

            simulated_buffers[norm_file] = updated_buf
            if ed.target:
                claimed_anchors[(norm_file, ed.target)] = ed.content
            else:
                claimed_anchors[anchor_key] = ed.content
            kept_edits.append(ed)
            ledger.append(
                {
                    "decision": "kept",
                    "candidate_id": cand_id,
                    "role": role,
                    "file": norm_file,
                    "op": ed.op,
                    "reason": "supported_non_conflicting_edit",
                    "evidence": evidence,
                }
            )

    notes_lines = [
        f"{row['decision']} -> {row['candidate_id']}:{row['file']} ({row['op']}) "
        f"-> {row['reason']} [{row['evidence']}]"
        for row in ledger
    ]
    notes_text = "\n".join(notes_lines) if notes_lines else "keep_base -> no_candidates"

    if not kept_edits:
        composed = GeneProposal(
            action="no_action",
            gene_id=inferred_gene_id,
            note=f"KEEP_BASE: {notes_text}"[:500],
            edits=[],
        )
        apply_report = (
            apply_proposal(composed, resolved_root)
            if apply
            else {"applied": False, "action": "no_action", "files_changed": []}
        )
        return {
            "ok": True,
            "decision": "keep_base",
            "proposal": composed,
            "kept_count": 0,
            "dropped_count": len(ledger),
            "composition_ledger": ledger,
            "notes": notes_text,
            "apply_report": apply_report,
        }

    composed = GeneProposal(
        action="patch",
        gene_id=inferred_gene_id,
        note=f"COMPOSED ({len(kept_edits)} kept): {notes_text}"[:500],
        edits=kept_edits,
    )
    apply_report = (
        apply_proposal(composed, resolved_root)
        if apply
        else {
            "applied": False,
            "action": "patch",
            "files_changed": list(dict.fromkeys(ed.file.replace("\\", "/") for ed in kept_edits)),
        }
    )
    return {
        "ok": True,
        "decision": "composed",
        "proposal": composed,
        "kept_count": len(kept_edits),
        "dropped_count": sum(1 for r in ledger if r["decision"] == "dropped"),
        "composition_ledger": ledger,
        "notes": notes_text,
        "apply_report": apply_report,
    }


__all__ = [
    "FORBIDDEN_PREFIXES",
    "GeneProposal",
    "ProposalEdit",
    "apply_proposal",
    "compose_proposals",
    "parse_proposal",
]
