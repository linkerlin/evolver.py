"""Tests for evolver.gep.open_pr_registry."""

from unittest.mock import patch

import pytest

from evolver.gep.open_pr_registry import (
    archive_merged_prs,
    get_open_prs,
    load_registry,
    prune_old_entries,
    register_pr,
    save_registry,
    update_pr_status,
)


class TestRegistry:
    def test_load_missing(self, tmp_path):
        data = load_registry(path=tmp_path / "missing.json")
        assert data["version"] == 1
        assert data["prs"] == []

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "reg.json"
        data = {"version": 1, "prs": [{"pr_number": 1, "status": "open"}]}
        save_registry(data, path=path)
        loaded = load_registry(path=path)
        assert loaded["prs"][0]["pr_number"] == 1


class TestRegisterPR:
    def test_register(self, tmp_path):
        path = tmp_path / "reg.json"
        entry = register_pr(
            pr_number=42,
            pr_url="https://github.com/.../42",
            branch="evolver-auto/123-g1",
            gene_id="g1",
            diff_text="+line1",
            confidence=0.9,
            path=path,
        )
        assert entry["pr_number"] == 42
        assert entry["diff_hash"]
        data = load_registry(path=path)
        assert len(data["prs"]) == 1


class TestUpdateStatus:
    def test_update(self, tmp_path):
        path = tmp_path / "reg.json"
        register_pr(1, "url", "b", "g", "diff", 0.9, path=path)
        updated = update_pr_status(1, "merged", path=path)
        assert updated is not None
        assert updated["status"] == "merged"

    def test_missing(self, tmp_path):
        path = tmp_path / "reg.json"
        assert update_pr_status(999, "merged", path=path) is None


class TestGetOpenPRs:
    def test_filter(self, tmp_path):
        path = tmp_path / "reg.json"
        register_pr(1, "url", "b", "g", "diff", 0.9, status="open", path=path)
        register_pr(2, "url", "b", "g", "diff", 0.9, status="merged", path=path)
        open_prs = get_open_prs(path=path)
        assert len(open_prs) == 1
        assert open_prs[0]["pr_number"] == 1


class TestPrune:
    def test_removes_old(self, tmp_path):
        path = tmp_path / "reg.json"
        import time
        old = time.time() - 40 * 86400
        register_pr(1, "url", "b", "g", "diff", 0.9, path=path)
        # Manually age the entry
        data = load_registry(path=path)
        data["prs"][0]["updated_at"] = old
        save_registry(data, path=path)
        removed = prune_old_entries(max_age_days=30, path=path)
        assert removed == 1

    def test_keeps_recent(self, tmp_path):
        path = tmp_path / "reg.json"
        register_pr(1, "url", "b", "g", "diff", 0.9, path=path)
        removed = prune_old_entries(max_age_days=30, path=path)
        assert removed == 0
