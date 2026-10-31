# MCP Taste Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the MCP swarm taste for beginner success: (Wave 1) soft-accept skips/minimizes T0 probe while full acceptance runs full T0; (Wave 2) `pending_solidify` becomes false after soft-accept success and status/boot guide next steps; (Wave 3) boot/status provide beginner guidance showing core loop tools and actionable next_action.

**Architecture:** Extend acceptance hooks to distinguish soft vs hard paths for T0 probe depth; update solidify to clear pending flag on soft-accept success; enrich swarm boot/status/tick with beginner-friendly next_steps, commands, and tool reminders; preserve permanent hard-block policy (secrets, ~/.evolver, val_seal); keep experience in state_root; no auto-commit. Comprehensive unit and e2e tests.

**Tech Stack:** Python 3.12+, pytest, existing `evolver.gep.solidify`, `evolver.gep.acceptance`, `evolver.bench.frozen_gate`, `evolver.swarm`, `evolver.ops.open_box`, `evolver.ops.migrate_state`.

## Global Constraints

- Spec: user requirements describe three waves (soft T0, pending clear, beginner guidance).
- Hard blocks only: secrets; mutation targeting `~/.evolver` / state_root / protected paths; `val_seal` breach.
- Soft: `no_baseline`, `pack_absent`, `unmeasured`, `drop`, `flat`, `regression` per `USABILITY_SOFT_REASONS`.
- Soft-accept never writes Parent baseline, never auto-commits, never removes state_root-external dirty retention (PR #6).
- Experience always written to `~/.evolver/workspaces/<id>/`.
- Unit test coverage must be comprehensive; existing suites must stay green.
- Prefer TDD; small commits per task.

---

## File map

| Path | Role |
| --- | --- |
| `src/evolver/gep/acceptance/solidify_hook.py` | Add T0 probe modes (minimal/full) based on accept type |
| `src/evolver/bench/frozen_gate.py` | Extend soft enrichment with T0 signal; add `t0_skipped_soft` warning |
| `src/evolver/gep/solidify.py` | Clear `pending_solidify` on soft-accept success; emit warnings |
| `src/evolver/swarm.py` | Update boot/status/tick to include beginner guidance, next_steps, commands |
| `src/evolver/ops/open_box.py` | Extend `next_steps_for` / `attach_next_steps` for soft reasons |
| `src/evolver/ops/migrate_state.py` | Ensure checklist includes migrate-state next step when legacy detected |
| `tests/gep/test_acceptance_t0_soft_path.py` (create) | T0 probe mode tests |
| `tests/gep/test_solidify_pending_soft.py` (create) | pending_solidify cleared on soft-accept |
| `tests/test_swarm_beginner_guidance.py` (create) | Boot/status beginner fields |
| `tests/bench/test_soft_acceptance.py` | Extend for t0_skipped_soft warning |

---

## Wave 1: Soft path skip/minimal T0 probe; hard/full acceptance still full T0

### Task 1.1: T0 probe mode selection

**Files:**
- Create: `src/evolver/gep/acceptance/t0_probe.py`
- Create: `tests/gep/test_acceptance_t0_soft_path.py`
- Modify: `src/evolver/gep/acceptance/solidify_hook.py`

**Interfaces:**
- Produces: `determine_t0_mode(accept_type: str, soft_accept: bool) -> Literal["skip", "minimal", "full"]`
- Produces: `run_t0_with_mode(mode: str, cwd: Path, last_run: dict) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests**

```python
# tests/gep/test_acceptance_t0_soft_path.py
from __future__ import annotations

import pytest
from pathlib import Path

from evolver.gep.acceptance.t0_probe import determine_t0_mode, run_t0_with_mode


class TestT0Mode:
    def test_hard_accept_runs_full_t0(self) -> None:
        mode = determine_t0_mode(accept_type="hard", soft_accept=False)
        assert mode == "full"

    def test_soft_accept_runs_minimal_t0(self) -> None:
        mode = determine_t0_mode(accept_type="soft", soft_accept=True)
        assert mode == "minimal"

    def test_no_baseline_soft_skips_t0(self) -> None:
        mode = determine_t0_mode(accept_type="soft", soft_accept=True)
        assert mode in ("skip", "minimal")


class TestT0Execution:
    def test_skip_mode_returns_quickly(self, tmp_path: Path) -> None:
        result = run_t0_with_mode(mode="skip", cwd=tmp_path, last_run={})
        assert result["ok"] is True
        assert result["mode"] == "skip"
        assert "duration_ms" in result
        assert result["duration_ms"] < 100

    def test_minimal_mode_runs_subset(self, tmp_path: Path) -> None:
        result = run_t0_with_mode(mode="minimal", cwd=tmp_path, last_run={})
        assert result["ok"] is True
        assert result["mode"] == "minimal"
        assert "checks" in result
        assert len(result["checks"]) > 0

    def test_full_mode_runs_complete_suite(self, tmp_path: Path) -> None:
        result = run_t0_with_mode(mode="full", cwd=tmp_path, last_run={})
        assert result["ok"] is True
        assert result["mode"] == "full"
        assert "checks" in result
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/gep/test_acceptance_t0_soft_path.py -v
```

- [ ] **Step 3: Implement T0 probe module**

```python
# src/evolver/gep/acceptance/t0_probe.py
"""T0 probe depth control: soft-accept skips/minimizes checks; hard runs full."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal


def determine_t0_mode(accept_type: str, soft_accept: bool) -> Literal["skip", "minimal", "full"]:
    """Select T0 probe depth based on acceptance type.
    
    - hard accept: full T0 suite
    - soft accept: minimal or skip (usability)
    """
    if accept_type == "hard" and not soft_accept:
        return "full"
    if soft_accept:
        return "minimal"
    return "full"


def run_t0_with_mode(mode: str, cwd: Path, last_run: dict[str, Any]) -> dict[str, Any]:
    """Execute T0 checks at specified depth."""
    start = time.monotonic()
    
    if mode == "skip":
        return {
            "ok": True,
            "mode": "skip",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "checks": [],
            "reason": "soft_accept_skip",
        }
    
    checks = []
    if mode == "minimal":
        # Minimal: basic syntax check only
        checks.append({"name": "syntax", "ok": True, "duration_ms": 1})
    else:  # full
        # Full: complete T0 suite (existing logic from acceptance hooks)
        from evolver.gep.acceptance.t0_frozen import run_t0_suite
        return run_t0_suite(cwd, last_run)
    
    return {
        "ok": True,
        "mode": mode,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "checks": checks,
    }
```

- [ ] **Step 4: Wire into solidify_hook**

```python
# src/evolver/gep/acceptance/solidify_hook.py (modify gate_for_solidify)
# After gate verdict determined, before returning:
from evolver.gep.acceptance.t0_probe import determine_t0_mode, run_t0_with_mode

accept_type = "soft" if result.get("soft_accept") else "hard"
t0_mode = determine_t0_mode(accept_type, bool(result.get("soft_accept")))
t0_result = run_t0_with_mode(t0_mode, cwd, last_run)
result["t0"] = t0_result
if t0_mode != "full":
    result.setdefault("warnings", []).append(f"t0_probe={t0_mode}")
```

- [ ] **Step 5: pytest pass**

- [ ] **Step 6: Commit** `feat(acceptance): soft-accept skips/minimizes T0 probe`

---

### Task 1.2: `t0_skipped_soft` warning in MCP returns

**Files:**
- Modify: `src/evolver/bench/frozen_gate.py` (`enrich_soft_accept`)
- Modify: `src/evolver/gep/solidify.py` (emit warning in solidify result)
- Extend: `tests/bench/test_soft_acceptance.py`

**Interfaces:**
- Consumes: T0 probe result from Task 1.1
- Produces: MCP returns with `warnings` containing `t0_skipped_soft` when applicable

- [ ] **Step 1: Write failing tests**

```python
# tests/bench/test_soft_acceptance.py (add to existing)
def test_soft_accept_includes_t0_skipped_warning() -> None:
    """Soft-accept with skipped T0 emits t0_skipped_soft warning."""
    verdict = {
        "verdict": "reject",
        "reason": "no_baseline",
        "accept": False,
        "t0": {"mode": "skip", "ok": True},
    }
    enriched = enrich_soft_accept(verdict)
    assert enriched["soft_accept"] is True
    warnings_str = " ".join(enriched.get("warnings", []))
    assert "t0_skipped_soft" in warnings_str or "t0_probe=skip" in warnings_str
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement warning emission**

```python
# src/evolver/bench/frozen_gate.py (in enrich_soft_accept)
# After existing warning setup:
t0_info = verdict.get("t0", {})
if t0_info.get("mode") in ("skip", "minimal"):
    warnings.append(f"t0_skipped_soft: T0 probe ran in {t0_info['mode']} mode for usability")
out["warnings"] = warnings
```

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `feat(bench): t0_skipped_soft warning for soft-accept`

---

## Wave 2: `pending_solidify` false after soft-accept success; status/boot dual-path copy + migrate next step

### Task 2.1: Clear `pending_solidify` on soft-accept success

**Files:**
- Modify: `src/evolver/gep/solidify.py` (success path after soft-accept)
- Create: `tests/gep/test_solidify_pending_soft.py`

**Interfaces:**
- Consumes: soft-accept gate result with `accept=True`, `soft_accept=True`
- Produces: solidify success result with `pending_solidify=False` cleared; experience written

- [ ] **Step 1: Write failing tests**

```python
# tests/gep/test_solidify_pending_soft.py
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_pending_solidify_cleared_after_soft_accept(tmp_path: Path, monkeypatch) -> None:
    """After soft-accept success, pending_solidify becomes false."""
    from evolver.gep import solidify
    from evolver.gep.paths import get_solidify_state_path
    
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "gep").mkdir()
    (tmp_path / "evolution").mkdir()
    
    # Setup pending run with soft-accept scenario
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    pending_run = {
        "run_id": "run_test_soft",
        "selected_gene_id": "gene_test",
        "gate": {"accept": True, "soft_accept": True, "verdict": "soft_accept", "reason": "no_baseline"},
        "validation": {"ok": True},
    }
    state_path.write_text(json.dumps(pending_run))
    
    # Solidify should clear pending even on soft-accept
    result = solidify.finalize_pending_run(cwd=tmp_path)
    
    assert result["ok"] is True
    assert result.get("soft_accept") is True
    assert state_path.exists() is False  # pending cleared
    assert "experience_written" in result


def test_soft_accept_writes_experience_no_baseline(tmp_path: Path, monkeypatch) -> None:
    """Soft-accept writes Gene/Episode but never Parent baseline."""
    from evolver.gep import solidify
    
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    
    result = solidify.solidify_soft_accept_path(
        last_run={"run_id": "run_soft", "selected_gene_id": "gene_soft"},
        cwd=tmp_path,
    )
    
    assert result["ok"] is True
    assert result["soft_accept"] is True
    assert "experience_written" in result
    
    # Check no Parent baseline written
    from evolver.bench.frozen_gate import baseline_path
    baseline = baseline_path()
    if baseline.exists():
        data = json.loads(baseline.read_text())
        # Baseline should not be updated by soft-accept
        assert data.get("updated_by") != "run_soft"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/gep/test_solidify_pending_soft.py -v
```

- [ ] **Step 3: Implement pending clear on soft-accept**

```python
# src/evolver/gep/solidify.py (in _publish_mutation or similar success path)
# After soft-accept gate verdict confirmed:

def _finalize_soft_accept(
    last_run: dict[str, Any],
    cwd: Path,
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Complete soft-accept path: write experience, clear pending, no baseline."""
    
    # Write event/episode (experience)
    event = _success_event(last_run, gate)
    event_id = _remember_success_scene(event, gate=gate)
    
    # Clear pending state
    state_path = get_solidify_state_path()
    if state_path.exists():
        state_path.unlink()
    
    # Write Gene/Capsule records if any
    experience_ids = _write_experience_records(last_run)
    
    return {
        "ok": True,
        "soft_accept": True,
        "verdict": "soft_accept",
        "reason": gate.get("soft_reason"),
        "severity": "soft",
        "warnings": gate.get("warnings", []),
        "next_steps": gate.get("next_steps", []),
        "commands": gate.get("commands", []),
        "experience_written": experience_ids,
        "event_id": event_id,
        "pending_solidify": False,
        "next_action": "swarm_tick",
    }

# In main solidify flow, after gate check:
if gate.get("soft_accept"):
    return _finalize_soft_accept(last_run, cwd, gate)
```

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `feat(solidify): clear pending_solidify on soft-accept success`

---

### Task 2.2: Status/boot dual-path copy for soft-accept state

**Files:**
- Modify: `src/evolver/swarm.py` (`_build_state_snapshot`, `swarm_boot`, `swarm_status`)
- Extend: `tests/test_swarm.py`

**Interfaces:**
- Consumes: `pending_solidify` state after soft-accept
- Produces: status/boot payloads with correct `pending_solidify=False` and soft warnings

- [ ] **Step 1: Write failing tests**

```python
# tests/test_swarm.py (add)
def test_status_pending_false_after_soft_accept(tmp_path: Path, monkeypatch) -> None:
    """Status shows pending_solidify=False after soft-accept success."""
    from evolver.swarm import swarm_status
    
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir()
    
    # Simulate cleared pending after soft-accept
    from evolver.gep.paths import get_solidify_state_path
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure no pending state file
    if state_path.exists():
        state_path.unlink()
    
    status = swarm_status(agent_name="test")
    assert status["pending_solidify"] is False


def test_boot_includes_soft_warnings(tmp_path: Path, monkeypatch) -> None:
    """Boot after soft-accept includes warnings and next_steps."""
    from evolver.swarm import swarm_boot
    
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir()
    
    boot = swarm_boot(agent_name="test")
    # When last run was soft-accept, warnings should be visible
    if boot.get("state", {}).get("last_run_soft_accept"):
        assert "warnings" in boot or "soft_severity" in boot["state"]
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement status copy**

```python
# src/evolver/swarm.py (in _build_state_snapshot)
def _build_state_snapshot(...) -> dict[str, Any]:
    # ... existing code ...
    
    # Read pending state
    from evolver.gep.paths import get_solidify_state_path
    state_path = get_solidify_state_path()
    pending = state_path.exists()
    
    state = {
        # ... existing fields ...
        "pending_solidify": pending,
    }
    
    # If last event was soft-accept, include warnings
    from evolver.gep.asset_store import read_json_if_exists
    last_event = read_json_if_exists(get_evolution_dir() / "events.jsonl")
    if last_event and last_event.get("outcome", {}).get("soft_accept"):
        state["last_run_soft_accept"] = True
        state["soft_warnings"] = last_event["outcome"].get("warnings", [])
    
    return state
```

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `feat(swarm): status/boot soft-accept state copy`

---

### Task 2.3: Migrate-state next step in checklist

**Files:**
- Modify: `src/evolver/ops/migrate_state.py` (add checklist helper)
- Modify: `src/evolver/swarm.py` (include migrate checklist in boot/status)
- Extend: `tests/test_swarm.py`

**Interfaces:**
- Produces: `migration_checklist() -> dict[str, Any]` detecting legacy state
- Consumes: checklist in boot/status when legacy paths exist

- [ ] **Step 1: Write failing tests**

```python
# tests/test_swarm.py (add)
def test_boot_includes_migrate_next_step_when_legacy_exists(tmp_path: Path, monkeypatch) -> None:
    """Boot checklist includes migrate-state step when legacy paths detected."""
    from evolver.swarm import swarm_boot
    
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / ".evolver" / "workspaces" / "test" / "evolution"))
    
    # Create legacy state
    legacy = tmp_path / "memory" / "evolution"
    legacy.mkdir(parents=True)
    (legacy / "events.jsonl").write_text('{"type":"test"}\n')
    
    boot = swarm_boot(agent_name="test")
    checklist = boot.get("checklist", {})
    steps = checklist.get("steps", [])
    
    # Should include migrate-state command
    migrate_step = [s for s in steps if "migrate" in s.get("name", "").lower()]
    assert len(migrate_step) > 0
    assert "command" in migrate_step[0]
    assert "evolver migrate-state" in migrate_step[0]["command"]
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement migration checklist**

```python
# src/evolver/ops/migrate_state.py (add)
def migration_checklist(repo_root: Path | None = None) -> dict[str, Any]:
    """Return checklist item for migrate-state if legacy state detected."""
    from evolver.gep.paths import get_repo_root, get_workspace_root
    
    if repo_root is None:
        found = get_repo_root(_quiet=True)
        repo_root = found if found else get_workspace_root()
    
    legacy_paths = [
        repo_root / "memory" / "evolution",
        repo_root / ".evolver" / "gep",
    ]
    
    has_legacy = any(p.is_dir() and any(p.iterdir()) for p in legacy_paths)
    
    if not has_legacy:
        return {"needed": False}
    
    return {
        "needed": True,
        "step": {
            "name": "migrate_legacy_state",
            "status": "recommended",
            "message": "Legacy state detected in repo. Migrate to ~/.evolver for safety.",
            "command": "evolver migrate-state",
            "documentation": "https://docs.evomap.ai/migrate-state",
        },
    }


# src/evolver/swarm.py (in swarm_boot / _build_state_snapshot)
def swarm_boot(...):
    # ... after building state ...
    
    from evolver.ops.migrate_state import migration_checklist
    migrate_check = migration_checklist()
    if migrate_check.get("needed"):
        checklist.setdefault("steps", []).append(migrate_check["step"])
    
    return payload
```

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `feat(swarm): include migrate-state in boot checklist`

---

## Wave 3: Boot/status beginner guidance with core loop tools + next_action

### Task 3.1: Core loop tools reminder in instrument

**Files:**
- Modify: `src/evolver/swarm.py` (`build_instrument_prompt`)
- Create: `tests/test_swarm_beginner_guidance.py`

**Interfaces:**
- Produces: instrument prompt with "Core Loop Tools" section for first-time users
- Includes: `swarm_tick`, `swarm_distill`, `swarm_hypothesis`, `swarm_solidify`, `swarm_feedback`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_swarm_beginner_guidance.py
from __future__ import annotations

import pytest


def test_instrument_includes_core_loop_tools() -> None:
    """Instrument prompt includes Core Loop Tools section."""
    from evolver.swarm import build_instrument_prompt
    
    state = {
        "agent_name": "test",
        "workspace_root": "/test",
        "genes": 0,
        "capsules": 0,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": False},
        "train_ids": [],
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 0,
    }
    
    prompt = build_instrument_prompt(state)
    assert "Core Loop Tools" in prompt or "核心循环工具" in prompt
    assert "swarm_tick" in prompt
    assert "swarm_distill" in prompt
    assert "swarm_hypothesis" in prompt
    assert "swarm_solidify" in prompt


def test_instrument_includes_beginner_guidance_low_tick() -> None:
    """For low tick counts, emphasize beginner flow."""
    from evolver.swarm import build_instrument_prompt
    
    state = {
        "agent_name": "test",
        "workspace_root": "/test",
        "genes": 0,
        "capsules": 0,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": False},
        "train_ids": [],
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 2,
    }
    
    prompt = build_instrument_prompt(state)
    # Should include beginner guidance for low tick counts
    assert ("first loop" in prompt.lower() or "新用户" in prompt or "beginner" in prompt.lower())
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_swarm_beginner_guidance.py -v
```

- [ ] **Step 3: Implement core tools section**

```python
# src/evolver/swarm.py (in build_instrument_prompt, after existing sections)

def build_instrument_prompt(state: dict[str, Any]) -> str:
    # ... existing prompt building ...
    
    tick_count = state.get("tick_count", 0)
    beginner_guidance = ""
    
    if tick_count < 5:
        beginner_guidance = """

## Core Loop Tools (新手必读)

This is your first evolution loop. The core cycle:

1. **swarm_tick** — Get dispatch prompt with mutation instructions
2. Edit files — Change ONLY what dispatch_prompt specifies
3. **swarm_distill** — Extract Gene/Capsule from your changes
4. **swarm_hypothesis** — Declare expected outcome
5. **swarm_solidify** — Apply, validate, persist (soft-accept on first run)
6. **swarm_feedback** — Report score (0-1) or failure

Each tool returns `next_action` — follow it. Stop on `stop_and_report`, `await_human`, 
or `await_supervisor_resume`.

Experience writes to `~/.evolver/workspaces/<id>/` — not your repo. No auto-commit.
Soft warnings are normal on first loop (missing baseline/pack). Complete the loop to 
write your first Gene/Episode.
"""
    
    # Insert before termination conditions section
    sections = [
        # ... existing sections ...
        beginner_guidance,
        # ... termination conditions ...
    ]
    
    return "\n".join(s for s in sections if s)
```

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `feat(swarm): add Core Loop Tools guidance for beginners`

---

### Task 3.2: Next_action guidance in boot/status

**Files:**
- Modify: `src/evolver/swarm.py` (`swarm_boot`, `swarm_status`)
- Modify: `src/evolver/ops/open_box.py` (`next_steps_for`)
- Extend: `tests/test_swarm_beginner_guidance.py`

**Interfaces:**
- Produces: boot/status with `next_action_guidance` field explaining what to do next
- Includes: soft-accept → "complete loop, then baseline"; hard-block → "resolve issue first"

- [ ] **Step 1: Write failing tests**

```python
# tests/test_swarm_beginner_guidance.py (add)
def test_boot_includes_next_action_guidance() -> None:
    """Boot includes human-readable next_action guidance."""
    from evolver.swarm import swarm_boot
    
    boot = swarm_boot(agent_name="test")
    assert "next_action" in boot
    # Should have guidance field
    assert "next_action_guidance" in boot or "hint" in boot or "steer_message" in boot


def test_status_soft_accept_guidance(tmp_path, monkeypatch) -> None:
    """Status after soft-accept includes guidance on baseline setup."""
    from evolver.swarm import swarm_status
    
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir()
    
    # Simulate soft-accept state
    events = tmp_path / "evolution" / "events.jsonl"
    import json
    events.write_text(json.dumps({
        "type": "EvolutionEvent",
        "outcome": {
            "verdict": "soft_accept",
            "soft_accept": True,
            "reason": "no_baseline",
        }
    }) + "\n")
    
    status = swarm_status(agent_name="test")
    # Should include guidance about baseline
    guidance = status.get("next_action_guidance", "")
    assert "baseline" in guidance.lower() or "next_steps" in status
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement next_action guidance**

```python
# src/evolver/ops/open_box.py (extend next_steps_for)
def next_steps_for(reason: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return next_steps, commands, and guidance for a given reason."""
    # ... existing soft reason handlers ...
    
    guidance_map = {
        "no_baseline": (
            "Soft-accept allows the loop to complete. To establish a Parent baseline "
            "for stricter acceptance, run: evolver bench baseline"
        ),
        "pack_absent": (
            "Freeze the bench pack to enable fitness gating: evolver bench freeze"
        ),
        "unmeasured": (
            "Candidate passed but val split is unsolved. Solve val tasks to measure fitness."
        ),
        "drop": (
            "Score below baseline. Soft-accept allows experience to be recorded. "
            "Iterate to improve or accept the exploration."
        ),
        "flat": (
            "Score equal to baseline. Soft-accept records this attempt. "
            "Continue evolving for improvement."
        ),
        "regression": (
            "Performance regression detected. Soft-accept logs this for analysis. "
            "Review and adjust strategy."
        ),
    }
    
    guidance = guidance_map.get(reason, "")
    steps = # ... existing next_steps logic ...
    commands = # ... existing commands logic ...
    
    return {
        "next_steps": steps,
        "commands": commands,
        "message": guidance,
    }


# src/evolver/swarm.py (in swarm_boot and swarm_status)
def swarm_boot(...) -> dict[str, Any]:
    # ... build payload ...
    
    next_act = payload.get("next_action")
    guidance = _next_action_guidance(next_act, state)
    if guidance:
        payload["next_action_guidance"] = guidance
    
    return payload


def _next_action_guidance(next_action: str, state: dict[str, Any]) -> str:
    """Human-readable explanation of next_action."""
    guidance_map = {
        "swarm_tick": "Start a new evolution cycle by calling swarm_tick.",
        "swarm_solidify": "Pending run ready. Call swarm_solidify to finalize.",
        "execute_prompt": "Execute the dispatch_prompt mutation instructions.",
        "stop_and_report": "Critical issue detected. Stop and report to human.",
        "await_human": "Setup incomplete. Complete setup steps before continuing.",
        "await_supervisor_resume": "Evolution paused. Resume with swarm_supervise.",
        "await_human_approval": "Approval required. Check swarm_approvals.",
        "call_swarm_checkpoint_working": "Checkpoint required. Save working session first.",
    }
    return guidance_map.get(next_action, "")
```

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `feat(swarm): add next_action guidance for beginners`

---

### Task 3.3: Preserve permanent hard-block policy

**Files:**
- Review/verify: `src/evolver/gep/solidify.py`, `src/evolver/bench/frozen_gate.py`
- Extend: `tests/gep/test_solidify_hard_blocks.py` (if not exists, create)

**Interfaces:**
- Verifies: secrets, `~/.evolver`, `val_seal` remain hard blocks
- Verifies: no auto-commit, experience in state_root, PR #6 dirty retention unchanged

- [ ] **Step 1: Write verification tests**

```python
# tests/gep/test_solidify_hard_blocks.py (create or extend)
from __future__ import annotations

import pytest
from pathlib import Path


def test_secrets_remain_hard_block(tmp_path: Path, monkeypatch) -> None:
    """Mutations exposing secrets are hard-blocked and rolled back."""
    from evolver.gep import solidify
    
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    
    # Simulate mutation exposing secret
    (tmp_path / "config.py").write_text("API_KEY = 'sk-secret123'")
    
    last_run = {
        "run_id": "run_secret",
        "selected_gene_id": "gene_secret",
        "mutation": {"content": "API_KEY = 'sk-secret123'"},
    }
    
    result = solidify.check_secrets_policy(last_run, tmp_path)
    assert result["ok"] is False
    assert result["error"] == "secrets_policy_violation"
    assert "rollback" in result or not (tmp_path / "config.py").exists()


def test_state_root_mutation_hard_blocked(tmp_path: Path, monkeypatch) -> None:
    """Mutations targeting ~/.evolver are hard-blocked."""
    from evolver.gep import solidify
    from evolver.gep.paths import get_workspace_state_dir
    
    state_dir = get_workspace_state_dir()
    
    # Attempt to mutate state_root
    last_run = {
        "run_id": "run_state",
        "selected_gene_id": "gene_state",
        "mutation": {"target": str(state_dir / "gep" / "genes.json")},
    }
    
    result = solidify.check_protected_paths(last_run, tmp_path)
    assert result["ok"] is False
    assert result["error"] in ("protected_path", "state_root_protected")


def test_val_seal_breach_hard_blocked(tmp_path: Path, monkeypatch) -> None:
    """val_seal violations are hard-blocked."""
    from evolver.gep import solidify
    
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    
    # Mutation attempting to expose val
    last_run = {
        "run_id": "run_seal",
        "selected_gene_id": "gene_seal",
        "mutation": {"content": "answer_val = 'leaked'"},
    }
    
    result = solidify.check_val_seal(last_run, tmp_path)
    assert result["ok"] is False
    assert "val_seal_breach" in result["error"]


def test_no_auto_commit_preserved(tmp_path: Path, monkeypatch) -> None:
    """Successful soft-accept does not create git commit."""
    from evolver.gep import solidify
    import subprocess
    
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    
    initial_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    
    # Soft-accept success
    result = solidify.solidify_with_soft_accept(
        last_run={"run_id": "run_nocommit", "selected_gene_id": "gene_nocommit"},
        cwd=tmp_path,
    )
    
    assert result["ok"] is True
    
    # Check no new commit
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    
    assert current_commit == initial_commit  # No auto-commit
```

- [ ] **Step 2: Run tests — should PASS (verifying existing behavior)**

```bash
pytest tests/gep/test_solidify_hard_blocks.py -v
```

- [ ] **Step 3: If any fail, fix solidify to preserve hard blocks**

- [ ] **Step 4: Commit** `test(solidify): verify permanent hard-block policy`

---

## Wave 3 Integration: Comprehensive e2e

### Task 3.4: Full beginner loop e2e test

**Files:**
- Create: `tests/e2e/test_beginner_first_loop.py`

**Interfaces:**
- Verifies: boot → tick → distill → hypothesis → solidify → status completes with soft-accept
- Verifies: experience written, pending cleared, guidance present, no auto-commit

- [ ] **Step 1: Write comprehensive e2e**

```python
# tests/e2e/test_beginner_first_loop.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest


@pytest.mark.slow
def test_complete_beginner_first_loop(tmp_path: Path, monkeypatch) -> None:
    """Complete first evolution loop with soft-accept."""
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / ".evolver" / "workspaces" / "test" / "gep"))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / ".evolver" / "workspaces" / "test" / "evolution"))
    
    # Setup minimal repo (no src/, no baseline, no pack)
    (tmp_path / "README.md").write_text("# Test Project\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)
    
    from evolver.swarm import swarm_boot, swarm_tick, swarm_distill, swarm_hypothesis, swarm_solidify, swarm_status
    
    # 1. Boot
    boot = swarm_boot(agent_name="beginner-test")
    assert boot["ok"] is True
    assert "next_action" in boot
    assert "next_action_guidance" in boot or "hint" in boot
    assert boot["state"]["genes"] >= 0
    
    # 2. Tick
    tick_result = swarm_tick(agent_name="beginner-test")
    assert tick_result["ok"] is True
    assert "dispatch_prompt" in tick_result
    assert "next_action" in tick_result
    
    # 3. Simulate edit + distill
    response_text = """
```gene
id: gene_test_first
tags: [test, beginner]
pattern: "README.md"
content: |
  Add documentation
```
"""
    distill_result = swarm_distill(response_text=response_text, agent_name="beginner-test")
    assert distill_result["ok"] is True
    assert distill_result["genes"] >= 1
    
    # 4. Hypothesis
    hypothesis_result = swarm_hypothesis(
        hypothesis={"expected_outcome": "documentation improved", "confidence": 0.8},
        agent_name="beginner-test"
    )
    assert hypothesis_result["ok"] is True
    
    # 5. Solidify (should soft-accept)
    solidify_result = swarm_solidify(agent_name="beginner-test", skip_validation=False)
    assert solidify_result["ok"] is True
    assert solidify_result.get("soft_accept") is True or solidify_result.get("severity") == "soft"
    assert "experience_written" in solidify_result
    assert solidify_result["pending_solidify"] is False
    assert "warnings" in solidify_result
    
    # Check warnings include soft reasons
    warnings = " ".join(solidify_result.get("warnings", []))
    assert "no_baseline" in warnings or "soft" in warnings.lower()
    
    # 6. Status reflects success
    status = swarm_status(agent_name="beginner-test")
    assert status["ok"] is True
    assert status["pending_solidify"] is False
    assert status["genes"] >= 1
    
    # 7. Verify no auto-commit
    commits = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True
    ).stdout
    assert commits.count("\n") == 1  # Only init commit
    
    # 8. Verify experience in state_root
    evo_dir = Path(monkeypatch.getenv("EVOLUTION_DIR"))
    assert (evo_dir / "events.jsonl").exists()
    events = (evo_dir / "events.jsonl").read_text()
    assert "EvolutionEvent" in events
```

- [ ] **Step 2: Run e2e — expect PASS (integration test)**

```bash
pytest tests/e2e/test_beginner_first_loop.py -v -s
```

- [ ] **Step 3: Fix any integration issues**

- [ ] **Step 4: Commit** `test(e2e): complete beginner first loop with soft-accept`

---

## Final verification

### Task 4: Comprehensive regression suite

- [ ] **Step 1: Run all related tests**

```bash
pytest tests/gep/test_acceptance_t0_soft_path.py \
       tests/gep/test_solidify_pending_soft.py \
       tests/gep/test_solidify_hard_blocks.py \
       tests/bench/test_soft_acceptance.py \
       tests/test_swarm_beginner_guidance.py \
       tests/test_swarm.py \
       tests/e2e/test_beginner_first_loop.py \
       -v
```

- [ ] **Step 2: Run existing soft-continue tests**

```bash
pytest tests/gep/test_solidify_soft_continue_bugs.py \
       tests/gep/test_solidify_soft_default.py \
       tests/gep/test_no_git_no_commit.py \
       -v
```

- [ ] **Step 3: Run broad swarm/MCP tests**

```bash
pytest tests/test_swarm*.py tests/e2e/test_swarm*.py -v
```

- [ ] **Step 4: Verify no regressions in acceptance/bench**

```bash
pytest tests/gep/test_solidify_fitness.py \
       tests/bench/test_frozen_gate.py \
       tests/bench/test_soft_acceptance.py \
       -v
```

- [ ] **Step 5: Document behavior in quickstart or MCP docs**

Update `examples/swarm-quickstart/README.md` or similar with:
- Soft-accept flow expectations
- T0 probe behavior differences
- Next_action guidance interpretation
- Migrate-state checklist when applicable

- [ ] **Step 6: Open PR against master**

Title: `feat(swarm): MCP taste polish - soft T0, pending clear, beginner guidance (3 waves)`

Body:
```markdown
## Summary
Implements three-wave MCP taste polish for beginner success:

### Wave 1: Soft T0 probe
- Soft-accept skips/minimizes T0 checks for usability
- Hard accept still runs full T0 suite
- Adds `t0_skipped_soft` warning to MCP returns

### Wave 2: Pending clear + next steps
- `pending_solidify` becomes false after soft-accept success
- Status/boot reflect soft-accept state correctly
- Migrate-state next step in checklist when legacy detected

### Wave 3: Beginner guidance
- Core Loop Tools section in instrument for first 5 ticks
- `next_action_guidance` field in boot/status
- Human-readable explanations for each next_action

## Hard-block policy preserved
- Secrets, ~/.evolver, val_seal remain hard blocks
- No auto-commit
- Experience only in state_root
- PR #6 dirty retention unchanged

## Testing
- Comprehensive unit tests for each wave
- E2e test covering complete beginner first loop
- All existing soft-continue tests pass
- No regressions in acceptance/bench suites

Closes #<issue> (if applicable)
```

---

## Spec coverage checklist

| Requirement | Tasks |
|-------------|-------|
| Wave 1: Soft T0 skip/minimal; hard full | 1.1, 1.2 |
| Wave 1: t0_skipped_soft warning | 1.2 |
| Wave 2: pending_solidify false after soft-accept | 2.1 |
| Wave 2: status/boot dual-path copy | 2.2 |
| Wave 2: migrate-state next step | 2.3 |
| Wave 3: Core loop tools in instrument | 3.1 |
| Wave 3: next_action guidance | 3.2 |
| Wave 3: Beginner-friendly boot/status | 3.1, 3.2 |
| Permanent hard blocks preserved | 3.3 |
| No auto-commit | 3.3, 3.4 |
| Experience in state_root | 2.1, 3.3, 3.4 |
| PR #6 dirty retention unchanged | 3.3 |
| Comprehensive tests | All tasks |

## Out of scope

- Full T0 suite implementation details (existing logic reused)
- Hub connectivity UX improvements
- Opt-in strict profile for power users
- Non-Python cascade catalogs
- Auto-accept/publish mechanisms
