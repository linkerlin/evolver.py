"""Tests for evolver.gep.a2a_protocol."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from evolver.gep import a2a_protocol as a2a
from evolver.gep.content_hash import verify_asset_id


def _fixed_id(monkeypatch: pytest.MonkeyPatch, node_id: str = "node_test123456") -> None:
    monkeypatch.setattr(a2a, "get_node_id", lambda: node_id)


def _no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a2a, "get_hub_node_secret", lambda: None)


def _secret(monkeypatch: pytest.MonkeyPatch, value: str = "s3cr3t") -> None:
    monkeypatch.setattr(a2a, "get_hub_node_secret", lambda: value)


@respx.mock
async def test_send_hello_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/hello").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    result = await a2a.send_hello()
    assert result["ok"] is True
    assert route.called


@respx.mock
async def test_send_hello_no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a2a, "get_hub_url", lambda: None)
    result = await a2a.send_hello()
    assert result["ok"] is False
    assert result["error"] == "no_hub_url"


@respx.mock
async def test_fetch_tasks_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/tasks").mock(
        return_value=Response(200, json={"tasks": [{"task_id": "t1", "title": "Fix bug"}]})
    )
    result = await a2a.fetch_tasks(signals=["log_error"])
    assert result["ok"] is True
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["task_id"] == "t1"
    assert route.called


@respx.mock
async def test_fetch_tasks_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    monkeypatch.setattr("evolver.config.HUB_FETCH_RETRY_BACKOFF_MS", 1)
    respx.post("https://mock.hub/v1/a2a/tasks").mock(side_effect=ConnectionError("nope"))
    result = await a2a.fetch_tasks()
    assert result["ok"] is False
    assert "nope" in result["error"]


@respx.mock
async def test_fetch_tasks_retries_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Living-memory friction f001 (hub_offline): one transient failure must
    not degrade the cycle to offline."""
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    monkeypatch.setattr("evolver.config.HUB_FETCH_RETRY_BACKOFF_MS", 1)
    route = respx.post("https://mock.hub/v1/a2a/tasks").mock(
        side_effect=[
            Response(500, json={"error": "boom"}),
            Response(200, json={"tasks": [{"task_id": "t9"}]}),
        ]
    )
    result = await a2a.fetch_tasks()
    assert result["ok"] is True
    assert result["tasks"][0]["task_id"] == "t9"
    assert route.call_count == 2


@respx.mock
async def test_fetch_tasks_no_retry_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    monkeypatch.setattr("evolver.config.HUB_FETCH_RETRIES", 0)
    route = respx.post("https://mock.hub/v1/a2a/tasks").mock(side_effect=ConnectionError("nope"))
    result = await a2a.fetch_tasks()
    assert result["ok"] is False
    assert route.call_count == 1


@respx.mock
async def test_submit_task_result_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/tasks/t1/result").mock(
        return_value=Response(200, json={"status": "accepted"})
    )
    result = await a2a.submit_task_result("t1", {"outcome": "success"})
    assert result["ok"] is True
    assert route.called


@respx.mock
async def test_consume_hub_events_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": [{"type": "directive", "body": "do X"}]})
    )
    result = await a2a.consume_hub_events()
    assert result["ok"] is True
    assert len(result["events"]) == 1
    assert route.called


# ---------------------------------------------------------------------------
# Protocol constants (Node a2aProtocol.test.js: protocol constants)
# ---------------------------------------------------------------------------


class TestProtocolConstants:
    def test_protocol_name(self) -> None:
        assert a2a.PROTOCOL_NAME == "gep-a2a"

    def test_six_valid_message_types(self) -> None:
        assert sorted(a2a.VALID_MESSAGE_TYPES) == [
            "decision",
            "fetch",
            "hello",
            "publish",
            "report",
            "revoke",
        ]


# ---------------------------------------------------------------------------
# build_message (Node: buildMessage)
# ---------------------------------------------------------------------------


class TestBuildMessage:
    @pytest.mark.parametrize("mtype", ["hello", "publish", "fetch", "report", "decision", "revoke"])
    def test_builds_valid_message(self, monkeypatch: pytest.MonkeyPatch, mtype: str) -> None:
        _fixed_id(monkeypatch)
        msg = a2a.build_message(message_type=mtype, payload={"k": "v"})
        assert msg["protocol"] == "gep-a2a"
        assert msg["protocol_version"] == "1.0.0"
        assert msg["message_type"] == mtype
        assert msg["sender_id"] == "node_test123456"
        assert re.match(r"^msg_\d+_[0-9a-f]{8}$", msg["message_id"])
        assert msg["payload"] == {"k": "v"}

    def test_rejects_invalid_message_type(self) -> None:
        with pytest.raises(ValueError, match="Invalid message type"):
            a2a.build_message(message_type="bogus")

    def test_dry_run_node_id_when_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(a2a, "get_node_id", lambda: None)
        msg = a2a.build_message(message_type="hello")
        assert msg["sender_id"] == a2a.DRY_RUN_NODE_ID

    def test_default_payload_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        msg = a2a.build_message(message_type="hello")
        assert msg["payload"] == {}


