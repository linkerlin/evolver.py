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
                continue
            raise ValueError(f"patch: file not found: {edit.file}")
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


__all__ = [
    "FORBIDDEN_PREFIXES",
    "GeneProposal",
    "ProposalEdit",
    "apply_proposal",
    "parse_proposal",
]
