"""Tests for evolver.gep.content_hash."""

from __future__ import annotations

from evolver.gep.content_hash import canonicalize, compute_asset_id, verify_asset_id


class TestCanonicalize:
    def test_stable(self):
        a = canonicalize({"b": 1, "a": 2})
        b = canonicalize({"a": 2, "b": 1})
        assert a == b

    def test_ensure_ascii_false(self):
        assert "中" in canonicalize({"x": "中文"})


class TestComputeAssetId:
    def test_basic(self):
        asset = {"id": "g1", "summary": "test"}
        aid = compute_asset_id(asset)
        assert aid.startswith("sha256:")
        assert len(aid) == 64 + 7

    def test_excludes_asset_id(self):
        asset = {"id": "g1", "asset_id": "sha256:abc"}
        aid1 = compute_asset_id(asset)
        asset2 = {"id": "g1", "asset_id": "sha256:xyz"}
        aid2 = compute_asset_id(asset2)
        assert aid1 == aid2

    def test_verify(self):
        asset = {"id": "g1", "summary": "x"}
        aid = compute_asset_id(asset)
        assert verify_asset_id(asset, aid)
        assert not verify_asset_id(asset, "sha256:wrong")

    def test_deterministic(self):
        asset = {"a": 1, "b": [3, 2, 1]}
        assert compute_asset_id(asset) == compute_asset_id(asset)
