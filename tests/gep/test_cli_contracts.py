"""Tests for evolver.gep.cli_contracts (reuse.v1 / publish.v1)."""

# Loop-local closures mutate dict flags; ARG002 unused store args match Node fixtures.
# ruff: noqa: B023, ARG002, E501

from __future__ import annotations

import hashlib
import hmac
import json
from io import StringIO
from pathlib import Path
from typing import Any

from evolver.gep.cli_contracts import (
    build_publish_bundle,
    parse_publish_args,
    parse_reuse_args,
    run_publish_command,
    run_reuse_command,
)
from evolver.gep.content_hash import compute_asset_id


def _capture() -> tuple[StringIO, dict[str, Any]]:
    buf = StringIO()
    return buf, {"out": buf}


def _gene(**extra: Any) -> dict[str, Any]:
    base = {
        "type": "Gene",
        "schema_version": "1",
        "asset_id": "sha256:gene-original",
        "id": "gene-1",
        "category": "repair",
        "signals_match": ["log_error"],
        "strategy": ["inspect logs"],
        "constraints": {"max_files": 2, "forbidden_paths": []},
        "validation": ["node --test"],
    }
    base.update(extra)
    return base


def _capsule(**extra: Any) -> dict[str, Any]:
    base = {
        "type": "Capsule",
        "schema_version": "1",
        "asset_id": "sha256:cap-original",
        "id": "cap-1",
        "trigger": ["log_error"],
        "gene": "sha256:gene-original",
        "summary": "fixed retry path",
        "confidence": 0.9,
        "blast_radius": {"files": 1, "lines": 3},
        "outcome": {"status": "success", "score": 0.8},
    }
    base.update(extra)
    return base


def _event(**extra: Any) -> dict[str, Any]:
    base = {
        "type": "EvolutionEvent",
        "schema_version": "1",
        "asset_id": "sha256:event-original",
        "id": "event-1",
        "gene": "sha256:gene-original",
        "capsule": "sha256:cap-original",
        "signals": ["log_error"],
        "outcome": {"status": "success"},
    }
    base.update(extra)
    return base


def _with_computed_asset_id(asset: dict[str, Any]) -> dict[str, Any]:
    copy = dict(asset)
    copy["asset_id"] = compute_asset_id(copy)
    return copy


class _FakeStore:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.writes: list[dict[str, Any]] = []
        self._records = records

    def load_genes(self) -> list[dict[str, Any]]:
        return [row for row in self._records if row.get("type") == "Gene"]

    def load_capsules(self) -> list[dict[str, Any]]:
        return [row for row in self._records if row.get("type") == "Capsule"]

    def read_all_events(self) -> list[dict[str, Any]]:
        return [row for row in self._records if row.get("type") == "EvolutionEvent"]

    def upsert_gene(self, asset: dict[str, Any]) -> None:
        self.writes.append(asset)

    def upsert_capsule(self, asset: dict[str, Any]) -> None:
        self.writes.append(asset)

    def append_event_jsonl(self, asset: dict[str, Any]) -> None:
        self.writes.append(asset)


def _fake_a2a() -> Any:
    class _Module:
        @staticmethod
        def build_publish_bundle(**kwargs: Any) -> dict[str, Any]:
            assets = [kwargs["gene"], kwargs["capsule"]]
            if kwargs.get("event") is not None:
                assets.append(kwargs["event"])
            return {
                "protocol": "gep-a2a",
                "protocol_version": "1.0.0",
                "message_type": "publish",
                "payload": {"assets": assets},
            }

        @staticmethod
        def build_fetch(**kwargs: Any) -> dict[str, Any]:
            return {
                "protocol": "gep-a2a",
                "protocol_version": "1.0.0",
                "message_type": "fetch",
                "payload": {"asset_ids": kwargs["asset_ids"]},
            }

        @staticmethod
        def build_hub_headers() -> dict[str, str]:
            return {"authorization": "Bearer test"}

    return _Module()


def _expected_signature(assets: list[dict[str, Any]], secret: str) -> str:
    ids = sorted(
        asset["asset_id"]
        for asset in assets
        if asset.get("type") in ("Gene", "Capsule") and asset.get("asset_id")
    )
    return hmac.new(secret.encode(), "|".join(ids).encode(), hashlib.sha256).hexdigest()


def test_parse_reuse_args_accepts_id_and_rejects_missing() -> None:
    assert parse_reuse_args(["--id", "sha256:x", "--json"]) == {
        "ok": True,
        "assetId": "sha256:x",
        "jsonOut": True,
    }
    assert parse_reuse_args(["--json"])["ok"] is False
    assert parse_reuse_args(["--id", "sha256:x", "--unknown", "--json"])["reason"] == "unsupported"
    assert parse_reuse_args(["sha256:x", "--json"])["reason"] == "unsupported"
    assert parse_reuse_args(["--id", "sha256:x"])["reason"] == "unsupported"


