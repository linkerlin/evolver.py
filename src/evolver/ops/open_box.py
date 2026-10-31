"""Open-box first-run readiness: diagnose, setup, doctor, actionable next steps.

Detects missing git / freeze pack / Parent baseline. Safely auto-fills what can
be filled (freeze pack). Never solves val or unlocks validation secrets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Error codes that MCP/CLI surfaces must carry ``next_steps``.
ACTIONABLE_ERRORS = (
    "not_a_git_repo",
    "hypothesis_missing",
    "no_baseline",
    "pack_absent",
    "unmeasured",
    "user_lock",
    "preflight_abort",
)

# Usability gaps: recommend filling, but soft-continue the swarm loop.
SOFT_GAP_ERRORS = frozenset({"pack_absent", "no_baseline", "unmeasured"})
# Hard roadblocks: doctor exit non-zero / ok=false until cleared.
HARD_BLOCKER_ERRORS = frozenset({"not_a_git_repo", "user_lock", "preflight_abort"})


def next_steps_for(error: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return actionable ``next_steps`` / ``commands`` for a known error code.

    Candidate conversations must never be told to decode or unlock val.
    """
    ctx = context or {}
    code = str(error or "").strip()
    # Normalize preflight reasons that embed user-lock text.
    lowered = code.lower()
    code = (
        "user_lock"
        if "user lock" in lowered or code == "user_lock"
        else (
            "user_lock"
            if (code.startswith("preflight") or "preflight_abort" in lowered)
            and "user lock" in lowered
            else (
                "preflight_abort"
                if code.startswith("preflight") or "preflight_abort" in lowered
                else code
            )
        )
    )

    catalog: dict[str, dict[str, Any]] = {
        "not_a_git_repo": {
            "message": (
                "Working directory is not a git repository. Solidify needs a git "
                "root. Point EVOLVER_REPO_ROOT / --project at a repo, or init one."
            ),
            "next_steps": [
                "Run `evolver doctor` to list nearby git candidates.",
                "Set EVOLVER_REPO_ROOT (or pass --project) to an existing git root.",
                "Or run `git init` only if this directory is meant to be the repo.",
                "Then re-run the failed command / swarm_solidify.",
            ],
            "commands": [
                "evolver doctor --json",
                "evolver setup --project <git-root>",
            ],
        },
        "hypothesis_missing": {
            "message": (
                "Solidify refused: no hypothesis was declared for this candidate. "
                "Call swarm_hypothesis (or pass hypothesis=) before swarm_solidify."
            ),
            "next_steps": [
                "Call swarm_hypothesis with hypothesis, dimension, mechanism_family, "
                "target_hook, and mechanism_check (train ids only — never val).",
                "Or pass the same hypothesis object into swarm_propose / swarm_solidify.",
                "Re-run swarm_solidify after ok=true from swarm_hypothesis.",
            ],
            "commands": [
                "evolver session hypothesis --help",
            ],
        },
        "no_baseline": {
            "message": (
                "Parent baseline missing (recommended). Soft-accept/publish may proceed "
                "with warnings; freeze pack, solve val sandboxes in a SEPARATE context "
                "(never in the candidate-writing chat), then measure for a trusted bar."
            ),
            "next_steps": [
                "Optional but recommended: ensure freeze pack exists "
                "(`evolver bench freeze` or `evolver doctor --fix`).",
                "In another context (not the candidate dialogue), write val sandboxes "
                "via `evolver bench prompt <task-id> --pack <pack>` — do NOT open sealed "
                "val secrets in the candidate conversation.",
                "Measure Parent: `evolver bench baseline` (soft-accept will NOT invent this).",
                "Continue swarm_tick / swarm_solidify / session accept; warnings stay until baseline exists.",
            ],
            "commands": [
                "evolver doctor --fix",
                "evolver bench freeze",
                "evolver bench baseline",
                "evolver doctor",
            ],
        },
        "pack_absent": {
            "message": (
                "Frozen charter pack is not installed (recommended). Soft-accept/publish "
                "may proceed with warnings; install the pack for a real fitness bar."
            ),
            "next_steps": [
                "Recommended: `evolver doctor --fix` or `evolver bench freeze` to install the pack.",
                "Then prepare val sandboxes in another context and run `evolver bench baseline`.",
                "You may continue swarm / soft-accept now; doctor loop_ready stays false until ready.",
            ],
            "commands": [
                "evolver doctor --fix",
                "evolver bench freeze",
            ],
        },
        "unmeasured": {
            "message": (
                "Val sandboxes are unmeasured (recommended to fill). Soft-accept/publish "
                "may proceed with warnings; do not open sealed val in the candidate chat."
            ),
            "next_steps": [
                "In another context, solve pending val tasks into sandboxes/r1 and sandboxes/r2.",
                "Do NOT open sealed val material in the candidate-writing dialogue.",
                "Re-run swarm_solidify after sandboxes are filled; soft-accept allowed before that.",
            ],
            "commands": [
                "evolver doctor",
                "evolver bench baseline",
            ],
        },
        "user_lock": {
            "message": (
                "User lock is active (another evolver process holds exclusive control). "
                "Wait for it to expire/release, or stop the holder."
            ),
            "next_steps": [
                "Check `evolver status` / supervise panel for a running daemon or soak.",
                "If you started it: `evolver stop` or remove the stale lock only when sure "
                "no process holds it (default ~/.evolver/user.lock or $EVOLVER_USER_LOCK).",
                "Re-run the tick / cycle after the lock clears.",
            ],
            "commands": [
                "evolver status",
                "evolver stop",
                "evolver doctor",
            ],
        },
        "preflight_abort": {
            "message": (
                "Preflight aborted this cycle. A snapshot was persisted; next cycle "
                "injects repair bias until the blocker is cleared."
            ),
            "next_steps": [
                "Read abort reason from the tick result / autopoiesis_preflight_abort.json.",
                "If reason is user lock: follow user_lock next steps.",
                "Clear the blocker, then swarm_tick again (or `evolver run`).",
                "Run `evolver doctor` to confirm gate and lock health.",
            ],
            "commands": [
                "evolver doctor",
                "evolver status",
            ],
        },
    }

    base = catalog.get(code)
    if base is None:
        return {
            "error": code or "unknown",
            "message": ctx.get("message") or f"Unrecognized error: {code or 'unknown'}",
            "next_steps": [
                "Run `evolver doctor` for readiness diagnostics.",
                "See examples/swarm-quickstart/README.md.",
            ],
            "commands": ["evolver doctor --json"],
        }

    out = {
        "error": code,
        "message": base["message"],
        "next_steps": list(base["next_steps"]),
        "commands": list(base["commands"]),
    }
    # Attach discoverable git candidates when relevant.
    if code == "not_a_git_repo":
        candidates = ctx.get("candidates")
        if candidates:
            out["candidates"] = list(candidates)
            out["next_steps"] = [
                f"Found git candidates: {candidates}. Set EVOLVER_REPO_ROOT to one of them.",
                *out["next_steps"],
            ]
    if code == "no_baseline" and ctx.get("pending_tasks"):
        out["pending_tasks"] = list(ctx["pending_tasks"])
        out["next_steps"] = [
            "Val sandboxes incomplete (pending_tasks listed). Fill them in another "
            "context — never in the candidate-writing dialogue.",
            *out["next_steps"],
        ]
    return out


