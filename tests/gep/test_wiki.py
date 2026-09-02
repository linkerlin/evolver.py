"""S27 wiki knowledge layer: evidence never rolls back."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evolver.gep import wiki


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    return proc.stdout or proc.stderr


@pytest.fixture
def evo_dir(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = temp_workspace / "memory" / "evolution"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(d))
    return d


def test_ensure_creates_skeleton_and_own_repo(evo_dir: Path) -> None:
    d = wiki.ensure()
    for name in ("README.md", "index.md", "log.md", "skill-impact.md"):
        assert (d / name).exists(), name
    assert (d / "patterns").is_dir()
    assert (d / ".git").is_dir()  # OWN repo — independent of any workspace
    # idempotent
    assert wiki.ensure() == d


def test_append_log_and_impact_leave_audit_commits(evo_dir: Path) -> None:
    wiki.append_log("accepted: gene=g1 score=1.0")
    wiki.append_skill_impact(
        "validation_failed: g2",
        "rolled back",
        metadata={"gene_id": "g2", "score": 0.5},
    )
    d = wiki.wiki_dir()
    log = (d / "log.md").read_text(encoding="utf-8")
    impact = (d / "skill-impact.md").read_text(encoding="utf-8")
    assert "accepted: gene=g1 score=1.0" in log
    assert "validation_failed: g2" in impact
    assert "gene_id: g2" in impact
    commits = _git(d, "log", "--oneline")
    assert "wiki: log entry" in commits
    assert "wiki: skill-impact entry" in commits


def test_rollback_cannot_touch_wiki(
    evo_dir: Path, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core invariant: workspace rollback (git reset --hard) leaves the
    wiki byte-identical — skills are hypotheses, the wiki is evidence."""
    from evolver.gep.git_ops import rollback_tracked

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    wiki.append_skill_impact("evidence: keep-me", "wiki survives rollbacks")
    before = (wiki.wiki_dir() / "skill-impact.md").read_text(encoding="utf-8")

    # dirty the workspace, then roll it back the way solidify does
    dirty = temp_workspace / "dirty.txt"
    dirty.write_text("mutation\n", encoding="utf-8")
    rollback_tracked(cwd=temp_workspace, include_untracked=False)

    assert dirty.read_text(encoding="utf-8") == "mutation\n" or not dirty.exists()
    assert (wiki.wiki_dir() / "skill-impact.md").read_text(encoding="utf-8") == before


def test_hard_reset_cannot_touch_wiki(
    evo_dir: Path, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even EVOLVER_ROLLBACK_MODE=hard (reset --hard) spares the wiki: it is a
    nested independent repo, and its files are not tracked by the workspace."""
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    wiki.ensure()
    wiki.append_log("before reset")
    before = (wiki.wiki_dir() / "log.md").read_text(encoding="utf-8")

    _git(temp_workspace, "reset", "--hard")  # workspace-level hard reset

    assert (wiki.wiki_dir() / "log.md").read_text(encoding="utf-8") == before


def test_parent_commit_and_reset_cannot_touch_wiki(
    evo_dir: Path, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S27 review fix: the real-world hazard — the parent repo AUTO-COMMITS
    everything (including memory/) and a later reset --hard would roll back
    committed wiki knowledge. ensure() must have added the wiki to the
    parent's .gitignore so the parent can never track it."""
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    # parent is a real git repo (the tracked-memory hazard scenario)
    _git(temp_workspace, "init")
    _git(temp_workspace, "config", "user.email", "t@t")
    _git(temp_workspace, "config", "user.name", "t")
    wiki.ensure()
    wiki.append_log("evidence before parent commit")

    # parent's .gitignore must now exclude the wiki (idempotently)
    gitignore = (temp_workspace / ".gitignore").read_text(encoding="utf-8")
    assert "memory/evolution/wiki/" in gitignore
    wiki.ensure()  # second call does not duplicate the entry
    again = (temp_workspace / ".gitignore").read_text(encoding="utf-8")
    assert again.count("memory/evolution/wiki/") == 1

    # parent commits everything it tracks, then hard-resets
    _git(temp_workspace, "add", "-A")
    _git(
        temp_workspace,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "parent snapshot",
        "--allow-empty",
    )
    before = (wiki.wiki_dir() / "log.md").read_text(encoding="utf-8")
    _git(temp_workspace, "reset", "--hard", "HEAD")
    assert (wiki.wiki_dir() / "log.md").read_text(encoding="utf-8") == before
    # and the wiki was never part of the parent commit
    tracked = _git(temp_workspace, "ls-files")
    assert "memory/evolution/wiki/log.md" not in tracked


def test_rejected_memory_is_main_path_in_gep_prompt(evo_dir: Path) -> None:
    """S27 core: every GEP prompt carries the wiki's rejection headings —
    the proposer can repeat past failures only if the wiki is empty."""
    from evolver.gep.prompt import build_gep_prompt

    wiki.append_skill_impact(
        "validation_failed: gene-bad-idea",
        "rolled back",
        metadata={"score": 0.3},
    )
    prompt = build_gep_prompt(
        now_iso="2026-09-01T00:00:00Z",
        context="",
        signals=["s"],
        selector={},
        parent_event_id=None,
        selected_gene=None,
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
    )
    assert "Wiki Impact" in prompt
    assert "validation_failed: gene-bad-idea" in prompt
    assert "do NOT repeat" in prompt


def test_prompt_has_no_wiki_section_when_wiki_empty(evo_dir: Path) -> None:
    from evolver.gep.prompt import build_gep_prompt

    prompt = build_gep_prompt(
        now_iso="2026-09-01T00:00:00Z",
        context="",
        signals=[],
        selector={},
        parent_event_id=None,
        selected_gene=None,
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
    )
    assert "Wiki Impact" not in prompt


def test_solidify_shadow_rejection_lands_impact_entry(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shadow-rejected (no_improvement) mutations land wiki evidence even
    though solidify itself returns ok (shadow period)."""
    from evolver.gep.feature_flags import set_flag
    from evolver.gep.fitness_state import record_measurement
    from evolver.gep.solidify import solidify, write_state_for_solidify

    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(temp_workspace / ".evolver" / "gep"))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=temp_workspace, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=temp_workspace,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=temp_workspace,
        capture_output=True,
        check=False,
    )
    (temp_workspace / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=temp_workspace, capture_output=True, check=False)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init", "--allow-empty"],
        cwd=temp_workspace,
        capture_output=True,
        check=False,
    )

    set_flag("enable_acceptance_gate", False, persist=False)
    record_measurement(1.0, source="solidify:seed")  # cascade r_best = 1.0
    write_state_for_solidify(
        {
            "run_id": "run-wiki",
            "selected_gene_id": "gene-wiki",
            "signals": ["s"],
            "mutation": {"type": "Mutation", "id": "m1", "category": "repair", "validation": []},
        }
    )
    assert solidify()["ok"] is True  # shadow: still ok
    impact = (wiki.wiki_dir() / "skill-impact.md").read_text(encoding="utf-8")
    assert "no_improvement: gene-wiki" in impact
    assert "Do not repeat" in impact
