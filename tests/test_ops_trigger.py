"""Tests for ops/trigger.py.

Equivalent test source: test/trigger.test.js.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evolver.ops.trigger import (
    check_file_trigger,
    check_http_trigger_allowed,
    consume_file_trigger,
    create_file_trigger,
    record_http_trigger,
    wait_for_trigger,
)


@pytest.fixture
def isolated_trigger_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    monkeypatch.setenv("MEMORY_DIR", str(memory_dir))
    return memory_dir


class TestFileTrigger:
    def test_no_trigger(self, isolated_trigger_dir: Path) -> None:
        assert check_file_trigger() is False
        assert consume_file_trigger() is None

    def test_create_and_consume(self, isolated_trigger_dir: Path) -> None:
        result = create_file_trigger({"reason": "test"})
        assert result["ok"] is True
        assert check_file_trigger() is True

        payload = consume_file_trigger()
        assert payload is not None
        assert payload["source"] == "filesystem"
        assert payload["data"] == {"reason": "test"}
        assert check_file_trigger() is False

    def test_create_string_payload(self, isolated_trigger_dir: Path) -> None:
        create_file_trigger("manual trigger")
        payload = consume_file_trigger()
        assert payload is not None
        assert payload["data"] == "manual trigger"

    def test_consume_idempotent(self, isolated_trigger_dir: Path) -> None:
        create_file_trigger()
        consume_file_trigger()
        assert consume_file_trigger() is None


class TestHttpTrigger:
    def test_cooldown(self) -> None:
        # First trigger should succeed
        r1 = record_http_trigger(source="test")
        assert r1["ok"] is True

        # Immediate second trigger should fail due to cooldown
        r2 = record_http_trigger(source="test")
        assert r2["ok"] is False
        assert r2["error"] == "cooldown"
        assert "cooldown_remaining" in r2

    def test_allowed_after_cooldown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "evolver.ops.trigger._last_trigger_time",
            0.0,
            raising=False,
        )
        assert check_http_trigger_allowed() is True


class TestWaitForTrigger:
    @pytest.mark.asyncio
    async def test_timeout(self, isolated_trigger_dir: Path) -> None:
        result = await wait_for_trigger(timeout=0.1, check_interval=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_triggers_on_file(self, isolated_trigger_dir: Path) -> None:
        async def delayed_trigger() -> None:
            await asyncio.sleep(0.1)
            create_file_trigger({"reason": "async"})

        task = asyncio.create_task(delayed_trigger())
        result = await wait_for_trigger(timeout=1.0, check_interval=0.05)
        await task
        assert result is not None
        assert result["data"] == {"reason": "async"}