# ---------------------------------------------------------------------------
# build_fetch (Node: buildFetch)
# ---------------------------------------------------------------------------


class TestBuildFetch:
    def test_omits_optional_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        msg = a2a.build_fetch()
        payload = msg["payload"]
        for key in ("asset_type", "local_id", "asset_ids", "signals", "search_only"):
            assert key not in payload, f"{key} must be omitted when unset"

    def test_includes_provided_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        msg = a2a.build_fetch(asset_type="Gene", local_id="g1")
        assert msg["payload"]["asset_type"] == "Gene"
        assert msg["payload"]["local_id"] == "g1"

    def test_signals_only_when_non_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        assert "signals" not in a2a.build_fetch(signals=[])["payload"]
        assert "signals" not in a2a.build_fetch(signals=None)["payload"]
        assert a2a.build_fetch(signals=["log_error"])["payload"]["signals"] == ["log_error"]

    def test_search_only_only_for_exact_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        assert a2a.build_fetch(search_only=True)["payload"].get("search_only") is True
        assert "search_only" not in a2a.build_fetch(search_only=False)["payload"]
        assert "search_only" not in a2a.build_fetch(search_only=None)["payload"]

    def test_asset_ids_only_when_non_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        assert "asset_ids" not in a2a.build_fetch(asset_ids=[])["payload"]
        assert a2a.build_fetch(asset_ids=["sha256:abc"])["payload"]["asset_ids"] == ["sha256:abc"]


# ---------------------------------------------------------------------------
# build_publish (Node: buildPublish requires asset with type and id)
# ---------------------------------------------------------------------------


class TestBuildPublish:
    def test_requires_asset_with_type_and_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _no_secret(monkeypatch)
        for bad in (None, {}, {"type": "Gene"}, {"id": "g1"}, {"type": "Gene", "id": ""}):
            with pytest.raises(ValueError, match="asset must have type and id"):
                a2a.build_publish(asset=bad)

    def test_computes_asset_id_and_payload_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        asset = {"type": "Gene", "id": "g1", "category": "repair", "strategy": ["do x"]}
        msg = a2a.build_publish(asset=asset)
        assert msg["message_type"] == "publish"
        assert msg["payload"]["asset_type"] == "Gene"
        assert msg["payload"]["local_id"] == "g1"
        body = msg["payload"]["asset"]
        assert verify_asset_id(body, body["asset_id"]) is True
        assert "signature" not in msg["payload"]

    def test_signature_present_with_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _secret(monkeypatch)
        asset = {"type": "Gene", "id": "g1", "category": "repair", "strategy": ["do x"]}
        msg = a2a.build_publish(asset=asset)
        sig = msg["payload"]["signature"]
        assert len(sig) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", sig) is not None

    def test_capsule_without_trace_gets_synthesized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        capsule = {"type": "Capsule", "id": "c1", "content": "x" * 50}
        msg = a2a.build_publish(asset=capsule)
        trace = msg["payload"]["asset"]["execution_trace"]
        assert isinstance(trace, list) and trace
        assert trace[0]["stage"] == "build"

    def test_capsule_with_valid_trace_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        trace = [{"step": 1, "stage": "validate", "cmd": "node --version", "exit": 0}]
        capsule = {"type": "Capsule", "id": "c1", "content": "x" * 50, "execution_trace": trace}
        msg = a2a.build_publish(asset=capsule)
        assert msg["payload"]["asset"]["execution_trace"] == trace

    def test_gene_trace_not_synthesized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        gene = {"type": "Gene", "id": "g1", "category": "repair", "strategy": ["do x"]}
        msg = a2a.build_publish(asset=gene)
        assert "execution_trace" not in msg["payload"]["asset"]


# ---------------------------------------------------------------------------
# _synthesize_execution_trace / _bundle_signature (internal contracts)
# ---------------------------------------------------------------------------


