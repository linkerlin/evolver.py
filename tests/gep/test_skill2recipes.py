"""Tests for GEP Skill → Recipe composition (not template recipes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.cli import main
from evolver.gep import skill2recipes
from evolver.gep.skill2gep_audit import (
    build_private_vocab,
    find_leakage,
    redact_private_literals,
)
from evolver.gep.skill2recipes import (
    MAX_STEPS,
    compose_recipe_from_skills,
    hydrolyze_and_verify,
    normalize_manifest,
    post_recipe,
    publish_step_bundle,
)


class _Store:
    def __init__(self) -> None:
        self.genes: list[dict[str, Any]] = []
        self.capsules: list[dict[str, Any]] = []

    def upsert_gene(self, gene: dict[str, Any]) -> None:
        self.genes.append(gene)

    def append_capsule(self, capsule: dict[str, Any]) -> None:
        self.capsules.append(capsule)


class _A2a:
    @staticmethod
    def get_node_id() -> str:
        return "node_aaaaaaaaaaaa"


def _write_skill(directory: Path, name: str, command: str) -> Path:
    directory.mkdir(parents=True)
    slug = name.replace("-", "_")
    markdown = f"""---
name: {name}
description: Repair {name} flow. Triggers: {slug}_alpha, {slug}_beta, {slug}_gamma.
---

# {name}

## Workflow
1. Inspect the failing assertion.
2. Apply the smallest targeted fix.
3. Re-run validation and abort if it fails.

## Avoid
- Do not refactor unrelated modules.