def test_parse_publish_args_accepts_assets_and_dry_run() -> None:
    assert parse_publish_args(["--asset", "g", "--capsule=c", "--dry-run", "--json"]) == {
        "ok": True,
        "assetRefs": ["g", "c"],
        "dryRun": True,
        "jsonOut": True,
    }
    assert parse_publish_args(["--unknown"])["reason"] == "unsupported"
    assert parse_publish_args(["--asset", "g"])["reason"] == "unsupported"
    assert parse_publish_args(["g", "--json"])["reason"] == "unsupported"


async def test_reuse_stores_without_transport_metadata(tmp_path: Path) -> None:
    buf, deps = _capture()
    store = _FakeStore([])
    fetched = _with_computed_asset_id(_gene())
    fetched["credit_cost"] = {"total": 3}
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["contract"] == "reuse.v1"
    assert payload["status"] == "ok"
    assert len(store.writes) == 1
    assert "credit_cost" not in store.writes[0]
    assert '"source":"hub"' in (tmp_path / "provenance.jsonl").read_text(encoding="utf-8")


async def test_reuse_fails_closed_when_provenance_append_fails(tmp_path: Path) -> None:
    buf, deps = _capture()
    store = _FakeStore([])
    (tmp_path / "provenance.jsonl").mkdir()
    fetched = _with_computed_asset_id(_gene())
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert store.writes == []


async def test_reuse_rollback_provenance_on_store_failure(tmp_path: Path) -> None:
    buf, deps = _capture()
    fetched = _with_computed_asset_id(_gene())

    class _BrokenStore(_FakeStore):
        def upsert_gene(self, asset: dict[str, Any]) -> None:
            raise RuntimeError("disk full /tmp/evolver/secret-token")

    store = _BrokenStore([])
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert "secret-token" not in buf.getvalue()
    prov = tmp_path / "provenance.jsonl"
    assert not prov.exists() or not prov.read_text(encoding="utf-8").strip()


async def test_reuse_rejects_same_local_id_different_asset_id(tmp_path: Path) -> None:
    buf, deps = _capture()
    existing = _with_computed_asset_id(_gene(id="gene-1"))
    fetched = _with_computed_asset_id(_gene(id="gene-1", strategy=["other"]))
    store = _FakeStore([existing])
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert len(store.writes) == 0


