"""Tests for evolver.experiment.llm (DeepSeek host client) — all offline.

The client is the host side of 经验即证据 §5.9: the engine never schedules
LLMs, but the ablation needs a real executor. What is pinned here is the
wiring contract — env resolution order, the request shape, the server-model
observation, and every failure mapping to ``LLMError`` (never a raw
``urllib`` exception, never a silent empty answer). No network: ``urlopen``
is a fake.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from evolver.experiment import llm
from evolver.experiment.llm import DeepSeekClient, LLMError


class FakeHTTPResponse:
    """Minimal context-manager stand-in for the urlopen response."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _ok_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": "deepseek-flash",
        "choices": [
            {
                "message": {"content": "solved def f", "reasoning_content": "scratch"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_APIKEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.delenv(key, raising=False)


def _fake_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any] | None = None,
    *,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Install a fake urlopen; return the dict that records what was sent."""
    seen: dict[str, Any] = {}

    def fake(req: Any, *, timeout: Any = None) -> FakeHTTPResponse:
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        if error is not None:
            raise error
        assert payload is not None
        return FakeHTTPResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen


def test_explicit_args_win_over_env(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example")
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    client = DeepSeekClient(api_key="k", base_url="https://x/", model="m")
    assert client.api_key == "k"
    assert client.base_url == "https://x"  # trailing slash stripped
    assert client.model == "m"


def test_env_fallback_chain(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_APIKEY", "second-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example/")
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    client = DeepSeekClient()
    assert client.api_key == "second-key"
    assert client.base_url == "https://env.example"
    assert client.model == "env-model"


def test_defaults_when_nothing_configured(_clean_env: None) -> None:
    client = DeepSeekClient()
    assert client.api_key == ""
    assert client.base_url == llm.DEFAULT_BASE_URL
    assert client.model == llm.DEFAULT_MODEL
    assert client.max_tokens == llm.DEFAULT_MAX_TOKENS
    assert client.timeout_s == llm.DEFAULT_TIMEOUT_S


def test_no_key_raises_before_network(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb(req: Any, *, timeout: Any = None) -> FakeHTTPResponse:
        raise AssertionError("must not touch the network without a key")

    monkeypatch.setattr(urllib.request, "urlopen", bomb)
    with pytest.raises(LLMError, match="no DEEPSEEK_API_KEY"):
        DeepSeekClient().complete([{"role": "user", "content": "hi"}])


def test_request_shape(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake_urlopen(monkeypatch, _ok_payload())
    client = DeepSeekClient(api_key="k", model="deepseek-flash", max_tokens=777)
    client.complete([{"role": "user", "content": "hi"}])
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["headers"]["Content-type"] == "application/json"
    assert seen["body"]["model"] == "deepseek-flash"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert seen["body"]["max_tokens"] == 777
    assert seen["timeout"] == llm.DEFAULT_TIMEOUT_S


def test_max_tokens_override_per_call(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake_urlopen(monkeypatch, _ok_payload())
    DeepSeekClient(api_key="k", max_tokens=777).complete(
        [{"role": "user", "content": "hi"}], max_tokens=11
    )
    assert seen["body"]["max_tokens"] == 11


def test_answer_usage_and_server_model(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_urlopen(monkeypatch, _ok_payload())
    client = DeepSeekClient(api_key="k")
    answer, usage = client.complete([{"role": "user", "content": "hi"}])
    # content is the answer; reasoning_content is scratch and never returned.
    assert answer == "solved def f"
    assert usage == {"prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    assert client.last_server_model == "deepseek-flash"


def test_missing_usage_and_model_are_zeros_not_errors(
    _clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _ok_payload()
    del payload["usage"]
    del payload["model"]
    _fake_urlopen(monkeypatch, payload)
    client = DeepSeekClient(api_key="k")
    answer, usage = client.complete([{"role": "user", "content": "hi"}])
    assert answer == "solved def f"
    assert usage == {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    assert client.last_server_model == ""


def test_malformed_response_raises(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_urlopen(monkeypatch, {"model": "deepseek-flash", "choices": []})
    with pytest.raises(LLMError, match="malformed LLM response"):
        DeepSeekClient(api_key="k").complete([{"role": "user", "content": "hi"}])


def test_empty_answer_raises(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _ok_payload()
    payload["choices"][0]["message"]["content"] = ""
    _fake_urlopen(monkeypatch, payload)
    with pytest.raises(LLMError, match="empty answer"):
        DeepSeekClient(api_key="k").complete([{"role": "user", "content": "hi"}])


def test_http_error_carries_status_and_truncated_detail(
    _clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fp = io.BytesIO(b'{"error": "auth failed"}')
    err = urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions", 401, "Unauthorized", {}, fp
    )
    _fake_urlopen(monkeypatch, None, error=err)
    with pytest.raises(LLMError, match=r"LLM HTTP 401.*auth failed"):
        DeepSeekClient(api_key="bad").complete([{"role": "user", "content": "hi"}])


def test_url_error_is_an_llm_error(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_urlopen(monkeypatch, None, error=urllib.error.URLError("down"))
    with pytest.raises(LLMError, match="LLM request failed"):
        DeepSeekClient(api_key="k").complete([{"role": "user", "content": "hi"}])


def test_complete_prompt_shapes_messages(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake_urlopen(monkeypatch, _ok_payload())
    client = DeepSeekClient(api_key="k")
    client.complete_prompt("write f", context="## Previous Episode\n- x")
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "## Previous Episode\n- x"},
        {"role": "user", "content": "write f"},
    ]
    client.complete_prompt("write g")
    assert seen["body"]["messages"] == [{"role": "user", "content": "write g"}]
