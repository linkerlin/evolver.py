"""Multi-module TLS-enforcement consistency (Node hubUrlTlsEnforcementConsistency).

Pins the post-fix contract: hubFetch, ATP clients, config.resolve_hub_url,
and a2a post_hub_envelope all honour the same enforce-or-bypass posture.
"""

from __future__ import annotations

import pytest

from evolver import config
from evolver.atp import client as atp_client
from evolver.atp import hub_client
from evolver.config import enforce_hub_scheme, hub_allow_insecure, resolve_hub_base
from evolver.gep import a2a_protocol, hub_fetch


class TestEnforceHubScheme:
    def test_refuses_http_when_insecure_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        with pytest.raises(ValueError, match=r"(?i)must use https"):
            enforce_hub_scheme("http://hub.example/api")

    def test_refuses_non_url_when_insecure_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        with pytest.raises(ValueError, match=r"(?i)not a valid URL"):
            enforce_hub_scheme("::::not-a-url")

    def test_accepts_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        assert enforce_hub_scheme("https://hub.example/api") == "https://hub.example/api"

    def test_accepts_http_when_insecure_exactly_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
        assert hub_allow_insecure() is True
        assert enforce_hub_scheme("http://localhost:8080/api") == "http://localhost:8080/api"

    def test_only_literal_one_bypasses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("true", "yes", "0", "", " 1", "1 "):
            monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", val)
            assert hub_allow_insecure() is False
            with pytest.raises(ValueError, match=r"(?i)must use https"):
                enforce_hub_scheme("http://hub.example/api")

    def test_http_error_mentions_tls_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        with pytest.raises(ValueError, match=r"tls_refused"):
            enforce_hub_scheme("http://hub.example")


class TestResolveHubUrlConsistency:
    def test_resolve_uses_shared_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        monkeypatch.setenv("A2A_HUB_URL", "http://insecure.example")
        with pytest.raises(ValueError, match=r"(?i)must use https"):
            config.resolve_hub_url()

    def test_resolve_hub_base_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        with pytest.raises(ValueError, match=r"(?i)must use https"):
            resolve_hub_base("http://override.example")
        assert resolve_hub_base("https://ok.example") == "https://ok.example"


class TestHubFetchTls:
    def test_hub_fetch_refuses_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        with pytest.raises(ValueError, match=r"(?i)must use https|tls_refused"):
            hub_fetch.hub_fetch("http://hub.example/v1/a2a/hello")

    def test_hub_fetch_allows_https_past_scheme_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scheme accepted; network may still fail — we only assert no tls_refused."""
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        hub_fetch.reset_circuit_breaker()
        with pytest.raises(RuntimeError, match=r"Hub fetch failed"):
            hub_fetch.hub_fetch(
                "https://127.0.0.1:1/definitely-closed",
                max_retries=0,
                timeout=0.2,
                use_cache=False,
            )


class TestAtpClientTls:
    @pytest.mark.asyncio
    async def test_buy_refuses_http_hub_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        result = await atp_client.buy("skill_x", hub_url="http://hub.example")
        assert result["ok"] is False
        assert result.get("stage") == "tls"
        assert (
            "must use https" in result["error"].lower() or "tls_refused" in result["error"].lower()
        )

    @pytest.mark.asyncio
    async def test_complete_task_refuses_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        result = await atp_client.complete_task("task_1", hub_url="http://hub.example")
        assert result["ok"] is False
        assert "tls" in str(result.get("stage", "")).lower() or "https" in result["error"].lower()


class TestA2aPostEnvelopeTls:
    def test_post_hub_envelope_refuses_http_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        res = a2a_protocol.post_hub_envelope(
            "/v1/a2a/hello",
            {"type": "hello"},
            hub_url="http://hub.example",
        )
        assert res["ok"] is False
        body = res.get("body") or {}
        assert body.get("error") == "tls_refused"
        assert "https" in str(body.get("detail", "")).lower()

    def test_post_hub_envelope_env_http_no_hub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env http without insecure: get_hub_url returns None → no_hub_url."""
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        monkeypatch.setenv("A2A_HUB_URL", "http://hub.example")
        res = a2a_protocol.post_hub_envelope("/v1/a2a/hello", {"type": "hello"})
        assert res["ok"] is False
        # Either no_hub_url (get_hub_url swallows) or tls on override path
        err = (res.get("body") or {}).get("error")
        assert err in ("no_hub_url", "tls_refused")


class TestAtpHubClientTls:
    @pytest.mark.asyncio
    async def test_hub_client_post_refuses_env_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        monkeypatch.setenv("A2A_HUB_URL", "http://hub.example")
        monkeypatch.setenv("A2A_NODE_SECRET", "a" * 64)
        result = await hub_client.place_order("svc_1", budget=1.0)
        assert result["ok"] is False
        assert result.get("stage") == "tls" or result.get("code") == "tls_refused"
        assert "must use https" in str(result.get("error", "")).lower()
