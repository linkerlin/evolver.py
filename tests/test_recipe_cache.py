"""Tests for evolver.recipe.cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.recipe.cache import (
    cache_recipe,
    clear_cache,
    get_cached_recipe,
    list_cached_recipes,
)


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))


class TestCache:
    def test_round_trip(self) -> None:
        recipe = {"id": "r1", "name": "Test", "files": [{"path": "a.py", "content": "1"}]}
        cache_recipe(recipe)
        loaded = get_cached_recipe("r1")
        assert loaded is not None
        assert loaded["id"] == "r1"

    def test_missing_returns_none(self) -> None:
        assert get_cached_recipe("nonexistent") is None

    def test_list_cached(self) -> None:
        cache_recipe({"id": "r1", "name": "A"})
        cache_recipe({"id": "r2", "name": "B"})
        recipes = list_cached_recipes()
        assert len(recipes) == 2
        ids = {r["id"] for r in recipes}
        assert ids == {"r1", "r2"}

    def test_clear(self) -> None:
        cache_recipe({"id": "r1"})
        count = clear_cache()
        assert count == 1
        assert list_cached_recipes() == []
