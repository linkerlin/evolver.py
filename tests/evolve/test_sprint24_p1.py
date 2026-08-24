"""Sprint 24.5: idempotency dedup, daemon stall watchdog, drain refusal."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import idempotency as idem


@pytest.fixture(autouse=True)
def _isolate(temp_workspace: Path) -> None:
    yield


class TestIdempotency:
    def test_once_fires_exactly_once(self) -> None:
        assert idem.once("c1", "tick")
        assert not idem.once("c1", "tick")
        assert idem.once("c2", "tick")  # different cycle → fires again

    def test_post_cycle_without_identity_ungated(self, temp_workspace: Path) -> None:
        """No cycle_id/run_id in ctx → tick must still run (no empty key)."""
        from unittest.mock import AsyncMock

        from evolver.atp import auto_buyer
        from evolver.evolve.post_cycle import run_post_cycle_hooks
        from evolver.gep.feature_flags import invalidate_cache, set_flag

        set_flag("enable_auto_buyer", True)
        invalidate_cache()
        try:
            run_tick = AsyncMock(return_value={"placed": 0})
            get_consent = lambda: {"enabled": True}  # noqa: E731
            orig_tick, orig_consent = auto_buyer.run_tick, auto_buyer.get_consent
            auto_buyer.run_tick = run_tick  # type: ignore[method-assign]
            auto_buyer.get_consent = get_consent  # type: ignore[method-assign]
            try:
                import asyncio

                asyncio.run(run_post_cycle_hooks({"signals": ["log_error"]}))
                assert run_tick.await_count == 1
            finally:
                auto_buyer.run_tick = orig_tick  # type: ignore[method-assign]
                auto_buyer.get_consent = orig_consent  # type: ignore[method-assign]
        finally:
            set_flag("enable_auto_buyer", False)
            invalidate_cache()

    def test_ttl_expiry(self) -> None:
        old = 0.0
        idem.mark_done("c1", "op", now=old)
        # Within TTL → deduped; past TTL → fires again.
        assert idem.already_done("c1", "op", now=86400.0)
        assert not idem.already_done("c1", "op", now=idem.IDEMPOTENCY_TTL_DAYS * 86400.0 + 1.0)

    def test_corrupt_lines_ignored(self) -> None:
        path = idem.idempotency_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken json\n", encoding="utf-8")
        assert idem.once("c1", "op")


class TestDaemonStallWatchdog:
    def test_no_progress_file_is_not_a_stall(self, temp_workspace: Path) -> None:
        from evolver.ops.health_check import daemon_stall_seconds

        assert daemon_stall_seconds(progress_path=temp_workspace / "missing.json") is None

    def test_staleness_measured(self, temp_workspace: Path) -> None:
        from evolver.ops.health_check import daemon_stall_seconds

        progress = temp_workspace / "cycle_progress.json"
        progress.write_text('{"updated_at": 1000}', encoding="utf-8")
        stall = daemon_stall_seconds(now_ms=301_000, progress_path=progress)
        assert stall == pytest.approx(300.0)

    def test_malformed_payload_returns_none(self, temp_workspace: Path) -> None:
        from evolver.ops.health_check import daemon_stall_seconds

        progress = temp_workspace / "cycle_progress.json"
        progress.write_text("[]", encoding="utf-8")
        assert daemon_stall_seconds(progress_path=progress) is None

    def test_health_report_includes_daemon_check(self, temp_workspace: Path) -> None:
        from evolver.gep.paths import get_cycle_progress_path
        from evolver.ops.health_check import run_health_check

        get_cycle_progress_path().parent.mkdir(parents=True, exist_ok=True)
        get_cycle_progress_path().write_text('{"updated_at": 1}', encoding="utf-8")
        report = run_health_check()
        names = [c.name for c in report.checks]
        assert "daemon_stall" in names


class TestDrainRefusal:
    def test_http_trigger_refused_while_draining(
        self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ) -> None:
        from evolver.ops import trigger as trigger_mod

        monkeypatch.setattr(trigger_mod, "_draining", lambda: True)
        verdict = trigger_mod.record_http_trigger(source="test")
        assert verdict == {"ok": False, "error": "draining"}
        assert not trigger_mod.check_http_trigger_allowed()

    def test_wait_for_trigger_returns_immediately_when_draining(
        self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ) -> None:
        import asyncio

        from evolver.ops import trigger as trigger_mod

        monkeypatch.setattr(trigger_mod, "_draining", lambda: True)
        result = asyncio.run(trigger_mod.wait_for_trigger(timeout=5))
        assert result is None

    def test_runner_exports_drain_state(self) -> None:
        from evolver.evolve import runner

        before = runner.is_draining()
        runner.request_shutdown()
        try:
            assert runner.is_draining() is True
        finally:
            runner._shutdown_requested = False
        assert isinstance(before, bool)


class TestFailureEventParity:
    """Sprint 24.6 (enable_failure_events): silent rejection paths land events."""

    def test_append_failure_event_flag_gated(self, temp_workspace: Path) -> None:
        from evolver.gep.asset_store import read_all_events
        from evolver.gep.feature_flags import invalidate_cache, set_flag
        from evolver.gep.solidify import _append_failure_event

        last_run: dict[str, object] = {
            "run_id": "r_fail",
            "selected_gene_id": "g1",
            "signals": ["log_error"],
            "mutation": {"category": "repair"},
        }

        set_flag("enable_failure_events", False)
        invalidate_cache()
        _append_failure_event(
            last_run, temp_workspace, blast_radius={"files": 1, "lines": 2}, error="x"
        )
        assert read_all_events() == []  # flag off → silent (v1.94 parity)

        set_flag("enable_failure_events", True)
        invalidate_cache()
        _append_failure_event(
            last_run, temp_workspace, blast_radius={"files": 1, "lines": 2}, error="y"
        )
        events = read_all_events()
        assert len(events) == 1
        assert events[0]["outcome"] == {"status": "failed", "score": 0.0, "error": "y"}
        assert events[0]["gene_id"] == "g1"
        set_flag("enable_failure_events", False)
