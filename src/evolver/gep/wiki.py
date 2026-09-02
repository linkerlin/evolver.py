"""Wiki knowledge layer (S27) — evidence that is NEVER rolled back.

No Node.js equivalent; evolver.py addition.

Mirrors the wikiskill asymmetric-rollback invariant: skills are hypotheses
(git-rollbackable), knowledge is evidence (append + audit only). The wiki is
its OWN git repository inside ``<EVOLUTION_DIR>/wiki/`` — solidify rollbacks
(stash/reset on the workspace) can never touch it.

The code only owns the skeleton and the audit trail; content is written by
the evolution pipeline (solidify verdicts, distill, reflection). Git here is
an audit trail, not a version-control feature: every change is recorded,
nothing is ever reverted.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_evolution_dir

WIKI_README = """# Evolution Wiki

Persistent knowledge layer. **Never rolled back** — skills are hypotheses,
this directory is evidence. Every change lands an audit commit.
"""

WIKI_INDEX = """# Pattern Index

Human-readable projection of what the evolution loop has learned.
Maintained by the distill/reflection pipeline; one page per pattern.
"""

WIKI_LOG = """# Decision Log

Append-only: one line per accepted mutation / gate outcome.
"""

WIKI_SKILL_IMPACT = """# Skill Impact — Rejected & Non-Improving Mutations

Full record of proposals that failed validation, were rejected by the
acceptance gate, or measured no improvement over r_best. Future mutations
MUST NOT repeat these fingerprints.
"""


def wiki_dir() -> Path:
    return get_evolution_dir() / "wiki"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )


def _ensure_parent_ignores_wiki() -> None:
    """S27 review fix: if the wiki lives INSIDE a git-tracked workspace, the
    parent repo must not track it — a parent auto-commit + reset --hard would
    roll back "never-rolled-back" knowledge. Idempotent best-effort append to
    the parent's .gitignore."""
    try:
        from evolver.gep.git_ops import is_git_repo
        from evolver.gep.paths import get_workspace_root

        root = get_workspace_root()
        if not is_git_repo(root):
            return
        rel = wiki_dir().resolve().relative_to(root.resolve()).as_posix()
        marker = f"{rel}/"
        gitignore = root / ".gitignore"
        existing = (
            gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.exists() else ""
        )
        if marker in existing:
            return
        with gitignore.open("a", encoding="utf-8") as f:
            f.write(f"\n# evolver: wiki knowledge layer — never rolled back (S27)\n{marker}\n")
    except Exception:
        pass


def ensure() -> Path:
    """Create the wiki skeleton + its own git repo (idempotent)."""
    d = wiki_dir()
    (d / "patterns").mkdir(parents=True, exist_ok=True)
    files = {
        "README.md": WIKI_README,
        "index.md": WIKI_INDEX,
        "log.md": WIKI_LOG,
        "skill-impact.md": WIKI_SKILL_IMPACT,
    }
    created = False
    for name, content in files.items():
        path = d / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created = True
    git_dir = d / ".git"
    if not git_dir.exists():
        _git(d, "init")
        _git(d, "config", "user.email", "evolver@local")
        _git(d, "config", "user.name", "evolver")
        created = True
    if created:
        _git(d, "add", "-A")
        _git(d, "-c", "commit.gpgsign=false", "commit", "-m", "wiki: skeleton", "--allow-empty")
    _ensure_parent_ignores_wiki()
    return d


def commit(message: str) -> None:
    """Audit commit: knowledge is never rolled back, but every change is
    recorded. Best-effort — wiki failures must never break solidify."""
    try:
        d = ensure()
        _git(d, "add", "-A")
        _git(d, "-c", "commit.gpgsign=false", "commit", "-m", message, "--allow-empty")
    except OSError:
        pass


def _append(path: Path, text: str) -> None:
    ensure()
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def _ts() -> str:
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z"
    )


def append_log(entry: str) -> None:
    """One-line decision-log entry (accepted mutations, gate outcomes)."""
    _append(wiki_dir() / "log.md", f"- [{_ts()}] {entry}\n")
    commit("wiki: log entry")


def append_skill_impact(heading: str, body: str, metadata: dict[str, Any] | None = None) -> None:
    """Full record of a rejected / non-improving mutation, so future
    mutations do not repeat it (wikiskill skill-impact.md contract)."""
    lines = [f"## {_ts()} — {heading}", ""]
    if metadata:
        lines += [f"- {k}: {v}" for k, v in metadata.items()]
        lines.append("")
    lines += [body.strip(), ""]
    _append(wiki_dir() / "skill-impact.md", "\n".join(lines))
    commit("wiki: skill-impact entry")


__all__ = [
    "append_log",
    "append_skill_impact",
    "commit",
    "ensure",
    "wiki_dir",
]
