"""Tests for evolver.recipe.client."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from evolver.recipe.client import _render_template, apply_recipe, get_recipe, list_recipes


class TestListRecipes:
    @respx.mock
    async def test_success(self) -> None:
        respx.get("https://evomap.ai/v1/recipes/").mock(
            return_value=Response(200, json={"recipes": [{"id": "r1", "name": "FastAPI"}, {"id": "r2", "name": "React"}]})
        )
        result = await list_recipes()
        assert result["ok"] is True
        assert len(result["recipes"]) == 2

    @respx.mock
    async def test_with_tag(self) -> None:
        route = respx.get("https://evomap.ai/v1/recipes/").mock(
            return_value=Response(200, json={"recipes": []})
        )
        await list_recipes(tag="python", limit=5)
        req = route.calls[0].request
        assert "tag=python" in str(req.url)
        assert "limit=5" in str(req.url)


class TestGetRecipe:
    @respx.mock
    async def test_success(self) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(200, json={"id": "r1", "files": [{"path": "main.py", "content": "print(1)"}]})
        )
        result = await get_recipe("r1")
        assert result["ok"] is True
        assert result["recipe"]["id"] == "r1"

    @respx.mock
    async def test_not_found(self) -> None:
        respx.get("https://evomap.ai/v1/recipes/r99").mock(return_value=Response(404))
        result = await get_recipe("r99")
        assert result["ok"] is False


class TestRenderTemplate:
    def test_simple(self) -> None:
        assert _render_template("Hello {{name}}!", {"name": "world"}) == "Hello world!"

    def test_missing_keeps_placeholder(self) -> None:
        assert _render_template("{{a}} {{b}}", {"a": "1"}) == "1 {{b}}"

    def test_whitespace_tolerant(self) -> None:
        assert _render_template("{{  x  }}", {"x": "y"}) == "y"


class TestApplyRecipe:
    @respx.mock
    async def test_dry_run(self, tmp_path: Path) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(
                200,
                json={
                    "id": "r1",
                    "files": [{"path": "main.py", "content": "print(1)"}],
                    "variables": [{"name": "name", "default": "world"}],
                },
            )
        )
        result = await apply_recipe("r1", target_dir=tmp_path, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["files"] == ["main.py"]
        assert result["variables"]["name"] == "world"
        assert not (tmp_path / "main.py").exists()

    @respx.mock
    async def test_apply_writes_files(self, tmp_path: Path) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(
                200,
                json={
                    "id": "r1",
                    "files": [
                        {"path": "src/main.py", "content": "print(1)"},
                        {"path": "README.md", "content": "# Hello"},
                    ],
                },
            )
        )
        result = await apply_recipe("r1", target_dir=tmp_path)
        assert result["ok"] is True
        assert "src/main.py" in result["applied"]
        assert "README.md" in result["applied"]
        assert (tmp_path / "src" / "main.py").read_text() == "print(1)"
        assert (tmp_path / "README.md").read_text() == "# Hello"

    @respx.mock
    async def test_apply_renders_variables(self, tmp_path: Path) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(
                200,
                json={
                    "id": "r1",
                    "files": [{"path": "main.py", "content": "name = '{{name}}'"}],
                    "variables": [{"name": "name", "default": "world"}],
                },
            )
        )
        result = await apply_recipe("r1", target_dir=tmp_path, variables={"name": "evolver"})
        assert result["ok"] is True
        content = (tmp_path / "main.py").read_text()
        assert content == "name = 'evolver'"

    @respx.mock
    async def test_apply_conflict_detection(self, tmp_path: Path) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(
                200,
                json={
                    "id": "r1",
                    "files": [{"path": "main.py", "content": "new"}],
                },
            )
        )
        (tmp_path / "main.py").write_text("existing", encoding="utf-8")
        result = await apply_recipe("r1", target_dir=tmp_path)
        assert result["ok"] is True
        assert "main.py" in result["conflicts"]
        assert (tmp_path / "main.py").read_text() == "existing"

    @respx.mock
    async def test_apply_empty_recipe(self, tmp_path: Path) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(200, json={"id": "r1", "files": []})
        )
        result = await apply_recipe("r1", target_dir=tmp_path)
        assert result["ok"] is True
        assert "no files" in result.get("note", "").lower()