def _check_git(project: Path | None) -> dict[str, Any]:
    from evolver.gep.git_ops import is_git_repo
    from evolver.gep.paths import discover_git_candidates, get_repo_root

    cwd = (project or Path.cwd()).expanduser().resolve()
    root = get_repo_root(cwd)
    ok = bool(root is not None and is_git_repo(root))
    candidates = [] if ok else discover_git_candidates(cwd)
    return {
        "id": "git",
        "ok": ok,
        "cwd": str(cwd),
        "repo_root": str(root) if root else None,
        "candidates": candidates,
        "error": None if ok else "not_a_git_repo",
    }


def _check_pack() -> dict[str, Any]:
    from evolver.bench.frozen_gate import frozen_pack_path, load_frozen_pack

    loaded = load_frozen_pack()
    path = frozen_pack_path()
    if loaded is None:
        return {
            "id": "freeze_pack",
            "ok": False,
            "path": str(path),
            "error": "pack_absent",
            "auto_fillable": True,
        }
    _tasks, digest = loaded
    return {
        "id": "freeze_pack",
        "ok": True,
        "path": str(path),
        "digest": digest,
        "error": None,
        "auto_fillable": False,
    }


def _check_baseline() -> dict[str, Any]:
    from evolver.bench.frozen_gate import load_baseline, load_frozen_pack

    if load_frozen_pack() is None:
        return {
            "id": "parent_baseline",
            "ok": False,
            "error": "pack_absent",
            "baseline": None,
            "auto_fillable": False,
            "note": "Install freeze pack before measuring Parent baseline.",
        }
    baseline = load_baseline()
    if baseline is None:
        return {
            "id": "parent_baseline",
            "ok": False,
            "error": "no_baseline",
            "baseline": None,
            "auto_fillable": False,  # needs val sandboxes from another context
            "note": (
                "Solve val sandboxes in a SEPARATE context, then "
                "`evolver bench baseline`. Candidate dialogues must not open sealed val material."
            ),
        }
    return {
        "id": "parent_baseline",
        "ok": True,
        "error": None,
        "baseline": float(baseline["score"]),
        "pack_digest": baseline.get("pack_digest"),
        "auto_fillable": False,
    }