class TestSynthesizeExecutionTrace:
    def test_validation_results_map_to_steps(self) -> None:
        trace = a2a._synthesize_execution_trace(
            {"type": "Capsule", "id": "c1"},
            {
                "results": [
                    {"cmd": "node --version", "ok": True},
                    {"command": "node t.js", "ok": False},
                ]
            },
        )
        assert trace == [
            {"step": 1, "stage": "validate", "cmd": "node --version", "exit": 0},
            {"step": 2, "stage": "validate", "cmd": "node t.js", "exit": 1},
        ]

    def test_non_dict_rows_skipped(self) -> None:
        trace = a2a._synthesize_execution_trace(
            {"type": "Capsule", "id": "c1"},
            {"results": ["junk", {"cmd": "node --version", "ok": True}]},
        )
        assert len(trace) == 1
        assert trace[0]["cmd"] == "node --version"

    def test_empty_results_falls_back_to_outcome(self) -> None:
        trace = a2a._synthesize_execution_trace(
            {"type": "Capsule", "id": "c1", "outcome": {"status": "failed"}},
            {"results": []},
        )
        assert trace == [{"step": 1, "stage": "build", "cmd": "node --test", "exit": 1}]

    def test_no_validation_falls_back_to_success(self) -> None:
        trace = a2a._synthesize_execution_trace({"type": "Capsule", "id": "c1"}, None)
        assert trace == [{"step": 1, "stage": "build", "cmd": "node --test", "exit": 0}]


class TestBundleSignature:
    def test_hmac_over_sorted_gene_capsule_ids(self) -> None:
        assets = [
            {"type": "Gene", "id": "g1", "asset_id": "sha256:bbb"},
            {"type": "Capsule", "id": "c1", "asset_id": "sha256:aaa"},
            {"type": "EvolutionEvent", "id": "e1", "asset_id": "sha256:ccc"},
        ]
        sig = a2a._bundle_signature(assets, "secret")
        expected = hmac.new(b"secret", b"sha256:aaa|sha256:bbb", hashlib.sha256).hexdigest()
        assert sig == expected

    def test_deterministic(self) -> None:
        assets = [{"type": "Gene", "id": "g1", "asset_id": "sha256:bbb"}]
        assert a2a._bundle_signature(assets, "k") == a2a._bundle_signature(assets, "k")


# ---------------------------------------------------------------------------
# build_publish_bundle (Node: buildPublish bundle path)
# ---------------------------------------------------------------------------


class TestBuildPublishBundle:
    def test_type_defaults_and_asset_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        msg = a2a.build_publish_bundle(gene={"id": "g1"}, capsule={"id": "c1"})
        assets = msg["payload"]["assets"]
        assert [a["type"] for a in assets] == ["Gene", "Capsule"]
        for asset in assets:
            assert verify_asset_id(asset, asset["asset_id"]) is True

    def test_optional_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        msg = a2a.build_publish_bundle(gene={"id": "g1"}, capsule={"id": "c1"}, event={"id": "e1"})
        types = [a["type"] for a in msg["payload"]["assets"]]
        assert types == ["Gene", "Capsule", "EvolutionEvent"]

    def test_capsule_trace_synthesized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        msg = a2a.build_publish_bundle(
            gene={"id": "g1"}, capsule={"id": "c1"}, validation={"results": []}
        )
        capsule = next(a for a in msg["payload"]["assets"] if a["type"] == "Capsule")
        assert isinstance(capsule.get("execution_trace"), list)
        assert capsule["execution_trace"]

    def test_signature_covers_bundle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _secret(monkeypatch, "k")
        msg = a2a.build_publish_bundle(gene={"id": "g1"}, capsule={"id": "c1"})
        assets = msg["payload"]["assets"]
        assert msg["payload"]["signature"] == a2a._bundle_signature(assets, "k")

    def test_sender_id_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        _no_secret(monkeypatch)
        msg = a2a.build_publish_bundle(
            gene={"id": "g1"}, capsule={"id": "c1"}, node_id="node_other"
        )
        assert msg["sender_id"] == "node_other"


# ---------------------------------------------------------------------------
# post_hub_envelope (Node: non-2xx sanitisation + error paths)
# ---------------------------------------------------------------------------


