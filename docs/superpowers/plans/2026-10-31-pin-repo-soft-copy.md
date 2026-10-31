# Pin MCP host workspace + soft-default copy Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin mutation/`workspace_root` to the `evolver.py` product checkout via `EVOLVER_REPO_ROOT` (process cwd may stay `/workspace`), and make instrument/config/session copy match full-chain soft for drop/flat/regression (hard only secrets, `~/.evolver`/engine-protected paths, val_seal).

**Architecture:** `get_repo_root` already honors `EVOLVER_REPO_ROOT`. Today `get_workspace_root` prefers `OPENCLAW_WORKSPACE`/`WORKSPACE_DIR` and ignores the pin, so MCP on Grok Bot mutates `/workspace` scratch. Fix precedence so an explicit product pin wins for both repo and workspace roots; align swarm instrument + stale comments; extend session soft-accept tests for drop/flat/regression (accept path already calls `is_usability_soft_reason`, which includes those reasons — docstring lies). Document MCP launch env for box.

**Tech Stack:** Python 3.11+, pytest, existing `evolver.gep.paths` / `evolver.swarm` / `evolver.gep.evolution_session` / `evolver.bench.frozen_gate`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-31-pin-repo-soft-copy-design.md` (origin `db674c8`).
- Hard blocks only: secrets/credentials into repo or event payloads; mutations rewriting `~/.evolver` / engine-protected paths; `val_seal` breach.
- Soft + warnings: drop, flat, regression, no_baseline, pack_absent, unmeasured (already in `USABILITY_SOFT_REASONS`).
- No auto-commit of mutations; experience stays under `~/.evolver/workspaces/<id>/`.
- Do not migrate scratch workspace `c52ddf…` in this plan.
- Prefer TDD; keep diffs minimal; do not restructure large modules.

## File map

| File | Role |
|------|------|
| `src/evolver/gep/paths.py` | Pin: `EVOLVER_REPO_ROOT` / `EVOLVER_PROJECT_DIR` win for `get_workspace_root` |
| `tests/gep/test_paths_repo_pin.py` (new) | Tests for pin precedence |
| `src/evolver/swarm.py` | Instrument strings: remove hard-reject for drop/flat/regression |
| `src/evolver/config.py` | Comment sync |
| `src/evolver/gep/evolution_session.py` | Docstring sync for `accept` |
| `tests/test_gep_evolution_session.py` | Soft-accept drop/flat/regression |
| `tests/test_swarm_instrument_soft_copy.py` (new or extend) | Instrument must not claim drop/flat hard |
| `docs/...` / skill note | MCP env example for Grok Bot box |

---

### Task 1: Pin `get_workspace_root` to `EVOLVER_REPO_ROOT`

**Files:**
- Modify: `src/evolver/gep/paths.py` (`get_workspace_root`, docstring)
- Create: `tests/gep/test_paths_repo_pin.py`

**Interfaces:**
- Consumes: existing `get_repo_root()` env handling
- Produces: `get_workspace_root()` returns product path when `EVOLVER_REPO_ROOT` or `EVOLVER_PROJECT_DIR` is set, even if `WORKSPACE_DIR`/`OPENCLAW_WORKSPACE` point at scratch

- [ ] **Step 1: Write failing tests**

```python
# tests/gep/test_paths_repo_pin.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

from evolver.gep import paths as paths_mod


@pytest.fixture()
@pytest.fixture()
def product_and_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    product = tmp_path / "evolver.py"
    product.mkdir()
    (product / ".git").mkdir()
    scratch = tmp_path / "workspace"
    scratch.mkdir()
    (scratch / ".git").mkdir()
    monkeypatch.chdir(scratch)
    monkeypatch.setenv("WORKSPACE_DIR", str(scratch))
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(product))
    monkeypatch.setenv("EVOLVER_QUIET_PARENT_GIT", "1")
    return product.resolve(), scratch.resolve()


def test_workspace_root_follows_evolver_repo_root_over_workspace_dir(product_and_scratch):
    product, _scratch = product_and_scratch
    assert paths_mod.get_workspace_root() == product
    assert paths_mod.get_repo_root(_quiet=True) == product


def test_workspace_id_stable_on_product_pin(product_and_scratch, monkeypatch):
    product, _ = product_and_scratch
    wid = paths_mod.compute_workspace_id()
    monkeypatch.setenv("WORKSPACE_DIR", str(Path("/tmp/other-scratch")))
    assert paths_mod.compute_workspace_id() == wid
    assert wid == paths_mod.compute_workspace_id(product)