async def test_reuse_allows_idempotent_same_local_id_and_asset_id(tmp_path: Path) -> None:
    buf, deps = _capture()
    asset = _with_computed_asset_id(_gene(id="gene-1"))
    store = _FakeStore([dict(asset)])
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: asset,
        }
    )
    code = await run_reuse_command(["--id", asset["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["status"] == "ok"
    assert len(store.writes) == 1


async def test_reuse_rejects_positional_id_before_fetch() -> None:
    buf, deps = _capture()
    called = {"fetch": False}

    async def _fetch(_asset_id: str) -> None:
        called["fetch"] = True

    deps["fetch_asset_by_id"] = _fetch
    code = await run_reuse_command(["sha256:positional", "--json"], deps)

    assert code == 1
    assert called["fetch"] is False


def test_publish_bundle_rejects_bare_gene() -> None:
    result = build_publish_bundle(["g"], {"asset_store": _FakeStore([_gene(asset_id="g")])})
    assert result["ok"] is False
    assert result["reason"] == "bundle_required"


def test_publish_bundle_rejects_bare_capsule() -> None:
    result = build_publish_bundle(["c"], {"asset_store": _FakeStore([_capsule(asset_id="c")])})
    assert result["ok"] is False
    assert result["reason"] == "bundle_required"


def test_publish_bundle_rejects_multiple_genes() -> None:
    refs = ["g1", "g2", "c"]
    store = _FakeStore(
        [
            _gene(asset_id="g1", id="gene-1"),
            _gene(asset_id="g2", id="gene-2"),
            _capsule(asset_id="c", gene="g1"),
        ]
    )
    result = build_publish_bundle(refs, {"asset_store": store})
    assert result["ok"] is False
    assert result["reason"] == "bundle_required"


async def test_publish_dry_run_validate_and_credits() -> None:
    buf, deps = _capture()
    validated = {"called": False}
    published = {"called": False}

    async def _validate(message: dict[str, Any]) -> dict[str, Any]:
        validated["called"] = True
        assert message["message_type"] == "publish"
        return {
            "ok": True,
            "status": 200,
            "body": {
                "payload": {
                    "valid": True,
                    "credits": {
                        "required": 2,
                        "available": 5,
                        "estimated": 2,
                        "balance_kind": "node_balance",
                    },
                }
            },
        }

    async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
        published["called"] = True
        raise AssertionError("dry-run should not publish")

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset", "g", "--asset", "c", "--dry-run", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["contract"] == "publish.v1"
    assert payload["mode"] == "dry_run"
    assert payload["blocked"] is False
    assert payload["gates"]["quality"] == "pass"
    assert payload["credits"] == {
        "required": 2,
        "available": 5,
        "estimated": 2,
        "balance_kind": "node_balance",
    }
    assert validated["called"] is True
    assert published["called"] is False


async def test_publish_actual_success_with_credits() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": 200,
            "body": {
                "payload": {
                    "status": "accepted",
                    "receipt_id": "rcpt_1",
                    "bundle_id": "bdl_1",
                    "credits": {
                        "required": 3,
                        "available": 6,
                        "charged": 3,
                        "balance_kind": "node_balance",
                    },
                }
            },
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset", "g", "--asset", "c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["status"] == "accepted"
    assert payload["receipt_id"] == "rcpt_1"
    assert payload["credits"]["charged"] == 3


async def test_publish_already_published_is_idempotent_success() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": 200,
            "body": {"payload": {"decision": "reject", "reason": "already_published"}},
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset", "g", "--asset", "c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["status"] == "published"


async def test_publish_dry_run_hard_leak_blocks_without_payload_assets() -> None:
    buf, deps = _capture()
    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [
                    _gene(asset_id="g"),
                    _capsule(
                        asset_id="c",
                        gene="g",
                        summary="internal endpoint 10.1.2.3:8080",
                    ),
                ]
            ),
        }
    )
    code = await run_publish_command(["--asset", "g", "--asset", "c", "--dry-run", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert "10.1.2.3:8080" not in buf.getvalue()
    assert payload["blocked"] is True
    assert payload["gates"]["leak"] == "fail"
    assert payload["block_reasons"] == ["leak_detected"]
    assert "payload" not in payload


async def test_reuse_preserves_existing_provenance_on_store_failure(tmp_path: Path) -> None:
    buf, deps = _capture()
    fetched = _with_computed_asset_id(_gene())
    existing = json.dumps({"assetId": "sha256:existing", "source": "hub"}) + "\n"
    (tmp_path / "provenance.jsonl").write_text(existing, encoding="utf-8")

    class _BrokenStore(_FakeStore):
        def upsert_gene(self, asset: dict[str, Any]) -> None:
            raise RuntimeError("store failed token=abcdefghijklmnop path=/tmp/.env")

    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": _BrokenStore([]),
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    stdout = buf.getvalue()
    payload = json.loads(stdout)

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert (tmp_path / "provenance.jsonl").read_text(encoding="utf-8") == existing
    assert "store failed" not in stdout
    assert "token=abcdefghijklmnop" not in stdout
    assert "/tmp/.env" not in stdout


async def test_reuse_rejects_content_hash_mismatch(tmp_path: Path) -> None:
    buf, deps = _capture()
    store = _FakeStore([])
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: _gene(asset_id="sha256:bad"),
        }
    )
    code = await run_reuse_command(["--id", "sha256:bad", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert store.writes == []
    assert not (tmp_path / "provenance.jsonl").exists()


async def test_reuse_maps_missing_assets_to_not_found() -> None:
    buf, deps = _capture()
    deps.update({"asset_store": _FakeStore([]), "fetch_asset_by_id": lambda _asset_id: None})
    code = await run_reuse_command(["--id=missing", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert {
        "ok": payload["ok"],
        "contract": payload["contract"],
        "reason": payload["reason"],
    } == {"ok": False, "contract": "reuse.v1", "reason": "not_found"}


async def test_reuse_rejects_unsupported_flag_and_missing_json_before_fetch(
    tmp_path: Path,
) -> None:
    for args in (["--id", "sha256:gene", "--future", "--json"], ["--id", "sha256:gene"]):
        buf, deps = _capture()
        called = {"fetch": False}
        store = _FakeStore([])

        async def _fetch(_asset_id: str) -> dict[str, Any]:
            called["fetch"] = True
            return _with_computed_asset_id(_gene())

        deps.update(
            {
                "assets_dir": tmp_path,
                "asset_store": store,
                "fetch_asset_by_id": _fetch,
            }
        )
        code = await run_reuse_command(args, deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert payload["reason"] == "unsupported"
        assert called["fetch"] is False
        assert store.writes == []


async def test_reuse_rejects_assets_missing_schema_version(tmp_path: Path) -> None:
    buf, deps = _capture()
    store = _FakeStore([])
    fetched = _gene()
    del fetched["schema_version"]
    fetched["asset_id"] = compute_asset_id(fetched)
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert store.writes == []
    assert not (tmp_path / "provenance.jsonl").exists()


async def test_reuse_conflict_message_and_no_provenance(tmp_path: Path) -> None:
    local = _with_computed_asset_id(_gene(id="shared-id", strategy=["local strategy"]))
    fetched = _with_computed_asset_id(_gene(id="shared-id", strategy=["hub strategy"]))
    assert local["asset_id"] != fetched["asset_id"]
    buf, deps = _capture()
    store = _FakeStore([local])
    deps.update(
        {
            "assets_dir": tmp_path,
            "asset_store": store,
            "fetch_asset_by_id": lambda _asset_id: fetched,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert payload["message"] == "local asset id conflict"
    assert store.writes == []
    assert not (tmp_path / "provenance.jsonl").exists()


async def test_publish_rejects_missing_json_and_positional_before_hub() -> None:
    for args in (["--asset", "g", "--asset", "c"], ["g", "--json"]):
        buf, deps = _capture()
        called = {"validate": False, "publish": False}

        async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
            called["validate"] = True
            return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

        async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
            called["publish"] = True
            return {"ok": True, "status": 200, "body": {"payload": {"status": "accepted"}}}

        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "validate": _validate,
                "publish": _publish,
            }
        )
        code = await run_publish_command(args, deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert payload["reason"] == "unsupported"
        assert called["validate"] is False
        assert called["publish"] is False


async def test_publish_dry_run_quality_failure_returns_blocked() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "status": 400,
            "body": {
                "payload": {
                    "valid": False,
                    "credits": {
                        "required": 4,
                        "available": 8,
                        "estimated": 4,
                        "balance_kind": "node_balance",
                    },
                }
            },
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": lambda _m: (_ for _ in ()).throw(AssertionError("no publish")),
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--dry-run", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["ok"] is True
    assert payload["blocked"] is True
    assert payload["gates"]["quality"] == "fail"
    assert payload["block_reasons"] == ["quality_gate_failed"]
    assert payload["credits"]["required"] == 4
    assert isinstance(payload["payload"]["assets"], list)


async def test_publish_actual_fail_closes_empty_validate_before_publish() -> None:
    cases = [
        {"ok": True, "status": 200, "body": {}},
        {"ok": True, "status": 200, "body": {"payload": {}}},
    ]
    for response in cases:
        buf, deps = _capture()
        published = {"called": False}

        async def _validate(_message: dict[str, Any], resp: dict[str, Any] = response) -> dict[str, Any]:
            return resp

        async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
            published["called"] = True
            return {"ok": True, "status": 200, "body": {"payload": {"status": "accepted"}}}

        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "validate": _validate,
                "publish": _publish,
            }
        )
        code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert payload["reason"] == "quality_gate_failed"
        assert payload["retryable"] is False
        assert published["called"] is False


async def test_publish_dry_run_empty_validate_is_blocked_not_success() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {}}}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--dry-run", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["mode"] == "dry_run"
    assert payload["blocked"] is True
    assert payload["gates"]["quality"] == "fail"
    assert payload["block_reasons"] == ["quality_gate_failed"]


async def test_publish_dry_run_without_hub_auth_fails_auth_required() -> None:
    buf, deps = _capture()

    class _AuthFailA2a:
        @staticmethod
        def build_publish_bundle(**_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("publishBundle: node_secret is required for signing")

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": None,
            "a2a": _AuthFailA2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "hub_fetch": lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no hub")),
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--dry-run", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["ok"] is False
    assert payload["mode"] == "dry_run"
    assert payload["reason"] == "auth_required"


async def test_publish_validate_failures_map_status_to_contract_reasons() -> None:
    cases = [
        (401, "auth_required", False),
        (403, "auth_required", False),
        (402, "insufficient_credits", False),
        (429, "network_error", True),
        (500, "network_error", True),
        (0, "network_error", True),
    ]
    for status, reason, retryable in cases:
        buf, deps = _capture()

        async def _validate(
            _message: dict[str, Any], st: int = status
        ) -> dict[str, Any]:
            return {
                "ok": False,
                "status": st,
                "body": {"payload": {"error": "raw upstream failure"}},
            }

        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "validate": _validate,
                "publish": lambda _m: (_ for _ in ()).throw(AssertionError("no publish")),
            }
        )
        code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert payload["reason"] == reason
        assert payload["retryable"] is retryable
        assert "raw upstream failure" not in buf.getvalue()


async def test_publish_preserves_stable_hub_capability_reasons() -> None:
    for reason in ("unsupported", "cli_unavailable"):
        dry_buf, dry_deps = _capture()

        async def _validate_dry(
            _message: dict[str, Any], r: str = reason
        ) -> dict[str, Any]:
            return {"ok": False, "status": 400, "reason": r, "body": {"payload": {"reason": r}}}

        dry_deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "validate": _validate_dry,
            }
        )
        dry_code = await run_publish_command(
            ["--asset=g", "--asset=c", "--dry-run", "--json"], dry_deps
        )
        dry_payload = json.loads(dry_buf.getvalue())
        assert dry_code == 1
        assert dry_payload["reason"] == reason
        assert "block_reasons" not in dry_payload

        actual_buf, actual_deps = _capture()

        async def _validate_actual(
            _message: dict[str, Any], r: str = reason
        ) -> dict[str, Any]:
            return {"ok": False, "status": 404, "body": {"payload": {"reason": r}}}

        actual_deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "validate": _validate_actual,
            }
        )
        actual_code = await run_publish_command(
            ["--asset=g", "--asset=c", "--json"], actual_deps
        )
        assert actual_code == 1
        assert json.loads(actual_buf.getvalue())["reason"] == reason


