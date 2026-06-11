"""Tests for evolver.proxy.extensions.skill_update_loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from evolver.proxy.extensions.skill_update_loop import SkillUpdateLoop
from evolver.proxy.extensions.skill_updater import create_skill_updater


async def test_loop_runs_process_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE", "true")
    calls = {"n": 0}

    async def _fake_process(*, auto_apply: bool = True) -> dict[str, Any]:
        calls["n"] += 1
        return {"ok": True, "applied": [], "auto_apply": auto_apply}

    updater = create_skill_updater(
        skills_dir=tmp_path / "skills",
        state_path=tmp_path / "state.json",
    )
    monkeypatch.setattr(updater, "process_updates", _fake_process)
    loop = SkillUpdateLoop(updater)
    loop.start(interval_sec=60)
    await asyncio.sleep(0.05)
    loop.stop()
    await asyncio.sleep(0.05)
    assert calls["n"] >= 1


async def test_loop_skips_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    async def _fake_process(*, auto_apply: bool = True) -> dict[str, Any]:
        calls["n"] += 1
        return {"ok": True, "applied": []}

    updater = create_skill_updater(
        skills_dir=tmp_path / "skills",
        state_path=tmp_path / "state.json",
    )
    updater.disable()
    monkeypatch.setattr(updater, "process_updates", _fake_process)
    loop = SkillUpdateLoop(updater)
    loop.start(interval_sec=0.05)
    await asyncio.sleep(0.1)
    loop.stop()
    assert calls["n"] == 0