def _check_user_lock() -> dict[str, Any]:
    import os

    from evolver.evolve.guards import evaluate_user_lock
    from evolver.gep.paths import get_evolver_state_root

    raw = os.environ.get("EVOLVER_USER_LOCK", "").strip()
    path = Path(raw) if raw else (get_evolver_state_root() / "user.lock")
    if not path.is_file():
        return {"id": "user_lock", "ok": True, "path": str(path), "error": None}
    ev = evaluate_user_lock(path)
    return {
        "id": "user_lock",
        "ok": not ev.yield_required,
        "path": str(path),
        "age_ms": ev.age_ms,
        "reason": ev.reason,
        "error": "user_lock" if ev.yield_required else None,
    }


def diagnose(*, project: str | Path | None = None) -> dict[str, Any]:
    """First-run readiness snapshot (git / pack / baseline / user lock)."""
    from evolver.gep.paths import (
        compute_workspace_id,
        get_evolver_state_root,
        get_workspace_state_dir,
    )

    proj = Path(project).expanduser().resolve() if project else None
    if proj is not None:
        import os

        os.environ.setdefault("EVOLVER_REPO_ROOT", str(proj))

    checks = [
        _check_git(proj),
        _check_pack(),
        _check_baseline(),
        _check_user_lock(),
    ]
    failed = [c for c in checks if not c.get("ok")]
    soft_gap_checks = [
        c for c in failed if str(c.get("error") or "") in SOFT_GAP_ERRORS
    ]
    hard_checks = [
        c for c in failed if str(c.get("error") or "") not in SOFT_GAP_ERRORS
    ]
    loop_ready = all(
        c.get("ok") for c in checks if c["id"] in ("git", "freeze_pack", "parent_baseline")
    )
    lock_ok = next(c for c in checks if c["id"] == "user_lock").get("ok")
    git_ok = next(c for c in checks if c["id"] == "git").get("ok")
    # Soft-continue when git is usable and no hard lock/roadblock — pack/baseline
    # gaps remain recommended fill-ins, not stop-the-world blockers.
    soft_continue = bool(git_ok and lock_ok and not hard_checks)
    repo_root = next(c for c in checks if c["id"] == "git").get("repo_root")

    def _enrich(c: dict[str, Any]) -> dict[str, Any]:
        err = str(c.get("error") or "")
        payload = {
            "id": c["id"],
            **next_steps_for(err or "unknown", context=c),
        }
        if err in SOFT_GAP_ERRORS:
            payload["severity"] = "soft"
            payload["gap"] = err
            # Doctor recommendations keep the code under gap/severity; hosts that
            # only treat top-level MCP ``error`` as hard stop are covered by
            # apply_soft_gap. Keep ``error`` here for check-id stability.
            payload["error"] = err
        else:
            payload["severity"] = "hard"
            payload["error"] = c.get("error")
        return payload

    state = {
        # ok tracks soft-continue (hosts may proceed); loop_ready stays honest.
        "ok": soft_continue,
        "soft_continue": soft_continue,
        "loop_ready": bool(loop_ready and lock_ok),
        "repo_root": repo_root,
        "workspace_id": compute_workspace_id(repo_root) if repo_root else None,
        "state_root": str(
            get_workspace_state_dir(repo_root) if repo_root else get_evolver_state_root()
        ),
        "checks": checks,
        "blockers": [_enrich(c) for c in hard_checks if c.get("error")],
        "recommendations": [_enrich(c) for c in soft_gap_checks if c.get("error")],
        "auto_evolution": {
            "when_ready": (
                "MCP: swarm_boot → swarm_tick → execute → swarm_distill → "
                "swarm_hypothesis → swarm_solidify → swarm_feedback"
            ),
            "cli_demo": "uv run python examples/swarm-quickstart/demo_swarm_loop.py",
            "host_round": "evolver round --host",
            "note": (
                "Mutate/execute is host-side. Engine tools cover tick/distill/"
                "hypothesis/solidify/feedback. Do not solve val in the candidate chat. "
                "Missing pack/baseline: soft-continue with warnings (not a hard stop)."
            ),
        },
    }
    if not state["loop_ready"]:
        state["setup_path"] = (
            "recommended (soft-continue ok): evolver setup   # or: evolver doctor --fix"
        )
    return state