async def test_reuse_preserves_stable_hub_capability_reasons() -> None:
    for reason in ("unsupported", "cli_unavailable"):
        buf, deps = _capture()

        async def _hub_fetch(_url: str, _opts: dict[str, Any], r: str = reason) -> dict[str, Any]:
            return {"ok": False, "status": 404, "json": lambda: {"payload": {"reason": r}}}

        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "hub_fetch": _hub_fetch,
            }
        )
        code = await run_reuse_command(["--id=sha256:missing", "--json"], deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert payload["reason"] == reason
        assert payload["reason"] != "not_found"


async def test_reuse_uses_node_secret_when_oauth_also_available(tmp_path: Path) -> None:
    node_secret = "n" * 64
    oauth_token = "oauth-access-token"
    fetched = _with_computed_asset_id(_gene())
    buf, deps = _capture()
    counts = {"build_hub_headers": 0, "fetch": 0}

    class _A2a:
        @staticmethod
        def build_fetch(**kwargs: Any) -> dict[str, Any]:
            return {
                "protocol": "gep-a2a",
                "protocol_version": "1.0.0",
                "message_type": "fetch",
                "payload": {"asset_ids": kwargs["asset_ids"]},
            }

        @staticmethod
        def build_hub_headers() -> dict[str, str]:
            counts["build_hub_headers"] += 1
            return {"Authorization": f"Bearer {oauth_token}"}

    async def _hub_fetch(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        counts["fetch"] += 1
        assert url.endswith("/a2a/fetch")
        auth = opts["headers"].get("Authorization") or opts["headers"].get("authorization")
        assert auth == f"Bearer {node_secret}"
        assert auth != f"Bearer {oauth_token}"
        return {"ok": True, "status": 200, "json": lambda: {"payload": {"assets": [fetched]}}}

    deps.update(
        {
            "out": buf,
            "assets_dir": tmp_path,
            "asset_store": _FakeStore([]),
            "hub_url": "https://hub.test",
            "node_secret": node_secret,
            "a2a": _A2a(),
            "hub_fetch": _hub_fetch,
        }
    )
    code = await run_reuse_command(["--id", fetched["asset_id"], "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert counts["fetch"] == 1
    assert counts["build_hub_headers"] == 0
    assert payload["status"] == "ok"


async def test_publish_rejects_oauth_only_for_node_scoped_endpoints() -> None:
    class _OauthOnly:
        @staticmethod
        def build_publish_bundle(**_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("publishBundle: node_secret is required for signing")

        @staticmethod
        def build_hub_headers() -> dict[str, str]:
            return {"Authorization": "Bearer oauth-access-token"}

    for args, mode in (
        (["--asset=g", "--asset=c", "--dry-run", "--json"], "dry_run"),
        (["--asset=g", "--asset=c", "--json"], "publish"),
    ):
        buf, deps = _capture()
        hub_calls = {"n": 0}

        def _hub_fetch(_url: str, _opts: dict[str, Any]) -> dict[str, Any]:
            hub_calls["n"] += 1
            raise AssertionError("should not send OAuth to node-scoped endpoint")

        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": None,
                "a2a": _OauthOnly(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "hub_fetch": _hub_fetch,
            }
        )
        code = await run_publish_command(args, deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert hub_calls["n"] == 0
        assert payload["mode"] == mode
        assert payload["reason"] == "auth_required"


async def test_publish_maps_thrown_hub_fetch_to_retryable_network_error() -> None:
    buf, deps = _capture()

    def _hub_fetch(_url: str, _opts: dict[str, Any]) -> dict[str, Any]:
        raise ConnectionError("ECONNRESET dns failure")

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "hub_fetch": _hub_fetch,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "network_error"
    assert payload["retryable"] is True
    assert "ECONNRESET" not in buf.getvalue()


async def test_publish_actual_hard_rejects_residual_leak() -> None:
    buf, deps = _capture()
    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [
                    _gene(asset_id="g"),
                    _capsule(
                        asset_id="c",
                        gene="g",
                        summary="internal endpoint 10.1.2.3:8080",
                    ),
                ]
            ),
            "validate": lambda _m: (_ for _ in ()).throw(AssertionError("no validate")),
            "publish": lambda _m: (_ for _ in ()).throw(AssertionError("no publish")),
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "leak_detected"
    assert "10.1.2.3:8080" not in buf.getvalue()


async def test_publish_does_not_treat_other_reject_reasons_as_success() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": 200,
            "body": {
                "payload": {
                    "decision": "reject",
                    "reason": "internal_error",
                    "bundle_id": "bdl_1",
                }
            },
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["ok"] is False
    assert payload["reason"] == "internal_error"
    assert "status" not in payload


async def test_publish_credits_do_not_fabricate_estimated_or_charged() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": 200,
            "body": {"payload": {"valid": True, "credits": {"required": 2, "available": 5}}},
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--dry-run", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["credits"] == {"required": 2, "available": 5}
    assert "estimated" not in payload["credits"]
    assert "charged" not in payload["credits"]


async def test_publish_credits_keep_zero_and_omit_fractional() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": 200,
            "body": {
                "payload": {
                    "status": "accepted",
                    "credits": {
                        "required": "0",
                        "available": 0,
                        "charged": 1.5,
                        "balance_kind": "not safe!!!",
                    },
                }
            },
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["credits"]["required"] == 0
    assert payload["credits"]["available"] == 0
    assert "charged" not in payload["credits"]
    assert "balance_kind" not in payload["credits"]


async def test_publish_maps_accept_and_quarantine_decisions() -> None:
    accept_buf, accept_deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish_accept(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"decision": "accept"}}}

    accept_deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish_accept,
        }
    )
    accept_code = await run_publish_command(["--asset=g", "--asset=c", "--json"], accept_deps)
    assert accept_code == 0
    assert json.loads(accept_buf.getvalue())["status"] == "accepted"

    quarantine_buf, quarantine_deps = _capture()

    async def _publish_quarantine(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"decision": "quarantine"}}}

    quarantine_deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish_quarantine,
        }
    )
    quarantine_code = await run_publish_command(
        ["--asset=g", "--asset=c", "--json"], quarantine_deps
    )
    quarantine_payload = json.loads(quarantine_buf.getvalue())
    assert quarantine_code == 1
    assert quarantine_payload["reason"] == "quality_gate_failed"