## Validation
```bash
{command}
```
"""
    (directory / "SKILL.md").write_text(markdown, encoding="utf-8")
    return directory


def test_normalize_manifest_accepts_paths_and_assigns_positions() -> None:
    normalized = normalize_manifest(["./a", "./b"], {"title": "My Recipe"})

    assert normalized["title"] == "My Recipe"
    assert [step["skill_path"] for step in normalized["steps"]] == ["./a", "./b"]
    assert [step["position"] for step in normalized["steps"]] == [0, 1]


def test_normalize_manifest_preserves_step_options_and_overrides() -> None:
    normalized = normalize_manifest(
        {
            "title": "old",
            "price_per_execution": 5,
            "steps": [
                {"skill_path": "./a"},
                {
                    "skillPath": "./b",
                    "optional": True,
                    "condition": "if x",
                    "parameters": {"mode": "safe"},
                },
            ],
        },
        {"title": "new", "pricePerExecution": 99},
    )

    assert normalized["title"] == "new"
    assert normalized["price_per_execution"] == 99
    assert normalized["steps"][1] == {
        "skill_path": "./b",
        "skill_name": None,
        "platform": None,
        "position": 1,
        "optional": True,
        "condition": "if x",
        "parameters": {"mode": "safe"},
    }


def test_hydrolyze_verifies_skill_with_real_trace(tmp_path: Path) -> None:
    skill = _write_skill(tmp_path / "skill", "fix-checkout", "python --version")

    result = hydrolyze_and_verify(
        {"skill_path": str(skill), "optional": False},
        {"repo_root": tmp_path},
    )

    assert result["ok"] is True
    assert result["gene"]["type"] == "Gene"
    assert result["gene"]["validation"] == ["python --version"]
    assert result["capsule"]["type"] == "Capsule"
    assert result["execution"]["status"] == "success"
    assert result["capsule"]["execution_trace"][0]["cmd"] == "python --version"


def test_hydrolyze_rejects_failure_missing_path_and_disallowed_command(
    tmp_path: Path,
) -> None:
    (tmp_path / "fail.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    failing = _write_skill(tmp_path / "failing", "broken-fix", "python fail.py")
    disallowed = _write_skill(tmp_path / "unsafe", "unsafe-fix", "curl https://example.com")

    failed = hydrolyze_and_verify({"skill_path": str(failing)}, {"repo_root": tmp_path})
    missing = hydrolyze_and_verify({"skill_path": str(tmp_path / "missing")})
    unsafe = hydrolyze_and_verify({"skill_path": str(disallowed)}, {"repo_root": tmp_path})

    assert failed["diagnostic"]["reason"] == "validation_failed"
    assert missing["diagnostic"]["reason"] == "skill_path_missing"
    assert unsafe["diagnostic"]["reason"] == "gene_validation_failed"


async def test_publish_step_bundle_dry_run_persists_content_addressed_assets() -> None:
    store = _Store()
    gene = {
        "type": "Gene",
        "id": "gene-1",
        "schema_version": "1",
        "category": "repair",
        "signals_match": ["error"],
        "strategy": ["fix"],
        "validation": ["python --version"],
        "constraints": {"max_files": 1, "forbidden_paths": []},
    }
    capsule = {
        "type": "Capsule",
        "id": "capsule-1",
        "schema_version": "1",
        "gene": "gene-1",
        "trigger": ["error"],
        "summary": "verified",
        "confidence": 0.8,
        "blast_radius": {"files": 1, "lines": 1},
        "outcome": {"status": "success", "score": 0.8},
        "execution_trace": [{"step": 1, "cmd": "python --version", "exit": 0}],
    }

    result = await publish_step_bundle(
        gene,
        capsule,
        {"publish": False, "asset_store": store},
    )

    assert result["ok"] is True
    assert result["gene_asset_id"].startswith("sha256:")
    assert result["capsule_asset_id"].startswith("sha256:")
    assert store.genes[0]["asset_id"] == result["gene_asset_id"]
    assert store.capsules[0]["gene"] == result["gene_asset_id"]
    assert result["publish"] == {"skipped": "publish_disabled"}


async def test_compose_dry_run_builds_ordered_gene_steps(tmp_path: Path) -> None:
    first = _write_skill(tmp_path / "a", "step-a", "python --version")
    second = _write_skill(tmp_path / "b", "step-b", "python --version")
    store = _Store()

    result = await compose_recipe_from_skills(
        {"title": "Two Step Pipeline", "steps": [str(first), str(second)]},
        {
            "publish": False,
            "repo_root": tmp_path,
            "asset_store": store,
            "a2a": _A2a(),
            "log_path": tmp_path / "log.jsonl",
            "state_path": tmp_path / "state.json",
        },
    )

    assert result["ok"] is True
    assert [step["position"] for step in result["steps"]] == [0, 1]
    assert all(step["asset_type"] == "Gene" for step in result["steps"])
    assert all(step["asset_id"].startswith("sha256:") for step in result["steps"])
    assert result["steps"][0]["asset_id"] != result["steps"][1]["asset_id"]
    assert result["recipe"]["dry_run"] is True
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert len(state["recipes"]) == 1


async def test_compose_aborts_required_failure_but_skips_optional(
    tmp_path: Path,
) -> None:
    (tmp_path / "fail.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    good = _write_skill(tmp_path / "good", "good-step", "python --version")
    bad = _write_skill(tmp_path / "bad", "bad-step", "python fail.py")
    common = {
        "publish": False,
        "repo_root": tmp_path,
        "asset_store": _Store(),
        "a2a": _A2a(),
        "log_path": tmp_path / "log.jsonl",
        "state_path": tmp_path / "state.json",
    }

    required = await compose_recipe_from_skills(
        {"title": "Has A Bad Step", "steps": [str(good), str(bad)]},
        common,
    )
    optional = await compose_recipe_from_skills(
        {
            "title": "Optional Bad Step",
            "steps": [str(good), {"skill_path": str(bad), "optional": True}],
        },
        common,
    )

    assert required["ok"] is False
    assert required["reason"] == "step_failed"
    assert required["skill_path"] == str(bad)
    assert len(optional["steps"]) == 1
    assert optional["skipped"][0]["skill_path"] == str(bad)


async def test_compose_rejects_invalid_manifest_shape(tmp_path: Path) -> None:
    short = await compose_recipe_from_skills({"title": "ab", "steps": ["./x"]})
    empty = await compose_recipe_from_skills({"title": "Valid", "steps": []})
    too_many = await compose_recipe_from_skills(
        {"title": "Valid", "steps": ["./x"] * (MAX_STEPS + 1)}
    )

    assert short["reason"] == "title_min_3_chars"
    assert empty["reason"] == "no_steps"
    assert too_many == {
        "ok": False,
        "reason": "too_many_steps",
        "max": MAX_STEPS,
        "got": MAX_STEPS + 1,
    }
    assert not (tmp_path / "state.json").exists()


async def test_post_recipe_dry_run_never_calls_network() -> None:
    called = {"poster": False}

    async def _poster(_body: dict[str, Any]) -> dict[str, Any]:
        called["poster"] = True
        return {"ok": False}

    result = await post_recipe(
        {"sender_id": "node_a", "title": "Recipe", "steps": []},
        {"publish": False, "recipe_poster": _poster},
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert called["poster"] is False


def test_cli_skill2recipe_routes_without_conflicting_with_template_recipes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, Any] = {}

    async def _compose(manifest: Any, opts: dict[str, Any]) -> dict[str, Any]:
        seen.update({"manifest": manifest, "opts": opts})
        return {"ok": True, "recipe_id": None, "steps": [{"asset_type": "Gene"}]}

    monkeypatch.setattr(skill2recipes, "compose_recipe_from_skills", _compose)
    code = main(
        [
            "skill2recipe",
            "--title",
            "My Pipeline",
            "--no-publish",
            "./skills/a",
            "./skills/b",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["ok"] is True
    assert seen["manifest"] == {"steps": ["./skills/a", "./skills/b"]}
    assert seen["opts"]["title"] == "My Pipeline"
    assert seen["opts"]["publish"] is False


def test_private_vocab_excludes_literals_already_public() -> None:
    private = build_private_vocab(
        "# Workflow\n1. write forecast.json\n",
        {"final_solution": "forecast.json\nseasonal_periods=12"},
    )

    assert "12" in private
    assert "forecast.json" not in private


def test_audit_drops_leaky_validation_without_mangling_command() -> None:
    private = {"987654"}
    gene = {
        "summary": "safe",
        "strategy": ["inspect"],
        "signals_match": ["error"],
        "preconditions": [],
        "validation": ["npm test -- --seed 987654", "node --check a.js"],
    }

    redacted = redact_private_literals(gene, private)

    assert redacted["validation"] == ["node --check a.js"]
    assert find_leakage(redacted, private) == []


def test_audit_scans_and_redacts_published_source_metadata() -> None:
    private = {"99887"}
    gene = {
        "summary": "safe",
        "strategy": ["inspect"],
        "signals_match": ["error"],
        "preconditions": [],
        "_source": {"overcame_errors": ["threshold 99887 exceeded"]},
    }

    assert find_leakage(gene, private) == [
        {"token": "99887", "location": "_source.overcame_errors[0]"}
    ]
    redacted = redact_private_literals(gene, private)
    assert find_leakage(redacted, private) == []
    assert "99887" not in json.dumps(redacted)
