"""DeepSeek LLM client — the host executor for the real-episode closed loop.

经验即证据 §5.9: the engine never builds its own LLM scheduling, but the HOST
does. This module is the host side — a thin OpenAI-compatible client over the
DeepSeek chat-completions endpoint, configured from ``DEEPSEEK_*`` env vars.

The model is a reasoning model (deepseek-v4-flash / v4-pro): the answer lands
in ``content`` after ``reasoning_content`` spends the budget, so ``max_tokens``
must leave room for both. The client returns the final answer text and the
token usage (for the cost panel).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Final

DEFAULT_BASE_URL: Final = "https://api.deepseek.com"
DEFAULT_MODEL: Final = "deepseek-v4-flash"
#: Reasoning models spend tokens before answering; leave headroom.
DEFAULT_MAX_TOKENS: Final = 4096
DEFAULT_TIMEOUT_S: Final = 120


class LLMError(RuntimeError):
    """The LLM call failed (network, auth, or malformed response)."""


class DeepSeekClient:
    """Minimal OpenAI-compatible chat client for the DeepSeek endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.api_key = (
            api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_APIKEY") or ""
        )
        self.base_url = (
            base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Return ``(answer_text, usage)`` for one chat completion.

        The answer is ``content`` (the final message); ``reasoning_content`` is
        the model's scratchpad and is not returned. Usage carries the token
        counts for the cost panel.
        """
        if not self.api_key:
            raise LLMError("no DEEPSEEK_API_KEY configured")
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens or self.max_tokens,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        try:
            choice = data["choices"][0]
            message = choice["message"]
            answer = str(message.get("content") or "")
            usage_raw = data.get("usage") or {}
            usage = {
                "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
                "output_tokens": int(usage_raw.get("completion_tokens", 0)),
                "total_tokens": int(usage_raw.get("total_tokens", 0)),
            }
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"malformed LLM response: {str(data)[:300]}") from exc
        if not answer:
            raise LLMError(f"LLM returned empty answer (finish={choice.get('finish_reason')})")
        return answer, usage

    def complete_prompt(
        self, prompt: str, *, context: str = "", max_tokens: int | None = None
    ) -> tuple[str, dict[str, int]]:
        """Convenience: a single user prompt with optional system context."""
        messages: list[dict[str, str]] = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})
        return self.complete(messages, max_tokens=max_tokens)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DeepSeekClient",
    "LLMError",
]