async def test_publish_rejects_non_lifecycle_hub_status_ok() -> None:
    buf, deps = _capture()

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish(_message: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": 200, "body": {"payload": {"status": "ok"}}}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert "status" not in payload


async def test_publish_actual_rehashes_and_resigns_after_mutation() -> None:
    buf, deps = _capture()
    secret = "h" * 64
    leaked = "token=abcdefghijklmnop"
    seen: dict[str, Any] = {}

    class _SigningMutating:
        @staticmethod
        def build_publish_bundle(**kwargs: Any) -> dict[str, Any]:
            gene = dict(kwargs["gene"])
            capsule = dict(kwargs["capsule"])
            if not isinstance(capsule.get("execution_trace"), list):
                capsule["execution_trace"] = [
                    {
                        "step": 1,
                        "stage": "build",
                        "cmd": f"node --test {leaked}",
                        "exit": 0,
                    }
                ]
            gene["asset_id"] = compute_asset_id(gene)
            capsule["asset_id"] = compute_asset_id(capsule)
            assets = [gene, capsule]
            signature = _expected_signature(assets, secret)
            return {
                "protocol": "gep-a2a",
                "protocol_version": "1.0.0",
                "message_type": "publish",
                "payload": {"assets": assets, "signature": signature},
            }

        @staticmethod
        def build_hub_headers() -> dict[str, str]:
            return {}

    async def _validate(message: dict[str, Any]) -> dict[str, Any]:
        seen["validated"] = json.loads(json.dumps(message))
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    async def _publish(message: dict[str, Any]) -> dict[str, Any]:
        seen["published"] = json.loads(json.dumps(message))
        return {"ok": True, "status": 200, "body": {"payload": {"status": "accepted"}}}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": secret,
            "a2a": _SigningMutating(),
            "asset_store": _FakeStore([_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]),
            "validate": _validate,
            "publish": _publish,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())
    assets = seen["published"]["payload"]["assets"]

    assert code == 0
    assert leaked not in json.dumps(seen["validated"])
    assert leaked not in json.dumps(seen["published"])
    assert assets[0]["asset_id"] == compute_asset_id(assets[0])
    assert assets[1]["asset_id"] == compute_asset_id(assets[1])
    assert seen["published"]["payload"]["signature"] == _expected_signature(assets, secret)
    assert seen["validated"]["payload"]["signature"] == seen["published"]["payload"]["signature"]
    assert payload["assets"] == [
        {"asset_id": assets[0]["asset_id"], "type": assets[0]["type"]},
        {"asset_id": assets[1]["asset_id"], "type": assets[1]["type"]},
    ]