```

(Fix fixture decorator to `@pytest.fixture()` properly when implementing.)

- [ ] **Step 2: Run tests — expect FAIL** (workspace still scratch)

`pytest tests/gep/test_paths_repo_pin.py -v`

- [ ] **Step 3: Implement precedence**

Change `get_workspace_root` to:

```python
def get_workspace_root() -> Path:
    """Workspace root for mutation/state.

    Precedence: EVOLVER_REPO_ROOT / EVOLVER_PROJECT_DIR (product pin) →
    OPENCLAW_WORKSPACE / WORKSPACE_DIR → get_repo_root() → cwd.
    """
    pin = os.environ.get("EVOLVER_REPO_ROOT") or os.environ.get("EVOLVER_PROJECT_DIR")
    if pin and pin.strip():
        return Path(pin.strip()).expanduser().resolve()
    env = os.environ.get("OPENCLAW_WORKSPACE") or os.environ.get("WORKSPACE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    repo = get_repo_root()
    if repo:
        return repo
    return Path.cwd()
```

Ensure `compute_workspace_id` already prefers `EVOLVER_REPO_ROOT` (it does) — add assertion coverage only.

- [ ] **Step 4: pytest pass**

- [ ] **Step 5: Commit** `fix(paths): EVOLVER_REPO_ROOT pins workspace_root over WORKSPACE_DIR`

---

### Task 2: Instrument + config copy alignment

**Files:**
- Modify: `src/evolver/swarm.py` (~lines 158–162, 282–298, any “仍硬拒绝” for drop/flat/regression)
- Modify: `src/evolver/config.py` (~306–308 comments)
- Create or extend: `tests/test_swarm_instrument_soft_copy.py`

**Interfaces:**
- Consumes: `build_instrument_prompt(state)`
- Produces: prompt text that soft-continues drop/flat/regression; hard language only for secrets / `~/.evolver` / val_seal

- [ ] **Step 1: Failing test**

```python
def test_instrument_does_not_hard_reject_drop_flat_regression():
    from evolver.swarm import build_instrument_prompt
    text = build_instrument_prompt({"agent_name": "t", "workspace_root": "/x", "genes": 0, "capsules": 0, "pending_solidify": False, "bench_pack_gate": {"armed": False}, "train_ids": [], "supervision": {"state": "running"}, "hitl": {"mode": "off", "pending": 0}, "tick_count": 0})
    assert "drop/flat/regression" not in text or "soft" in text.lower()
    # Stronger: must not say 仍硬拒绝 next to drop/flat/regression
    import re
    assert not re.search(r"drop\s*/\s*flat\s*/\s*regression[^\n]*仍硬拒绝", text)
    assert "val_seal" in text or "secrets" in text.lower() or "密钥" in text or "~/.evolver" in text
```

(Adjust state keys until `build_instrument_prompt` renders without KeyError — mirror existing swarm tests.)

- [ ] **Step 2: FAIL expected**

- [ ] **Step 3: Edit strings** so soft-continue covers drop/flat/regression; hard list = secrets / protected `~/.evolver` / val_seal only. Sync `config.py` comments.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `docs(swarm): soft-default instrument matches USABILITY_SOFT_REASONS`

---

### Task 3: Session accept docstring + drop/flat/regression tests

**Files:**
- Modify: `src/evolver/gep/evolution_session.py` docstring on `accept`
- Modify: `tests/test_gep_evolution_session.py`

**Interfaces:**
- Consumes: `is_usability_soft_reason` / `enrich_soft_accept` (already wired)
- Produces: proven soft-accept for drop/flat/regression; docstring no longer claims they are hard

- [ ] **Step 1: Add tests** (pattern from `test_soft_accept_allows_no_baseline_with_warnings`)

```python
@pytest.mark.parametrize("reason", ["drop", "flat", "regression"])
def test_soft_accept_allows_fitness_soft_reasons(session, reason):
    # open candidate then accept with gate returning accept=False, reason=reason
    ...
    assert session.run["gate"]["soft_accept"] is True
    assert session.run["gate"]["accept"] is True
```

- [ ] **Step 2: Run — should PASS if code already soft; if FAIL, fix accept path**

- [ ] **Step 3: Fix docstring** to match full-chain soft

- [ ] **Step 4: Commit** `test(session): soft-accept drop/flat/regression; docstring sync`

---

### Task 4: MCP launch docs + operator note

**Files:**
- Modify: `docs/superpowers/specs/2026-10-31-pin-repo-soft-copy-design.md` (add “Operator: Grok Bot MCP” section) **or** short note under `docs/superpowers/plans/` / README swarm-quickstart if one exists
- Do **not** invent Grok Bot MCP UI clicks; document env:

```text
EVOLVER_REPO_ROOT=/workspace/evolver-research/evolver.py
EVOLVER_QUIET_PARENT_GIT=1
# optional: unset WORKSPACE_DIR for clarity; pin wins after Task 1 either way
command: uv --project /workspace/evolver-research/evolver.py run evolver mcp
cwd may remain /workspace
```

OMEN16: `EVOLVER_REPO_ROOT=C:\GitHub\evolver.py`

- [ ] **Step 1: Write the operator section with exact env**
- [ ] **Step 2: Commit** `docs: MCP pin env for product checkout`

---

### Task 5: Full verification

- [ ] `pytest tests/gep/test_paths_repo_pin.py tests/test_swarm_instrument_soft_copy.py tests/test_gep_evolution_session.py tests/bench/test_soft_acceptance.py -q`
- [ ] Broader: `pytest tests/gep/test_solidify_soft_default.py tests/bench/test_soft_acceptance.py -q` (no regressions)
- [ ] Open PR against `master` with summary mapping to spec acceptance criteria
- [ ] Note for host after merge: set MCP env, restart MCP, confirm `swarm_status.repo_root` is product path

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| Pin via EVOLVER_REPO_ROOT; cwd may stay /workspace | 1, 4 |
| Full-chain soft drop/flat/regression | 2, 3 |
| Hard only secrets / ~/.evolver / val_seal | 2 |
| Copy matches code | 2, 3 |
| Unit tests + acceptance | 1–5 |
| No scratch migration / no auto-commit | Global constraints |

## Self-review

- No TBD placeholders.
- Pin precedence is the actual root cause (`WORKSPACE_DIR` beat `EVOLVER_REPO_ROOT` for workspace_root).
- Session accept likely already soft via `USABILITY_SOFT_REASONS`; Task 3 proves it and fixes docs.
