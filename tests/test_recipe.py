"""Tests for evolver.recipe.client."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from evolver.recipe.client import apply_recipe, get_recipe, list_recipes


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
            return_value=Response(200, json={"id": "r1", "files": ["main.py"]})
        )
        result = await get_recipe("r1")
        assert result["ok"] is True
        assert result["recipe"]["id"] == "r1"

    @respx.mock
    async def test_not_found(self) -> None:
        respx.get("https://evomap.ai/v1/recipes/r99").mock(return_value=Response(404))
        result = await get_recipe("r99")
        assert result["ok"] is False


class TestApplyRecipe:
    @respx.mock
    async def test_dry_run(self) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(200, json={"id": "r1", "files": ["main.py"]})
        )
        result = await apply_recipe("r1", dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["files"] == ["main.py"]

    @respx.mock
    async def test_apply_skeleton(self) -> None:
        respx.get("https://evomap.ai/v1/recipes/r1").mock(
            return_value=Response(200, json={"id": "r1", "files": ["main.py"]})
        )
        result = await apply_recipe("r1")
        assert result["ok"] is True
        assert "skeleton" in result["note"]