async def test_publish_redacts_secret_shaped_keys_and_nested_values() -> None:
    buf, deps = _capture()
    secret = "q" * 64
    marker = "token=abcdefghijklmnop"
    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": secret,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [
                    _gene(
                        asset_id="g",
                        metadata={
                            marker: "safe",
                            "nested": {"safe": [f"again {secret}"]},
                        },
                    ),
                    _capsule(asset_id="c", gene="g"),
                ]
            ),
            "validate": lambda _m: {
                "ok": True,
                "status": 200,
                "body": {"payload": {"valid": True}},
            },
        }
    )

    code = await run_publish_command(
        ["--asset=g", "--asset=c", "--dry-run", "--json"], deps
    )
    payload = json.loads(buf.getvalue())
    text = json.dumps(payload)
    metadata = payload["payload"]["assets"][0]["metadata"]

    assert code == 0
    assert secret not in text
    assert marker not in text
    assert metadata["nested"]["safe"] == ["again [REDACTED]"]
    assert payload["blocked"] is False


async def test_publish_redacted_payload_remains_clean_and_validates() -> None:
    buf, deps = _capture()
    validated = {"called": False}

    async def _validate(message: dict[str, Any]) -> dict[str, Any]:
        validated["called"] = True
        assert message["payload"]["assets"][1]["summary"] != "secret=abcdefghijklmnop"
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [
                    _gene(asset_id="g"),
                    _capsule(asset_id="c", gene="g", summary="secret=abcdefghijklmnop"),
                ]
            ),
            "validate": _validate,
        }
    )
    code = await run_publish_command(
        ["--asset=g", "--asset=c", "--dry-run", "--json"], deps
    )
    payload = json.loads(buf.getvalue())

    assert code == 0
    assert payload["blocked"] is False
    assert payload["gates"]["leak"] == "pass"
    assert validated["called"] is True