def doctor(*, fix: bool = False, project: str | Path | None = None) -> dict[str, Any]:
    """Diagnose readiness; with ``fix=True``, safely auto-fill freeze pack only.

    Never establishes a Parent baseline by inventing val answers. If sandboxes
    are already complete, ``fix`` may attempt ``establish_parent_baseline``.
    """
    report = diagnose(project=project)
    actions: list[dict[str, Any]] = []
    if fix:
        pack_check = next(c for c in report["checks"] if c["id"] == "freeze_pack")
        if not pack_check.get("ok"):
            from evolver.bench.frozen_gate import freeze_charter_pack

            frozen = freeze_charter_pack(force=False)
            actions.append({"action": "freeze_charter_pack", "result": frozen})
        # Re-check pack after freeze, then try baseline only if measurable.
        report = diagnose(project=project)
        base_check = next(c for c in report["checks"] if c["id"] == "parent_baseline")
        pack_ok = next(c for c in report["checks"] if c["id"] == "freeze_pack").get("ok")
        if pack_ok and not base_check.get("ok"):
            from evolver.bench.frozen_gate import establish_parent_baseline

            baselined = establish_parent_baseline()
            actions.append({"action": "establish_parent_baseline", "result": baselined})
            # If unmeasured, attach pending_tasks into blockers next_steps — never
            # invent answers and never instruct unlocking val in-candidate.
            if not baselined.get("ok") and baselined.get("reason") == "unmeasured":
                actions.append(
                    {
                        "action": "baseline_blocked",
                        "reason": "unmeasured",
                        "pending_tasks": baselined.get("pending_tasks") or [],
                        "guidance": next_steps_for(
                            "no_baseline",
                            context={"pending_tasks": baselined.get("pending_tasks") or []},
                        ),
                    }
                )
            report = diagnose(project=project)

    report["fix"] = fix
    report["actions"] = actions
    # Keep diagnose soft-continue ok (do not force ok=false solely for pack/baseline gaps).
    report["ok"] = bool(report.get("soft_continue", report.get("ok")))
    return report


def setup(*, project: str | Path | None = None) -> dict[str, Any]:
    """First-run entry: ``doctor(fix=True)``."""
    return doctor(fix=True, project=project)


def attach_next_steps(result: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    """Merge ``next_steps`` into an error/result dict (idempotent)."""
    if not isinstance(result, dict):
        return result
    code = error or result.get("error") or result.get("reason")
    if not code:
        if result.get("preflight_aborted"):
            abort_reason = str(result.get("abort_reason") or "preflight_abort")
            code = "user_lock" if "user lock" in abort_reason.lower() else "preflight_abort"
        else:
            return result
    if result.get("next_steps") and result.get("commands"):
        return result
    payload = next_steps_for(str(code), context=result.get("suggested_actions") or result)
    merged = {**result}
    merged.setdefault("error", payload["error"] if result.get("error") else result.get("error"))
    if not merged.get("error") and result.get("reason"):
        pass  # keep reason; still attach steps
    merged["next_steps"] = payload["next_steps"]
    merged["commands"] = payload["commands"]
    if payload.get("message") and not merged.get("hint"):
        merged["hint"] = payload["message"]
    for key in ("candidates", "pending_tasks"):
        if key in payload:
            merged[key] = payload[key]
    return merged


def apply_soft_gap(result: dict[str, Any], gap: str) -> dict[str, Any]:
    """Attach a usability soft-gap without a hard ``error`` field.

    Hosts that stop solely when ``error`` is set must continue. Soft gaps
    expose ``gap`` / ``gate_gap`` / ``reason`` / ``severity=soft`` /
    ``gate_soft_continue`` / ``warning`` / ``next_steps`` / ``commands``.
    Dangerous gates keep using ``attach_next_steps`` with ``error``.
    """
    code = str(gap or "").strip()
    if code not in SOFT_GAP_ERRORS:
        hard = {
            **result,
            "error": code or result.get("error"),
            "reason": code or result.get("reason"),
            "severity": "hard",
        }
        out = attach_next_steps(hard, error=code or None)
        out.setdefault("severity", "hard")
        return out

    steps = next_steps_for(code, context=result.get("suggested_actions") or result)
    out = {**result}
    # Soft gaps must not live in ``error`` — that field is the hard-stop signal.
    if out.get("error") in SOFT_GAP_ERRORS:
        out.pop("error", None)
    out["gap"] = code
    out["gate_gap"] = code
    out["reason"] = code
    out["severity"] = "soft"
    out["gate_soft_continue"] = True
    out["gate_ready"] = False
    warning = str(steps.get("message") or f"soft-continue ({code})")
    out["warning"] = warning
    if not out.get("hint"):
        out["hint"] = warning
    out["next_steps"] = list(steps.get("next_steps") or [])
    out["commands"] = list(steps.get("commands") or [])
    for key in ("candidates", "pending_tasks"):
        if key in steps:
            out[key] = steps[key]
    warnings = list(out.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
    out["warnings"] = warnings
    return out


__all__ = [
    "ACTIONABLE_ERRORS",
    "HARD_BLOCKER_ERRORS",
    "SOFT_GAP_ERRORS",
    "apply_soft_gap",
    "attach_next_steps",
    "diagnose",
    "doctor",
    "next_steps_for",
    "setup",
]