class TestPostHubEnvelope:
    @respx.mock
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        monkeypatch.setattr(a2a, "get_hub_url", lambda: "https://mock.hub")
        route = respx.post("https://mock.hub/a2a/publish").mock(
            return_value=Response(200, json={"ok": True})
        )
        result = a2a.post_hub_envelope("/a2a/publish", {"message_type": "publish"})
        assert result["ok"] is True
        assert result["status"] == 200
        assert result["body"] == {"ok": True}
        assert route.called

    @respx.mock
    def test_non_2xx_reported_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        monkeypatch.setattr(a2a, "get_hub_url", lambda: "https://mock.hub")
        respx.post("https://mock.hub/a2a/publish").mock(
            return_value=Response(400, json={"error": "bad"})
        )
        result = a2a.post_hub_envelope("/a2a/publish", {})
        assert result["ok"] is False
        assert result["status"] == 400

    @respx.mock
    def test_non_json_body_becomes_error_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        monkeypatch.setattr(a2a, "get_hub_url", lambda: "https://mock.hub")
        respx.post("https://mock.hub/a2a/publish").mock(return_value=Response(500, text="boom"))
        result = a2a.post_hub_envelope("/a2a/publish", {})
        assert result["status"] == 500
        assert result["body"] == {"error": "boom"}

    @respx.mock
    def test_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        monkeypatch.setattr(a2a, "get_hub_url", lambda: "https://mock.hub")
        respx.post("https://mock.hub/a2a/publish").mock(side_effect=httpx.ConnectError("down"))
        result = a2a.post_hub_envelope("/a2a/publish", {})
        assert result == {"ok": False, "status": 0, "body": {"error": "network_error"}}

    def test_no_hub_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        monkeypatch.setattr(a2a, "get_hub_url", lambda: None)
        result = a2a.post_hub_envelope("/a2a/publish", {})
        assert result == {"ok": False, "status": 0, "body": {"error": "no_hub_url"}}

    def test_tls_refused_on_http_scheme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fixed_id(monkeypatch)
        result = a2a.post_hub_envelope("/a2a/publish", {}, hub_url="http://insecure.hub")
        assert result["ok"] is False
        assert result["body"]["error"] == "tls_refused"


# ---------------------------------------------------------------------------
# read_node_id_file / non_persisted_node_id
# ---------------------------------------------------------------------------


class TestNodeIdFiles:
    def test_read_missing_file(self, tmp_path: Path) -> None:
        assert a2a.read_node_id_file(tmp_path / "nope") == ""

    def test_read_trimmed(self, tmp_path: Path) -> None:
        f = tmp_path / "node_id"
        f.write_text("  node_abcdef123456  \n", encoding="utf-8")
        assert a2a.read_node_id_file(f) == "node_abcdef123456"

    def test_non_persisted_env_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("A2A_NODE_ID", "node_env00000001")
        assert a2a.non_persisted_node_id() == "node_env00000001"

    def test_non_persisted_home_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("A2A_NODE_ID", raising=False)
        home = tmp_path / "home"
        home.mkdir()
        (home / "node_id").write_text("node_home00000001", encoding="utf-8")
        monkeypatch.setattr(a2a, "get_evolver_home", lambda: home)
        assert a2a.non_persisted_node_id() == "node_home00000001"

    def test_non_persisted_dry_run_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("A2A_NODE_ID", raising=False)
        monkeypatch.setattr(a2a, "get_evolver_home", lambda: tmp_path / "empty-home")
        monkeypatch.setattr(a2a, "get_repo_root", lambda: None)
        assert a2a.non_persisted_node_id() == a2a.DRY_RUN_NODE_ID


# ---------------------------------------------------------------------------
# unwrap_asset_from_message (Node: unwrapAssetFromMessage)
# ---------------------------------------------------------------------------


class TestUnwrapAssetFromMessage:
    def test_extracts_single_asset_from_publish(self) -> None:
        asset = {"type": "Gene", "id": "g1"}
        msg = {"protocol": "gep-a2a", "message_type": "publish", "payload": {"asset": asset}}
        assert a2a.unwrap_asset_from_message(msg) == asset

    def test_extracts_first_bundle_asset(self) -> None:
        msg = {
            "protocol": "gep-a2a",
            "message_type": "publish",
            "payload": {
                "assets": [
                    {"type": "Gene", "id": "g1"},
                    {"type": "Capsule", "id": "c1"},
                ]
            },
        }
        assert a2a.unwrap_asset_from_message(msg)["id"] == "g1"

    def test_plain_asset_passthrough(self) -> None:
        for asset in (
            {"type": "Gene", "id": "g1"},
            {"type": "Capsule", "id": "c1"},
            {"type": "EvolutionEvent", "id": "e1"},
        ):
            assert a2a.unwrap_asset_from_message(asset) == asset

    def test_null_for_unrecognized(self) -> None:
        for bad in (
            None,
            "text",
            42,
            {},
            {"type": "Other"},
            {"protocol": "gep-a2a", "message_type": "hello"},
        ):
            assert a2a.unwrap_asset_from_message(bad) is None

    def test_publish_without_asset_payload_returns_none(self) -> None:
        msg = {"protocol": "gep-a2a", "message_type": "publish", "payload": {}}
        assert a2a.unwrap_asset_from_message(msg) is None