async def test_publish_leak_gate_ignores_legacy_mode(
    monkeypatch: Any,
) -> None:
    for mode in ("warn", "off"):
        monkeypatch.setenv("EVOLVER_LEAK_CHECK", mode)
        buf, deps = _capture()
        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [
                        _gene(asset_id="g"),
                        _capsule(
                            asset_id="c",
                            gene="g",
                            summary="internal endpoint 10.1.2.3:8080",
                        ),
                    ]
                ),
            }
        )
        code = await run_publish_command(
            ["--asset=g", "--asset=c", "--dry-run", "--json"], deps
        )
        payload = json.loads(buf.getvalue())
        assert code == 0
        assert payload["blocked"] is True
        assert payload["block_reasons"] == ["leak_detected"]


async def test_publish_dry_run_missing_refs_does_not_create_asset_dir(
    tmp_path: Path,
) -> None:
    assets_dir = tmp_path / "missing"
    buf, deps = _capture()
    deps.update(
        {
            "assets_dir": assets_dir,
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
        }
    )
    code = await run_publish_command(
        ["--asset=missing-g", "--asset=missing-c", "--dry-run", "--json"],
        deps,
    )

    assert code == 1
    assert json.loads(buf.getvalue())["reason"] == "schema_invalid"
    assert not assets_dir.exists()


async def test_publish_invalid_json_response_preserves_stable_reason() -> None:
    buf, deps = _capture()
    calls = {"n": 0}

    async def _hub_fetch(_url: str, _opts: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        return {
            "ok": False,
            "status": 400,
            "text": lambda: '{"payload":{"reason":"unsupported"}}',
        }

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
            ),
            "hub_fetch": _hub_fetch,
        }
    )
    code = await run_publish_command(
        ["--asset=g", "--asset=c", "--dry-run", "--json"], deps
    )

    assert calls["n"] == 1
    assert code == 1
    assert json.loads(buf.getvalue())["reason"] == "unsupported"


async def test_publish_uses_node_secret_for_validate_and_publish() -> None:
    buf, deps = _capture()
    node_secret = "n" * 64
    oauth = "oauth-access-token"
    seen: list[tuple[str, str]] = []

    class _OauthA2a:
        build_publish_bundle = staticmethod(_fake_a2a().build_publish_bundle)

        @staticmethod
        def build_hub_headers() -> dict[str, str]:
            return {"Authorization": f"Bearer {oauth}"}

    async def _hub_fetch(url: str, opts: dict[str, Any]) -> dict[str, Any]:
        authorization = opts["headers"]["Authorization"]
        seen.append((url.rsplit("/", 1)[-1], authorization))
        body = (
            {"payload": {"valid": True}}
            if url.endswith("/validate")
            else {"payload": {"status": "accepted"}}
        )
        return {"ok": True, "status": 200, "body": body}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": node_secret,
            "a2a": _OauthA2a(),
            "asset_store": _FakeStore(
                [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
            ),
            "hub_fetch": _hub_fetch,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)

    assert code == 0
    assert seen == [
        ("validate", f"Bearer {node_secret}"),
        ("publish", f"Bearer {node_secret}"),
    ]
    assert json.loads(buf.getvalue())["status"] == "accepted"


async def test_publish_requires_node_secret_before_injected_validate() -> None:
    buf, deps = _capture()
    called = {"validate": False}

    async def _validate(_message: dict[str, Any]) -> dict[str, Any]:
        called["validate"] = True
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": None,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
            ),
            "validate": _validate,
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)

    assert code == 1
    assert called["validate"] is False
    assert json.loads(buf.getvalue())["reason"] == "auth_required"


async def test_publish_dry_run_rehashes_and_resigns_after_mutation() -> None:
    buf, deps = _capture()
    secret = "h" * 64
    seen: dict[str, Any] = {}

    class _Mutating:
        @staticmethod
        def build_publish_bundle(**kwargs: Any) -> dict[str, Any]:
            gene = dict(kwargs["gene"])
            capsule = dict(kwargs["capsule"])
            capsule.setdefault(
                "execution_trace",
                [{"step": 1, "stage": "build", "cmd": "node --test", "exit": 0}],
            )
            gene["asset_id"] = compute_asset_id(gene)
            capsule["asset_id"] = compute_asset_id(capsule)
            assets = [gene, capsule]
            return {
                "protocol": "gep-a2a",
                "protocol_version": "1.0.0",
                "message_type": "publish",
                "sender_id": kwargs.get("node_id"),
                "payload": {
                    "assets": assets,
                    "signature": _expected_signature(assets, secret),
                },
            }

        @staticmethod
        def build_hub_headers() -> dict[str, str]:
            return {}

    async def _validate(message: dict[str, Any]) -> dict[str, Any]:
        seen.update(message)
        return {"ok": True, "status": 200, "body": {"payload": {"valid": True}}}

    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": secret,
            "node_id": "node_preview",
            "a2a": _Mutating(),
            "asset_store": _FakeStore(
                [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
            ),
            "validate": _validate,
        }
    )
    code = await run_publish_command(
        ["--asset=g", "--asset=c", "--dry-run", "--json"], deps
    )
    assets = seen["payload"]["assets"]

    assert code == 0
    assert seen["sender_id"] == "node_preview"
    assert seen["payload"]["signature"] == _expected_signature(assets, secret)
    assert all(asset["asset_id"] == compute_asset_id(asset) for asset in assets)


async def test_publish_failure_hides_raw_error_and_lifecycle_status() -> None:
    buf, deps = _capture()
    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
            ),
            "validate": lambda _m: {
                "ok": True,
                "status": 200,
                "body": {"payload": {"valid": True}},
            },
            "publish": lambda _m: {
                "ok": False,
                "status": 500,
                "reason": "upstream token=abcdefghijklmnop",
                "body": {
                    "payload": {
                        "status": "accepted",
                        "error": "upstream token=abcdefghijklmnop",
                        "credits": {"required": 1},
                    }
                },
            },
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "network_error"
    assert payload["message"] == "Hub unreachable"
    assert "status" not in payload
    assert payload["credits"]["required"] == 1
    assert "abcdefghijklmnop" not in buf.getvalue()


async def test_publish_success_does_not_fabricate_status_or_receipt() -> None:
    buf, deps = _capture()
    deps.update(
        {
            "hub_url": "https://hub.test",
            "node_secret": "s" * 64,
            "a2a": _fake_a2a(),
            "asset_store": _FakeStore(
                [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
            ),
            "validate": lambda _m: {
                "ok": True,
                "status": 200,
                "body": {"payload": {"valid": True}},
            },
            "publish": lambda _m: {
                "ok": True,
                "status": 200,
                "body": {"payload": {"ok": True}},
            },
        }
    )
    code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
    payload = json.loads(buf.getvalue())

    assert code == 1
    assert payload["reason"] == "internal_error"
    assert "status" not in payload
    assert "receipt_id" not in payload


async def test_publish_rejects_non_a2a_decisions() -> None:
    for decision in ("ok", "approved"):
        buf, deps = _capture()
        deps.update(
            {
                "hub_url": "https://hub.test",
                "node_secret": "s" * 64,
                "a2a": _fake_a2a(),
                "asset_store": _FakeStore(
                    [_gene(asset_id="g"), _capsule(asset_id="c", gene="g")]
                ),
                "validate": lambda _m: {
                    "ok": True,
                    "status": 200,
                    "body": {"payload": {"valid": True}},
                },
                "publish": lambda _m, value=decision: {
                    "ok": True,
                    "status": 200,
                    "body": {"payload": {"decision": value}},
                },
            }
        )
        code = await run_publish_command(["--asset=g", "--asset=c", "--json"], deps)
        payload = json.loads(buf.getvalue())
        assert code == 1
        assert payload["reason"] == "internal_error"
        assert "status" not in payload


async def test_contract_json_redirects_dependency_stdout(
    capsys: Any,
    tmp_path: Path,
) -> None:
    fetched = _with_computed_asset_id(_gene())

    async def _fetch(_asset_id: str) -> dict[str, Any]:
        print("[fetch] dependency stdout")
        return fetched

    code = await run_reuse_command(
        ["--id", fetched["asset_id"], "--json"],
        {
            "assets_dir": tmp_path,
            "asset_store": _FakeStore([]),
            "fetch_asset_by_id": _fetch,
        },
    )
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()

    assert code == 0
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "ok"
    assert "[fetch]" not in captured.out
    assert "[fetch]" in captured.err


async def test_missing_json_rejects_before_dependency_output(
    capsys: Any,
) -> None:
    async def _fetch(_asset_id: str) -> None:
        print("[fetch] should not run")

    code = await run_reuse_command(
        ["--id", "sha256:x"],
        {"fetch_asset_by_id": _fetch},
    )
    captured = capsys.readouterr()

    assert code == 1
    assert json.loads(captured.out)["reason"] == "unsupported"
    assert "[fetch]" not in captured.out
    assert "[fetch]" not in captured.err
