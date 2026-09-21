"""Centralized configuration for evolver runtime thresholds and timeouts.

Equivalent to evolver/src/config.js.
All values support environment variable override where specified.
Groups: network, solidify, evolution, ops, limits.
"""

from __future__ import annotations

import os
import warnings
from typing import Any, Final
from urllib.parse import urlparse

_ENV_WARNED: set[str] = set()


def env_int(key: str, fallback: int) -> int:
    v = os.environ.get(key)
    if v is None or v == "":
        return fallback
    try:
        return int(v)
    except ValueError:
        return fallback


def env_positive_int(key: str, fallback: int) -> int:
    """Strict variant for timers/intervals: must be positive and < 2**31."""
    v = os.environ.get(key)
    if v is None or v == "":
        return fallback
    try:
        n = int(v)
    except ValueError:
        n = None
    if n is None or not (0 < n < 2**31):
        if key not in _ENV_WARNED:
            _ENV_WARNED.add(key)
            warnings.warn(
                f"[config] {key}={v!r} is not a positive integer; "
                f"falling back to {fallback}. Set a value in (0, 2^31) ms.",
                stacklevel=2,
            )
        return fallback
    return n


def env_float(key: str, fallback: float) -> float:
    v = os.environ.get(key)
    if v is None or v == "":
        return fallback
    try:
        return float(v)
    except ValueError:
        return fallback


def env_str(key: str, fallback: str) -> str:
    v = os.environ.get(key)
    return v if v is not None and v != "" else fallback


def parse_hitl_mode(raw: str | None, *, default: str = "off") -> str:
    """Normalize HITL mode. Unknown values fail-closed to ``on``."""
    if raw is None or str(raw).strip() == "":
        return default
    s = str(raw).strip().lower()
    if s in ("on", "true", "1", "yes"):
        return "on"
    if s in ("off", "false", "0", "no"):
        return "off"
    return "on"


def env_bool(key: str, fallback: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return fallback
    s = v.lower().strip()
    if s in ("",):
        return fallback
    if s in ("false", "0", "off", "no"):
        return False
    if s in ("true", "1", "on", "yes"):
        return True
    return fallback


# --- Network & A2A (S30.4 §11.4 #7: stable constants) ---
HELLO_TIMEOUT_MS: Final = 15_000
HEARTBEAT_TIMEOUT_MS: Final = 10_000
HEARTBEAT_INTERVAL_MS: Final = env_positive_int("HEARTBEAT_INTERVAL_MS", 360_000)
HEARTBEAT_FIRST_DELAY_MS: Final = 30_000
EVENT_POLL_TIMEOUT_MS: Final = 60_000
# Round-53: calibrated from measured endpoint distribution — the Hub answers
# 404 in a stable 1.4-1.5s (three consecutive curl samples), so the old
# 15s/8s values only ever mattered as worst-case burn (one 15s timeout + one
# retry = the 15.7s hub-phase reading that drove the round-40/41 tick
# timeouts). 10s/5s keep ~7x/3x headroom over the observed floor while
# halving the worst case. Module constants, not env knobs.
HTTP_TRANSPORT_TIMEOUT_MS: Final = 10_000
SECRET_CACHE_TTL_MS: Final = 60_000
HUB_SEARCH_TIMEOUT_MS: Final = 5_000
HUB_FETCH_RETRIES: Final = 1
HUB_FETCH_RETRY_BACKOFF_MS: Final = 500

PUBLIC_DEFAULT_HUB_URL: Final = "https://evomap.ai"
DEFAULT_PROXY_PORT: Final = 8081
DEFAULT_WEBUI_PORT: Final = 8080
PROXY_HOST: Final = "127.0.0.1"


def resolve_proxy_port() -> int:
    """Local A2A proxy listen port.

    Precedence: ``EVOLVER_PROXY_PORT`` → ``EVOMAP_PROXY_PORT`` → ``8081``.
    """
    for key in ("EVOLVER_PROXY_PORT", "EVOMAP_PROXY_PORT"):
        raw = os.environ.get(key)
        if raw is None or raw == "":
            continue
        try:
            port = int(raw)
        except ValueError:
            continue
        if 0 < port < 65536:
            return port
    return DEFAULT_PROXY_PORT


def proxy_base_url() -> str:
    """Base URL for the local proxy, e.g. ``http://127.0.0.1:8081``."""
    return f"http://{PROXY_HOST}:{resolve_proxy_port()}"


def proxy_local_url(path: str) -> str:
    """URL under the local proxy ``/v1/a2a`` prefix (no leading slash required)."""
    suffix = path.lstrip("/")
    return f"{proxy_base_url()}/v1/a2a/{suffix}"


def resolve_webui_port() -> int:
    """WebUI listen port (``EVOLVER_WEBUI_PORT``, default ``8080``)."""
    raw = os.environ.get("EVOLVER_WEBUI_PORT")
    if raw is None or raw == "":
        return DEFAULT_WEBUI_PORT
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_WEBUI_PORT
    if 0 < port < 65536:
        return port
    return DEFAULT_WEBUI_PORT


def hub_allow_insecure() -> bool:
    """True only when ``EVOMAP_HUB_ALLOW_INSECURE`` is exactly ``"1"``.

    Matches Node hubFetch: ``true`` / ``yes`` / ``0`` / padded values do **not**
    disable TLS enforcement (Bugbot PR #160).
    """
    return os.environ.get("EVOMAP_HUB_ALLOW_INSECURE") == "1"


def enforce_hub_scheme(url: str) -> str:
    """Refuse non-``https://`` Hub URLs unless insecure bypass is set.

    Shared posture for hubFetch, ATP hubClient, and any caller that takes a
    Hub base or absolute URL (Node ``enforceHubScheme``).

    Returns *url* unchanged on success. Raises :class:`ValueError` whose
    message matches ``/must use https/i`` or ``/not a valid URL/i`` (and
    includes ``tls_refused`` for cleartext refusals).
    """
    raw = str(url or "").strip()
    if hub_allow_insecure():
        return raw

    try:
        parsed = urlparse(raw)
    except Exception as exc:
        raise ValueError(f"[config] Hub URL is not a valid URL: {raw!r}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme == "https" and parsed.netloc:
        return raw
    if scheme == "http" and parsed.netloc:
        raise ValueError(
            f"[config] Hub URL must use https:// — got {raw!r} (tls_refused). "
            "Set EVOMAP_HUB_ALLOW_INSECURE=1 to bypass (local dev / mock hub only)."
        )
    raise ValueError(f"[config] Hub URL is not a valid URL: {raw!r}")


def resolve_hub_base(hub_url: str | None = None) -> str:
    """Resolve Hub base URL, enforcing TLS on env default or *hub_url* override."""
    if hub_url is not None and str(hub_url).strip():
        return enforce_hub_scheme(str(hub_url).strip())
    return resolve_hub_url()


def resolve_hub_url() -> str:
    """Hub URL resolution with TLS enforcement.

    Precedence:
      1. A2A_HUB_URL
      2. EVOMAP_HUB_URL (backward compat)
      3. EVOLVER_DEFAULT_HUB_URL
      4. PUBLIC_DEFAULT_HUB_URL
    """
    # Solo "no escape valve": even with a hub URL set, return "" so every hub
    # call bails with no_hub_url. Inline check (not an import) to avoid coupling
    # config -> solo; matches solo.breaker.SOLO_ENV.
    if os.environ.get("EVOLVER_SOLO", "") == "1":
        return ""
    raw = (
        os.environ.get("A2A_HUB_URL") or os.environ.get("EVOMAP_HUB_URL") or PUBLIC_DEFAULT_HUB_URL
    )
    return enforce_hub_scheme(raw)


# --- Solidify & Validation (S30.4 §11.4 #7: stable constants) ---
BLAST_RADIUS_HARD_CAP_FILES: Final = 60
BLAST_RADIUS_HARD_CAP_LINES: Final = 20_000
VALIDATION_TIMEOUT_MS: Final = 180_000
CANARY_TIMEOUT_MS: Final = 30_000
CAPSULE_CONTENT_MAX_CHARS: Final = 8_000
SOLIDIFY_MAX_RETRIES: Final = env_int("SOLIDIFY_MAX_RETRIES", 2)
SOLIDIFY_RETRY_INTERVAL_MS: Final = 1_000

# --- Self-Harness causal diagnosis (Sprint B1; opt-in, off by default) ---
DIAGNOSIS_INTERVAL: Final = 1
DIAGNOSIS_MAX_EVENTS: Final = 20

# --- Self-Harness acceptance gate (Sprint A1; opt-in, off by default) ---
ACCEPTANCE_REPEATS: Final = 2
ACCEPTANCE_DELTA_EPSILON: Final = 0.0
# Round-25: T0 flake adjudication needs NO spread threshold — the frozen set
# is deterministic, so any inter-repeat difference triggers adjudication and
# the majority value anchors the mean (a fixed 0.05 bar let single-test noise
# through; the retired T0_FLAKE_ADJUDICATION_SPREAD lives in DEBUG #33/#35).
# Sprint 22.5 gray-scale + S26 promotion: compute + record gate verdicts but
# never enforce during the soak window (interception / false-kill rates are
# measured on events as shadow markers). Set EVOLVER_ACCEPTANCE_SHADOW=0 to
# start enforcing (planned after the soak: 演进方案_wikiskill对照版.md §S26.3).
ACCEPTANCE_SHADOW: Final = env_bool("EVOLVER_ACCEPTANCE_SHADOW", True)

# --- Self-Harness multi-proposer (Sprint C2; 1 = existing single-proposal) ---
MULTI_PROPOSE_ROUTES: Final = 1

# --- Sprint 22.2 fitness cascade (flag enable_fitness_cascade; assumes Python/uv repo) ---
FITNESS_PYTEST_TIMEOUT_MS: Final = 600_000
FITNESS_CASCADE_COMMANDS: Final[list[dict[str, Any]]] = [
    {"command": ["ruff", "check", "src", "tests"]},
    {"command": ["mypy", "src"]},
    {"command": ["pytest", "-m", "not slow", "-q"], "timeout_ms": FITNESS_PYTEST_TIMEOUT_MS},
]
# S26.3 strict-improvement gate (r_best ledger): shadow period records verdicts
# only; set EVOLVER_FITNESS_GATE_ENFORCE=1 to roll back no_improvement
# mutations (same gray-scale pattern as EVOLVER_ACCEPTANCE_SHADOW).
FITNESS_GATE_ENFORCE: Final = False

# --- Self-Harness external LLM templates (Sprint D) ---
LLM_CALL_DIR: Final = env_str("EVOLVER_LLM_CALL_DIR", "<GEP_ASSETS_DIR>/llm_calls")

MIN_PUBLISH_SCORE: Final = 0.78
BROADCAST_SCORE_THRESHOLD: Final = 0.7
BROADCAST_SUCCESS_STREAK: Final = 2
MAX_REGEX_PATTERN_LEN: Final = 1_024

# --- Evolution Loop (S30.4 §11.4 #7: stable constants) ---
REPAIR_LOOP_THRESHOLD: Final = 3
GENE_BAN_PER_KEY_ATTEMPTS: Final = 4
GENE_BAN_BEST_THRESHOLD: Final = 0.15
GENE_INERT_BAN_STREAK: Final = env_int("EVOLVER_GENE_INERT_BAN_STREAK", 8)
APPLIED_GENE_COOLDOWN_EVENTS: Final = env_int("EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS", 5)
APPLIED_GENE_COOLDOWN_PENALTY: Final = env_float("EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY", 0.25)
GENE_EPIGENETIC_HARD_BOOST: Final = -0.3
SESSION_ARCHIVE_TRIGGER: Final = 100
SESSION_ARCHIVE_KEEP: Final = 50
MEMORY_FRAGMENT_MAX_CHARS: Final = 50_000
IDLE_FETCH_INTERVAL_MS: Final = 600_000
# Solo / loop testability: exit the daemon loop after N cycles (0 = unlimited).
MAX_CYCLES_PER_PROCESS: Final = env_int("EVOLVER_MAX_CYCLES_PER_PROCESS", 0)
# Issue #19: hard timeout per evolve cycle (default 45 min); 0 disables via ENABLED=false.
CYCLE_TIMEOUT_MS: Final = env_int("EVOLVER_CYCLE_TIMEOUT_MS", 2_700_000)
PROGRESS_UPDATE_MS: Final = 60_000
PROMPT_MAX_CHARS: Final = 24_000
ACTIVE_WINDOW_MS: Final = 24 * 60 * 60 * 1_000
TARGET_BYTES: Final = 120_000
PER_FILE_BYTES: Final = 20_000
PER_SESSION_BYTES: Final = 20_000
RECENCY_GUARD_MS: Final = 30 * 1_000
DORMANT_TTL_MS: Final = 3_600 * 1_000
PACKAGE_DESC_CACHE_TTL_MS: Final = 6 * 60 * 60 * 1_000
MEMORY_GRAPH_READ_LIMIT: Final = 1_000
NARRATIVE_SUMMARY_MAX_CHARS: Final = 3_000

# --- Swarm (MCP host-agent takeover; see evolver.swarm) ---
# Auto-hijack: prepend the full takeover directive into the MCP server
# instructions so unattended hosts boot straight into the swarm protocol.
# Default false — plain instructions merely advertise `evolver_swarm`.
SWARM_AUTO_HIJACK: Final = env_bool("EVOLVER_SWARM_AUTO_HIJACK", False)
# swarm_tick returns the engine's stdout as `engine_log` (tail-truncated to
# this budget); the dispatch prompt itself is returned untruncated.
SWARM_TICK_LOG_MAX_CHARS: Final = 8_000
# EvoX concept harvest: a swarm feedback report below this primary_score (or
# with success=false) is "degraded" and injects repair-bias signals.
SWARM_FEEDBACK_DEGRADED_THRESHOLD: Final = env_float("EVOLVER_FEEDBACK_DEGRADED_THRESHOLD", 0.5)
# EvoX concept harvest (HITLManager): "off" auto-approves high-risk requests
# (decision still journaled for audit); "on" requires explicit human approval;
# pending requests past the TTL fail-safe to REJECT. Unknown values fail-closed
# to "on". ``SWARM_AUTO_HIJACK`` also forces the gate on (see hitl_mode_enabled).
HITL_MODE: Final = parse_hitl_mode(os.environ.get("EVOLVER_HITL_MODE"), default="off")
HITL_TTL_MS: Final = env_positive_int("EVOLVER_HITL_TTL_MS", 30 * 60 * 1_000)
# HOTL (human-on-the-loop) tripwire: auto-pause supervision after this many
# consecutive degraded feedback reports (0 disables). Human resumes via
# `evolver supervise resume` / the swarm_supervise tool.
SUPERVISION_AUTO_PAUSE_STREAK: Final = env_int("EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK", 3)
# Skill asset bridge (gep/skill_assets.py): os.pathsep-separated skill roots
# replacing the defaults (project .agents/.claude skills > user home skills >
# builtin). Order IS the priority.
SKILL_ROOTS_OVERRIDE: Final = env_str("EVOLVER_SKILL_ROOTS", "")
# EvoX harvest (adaptive mutation rate): the unified feedback channel shifts
# strategy weights — degraded streak → repair bias, converged plateau →
# exploration pivot. Neutral no-op with fewer than 3 feedback entries.
ADAPTIVE_MUTATION_ENABLED: Final = env_bool("EVOLVER_ADAPTIVE_MUTATION", True)
ADAPTIVE_MUTATION_SHIFT: Final = env_float("EVOLVER_ADAPTIVE_MUTATION_SHIFT", 0.2)
# Acceptance-gate soak promotion criteria (evolver gate-report readiness
# verdicts; the actual switch stays a human decision — EVOLVER_ACCEPTANCE_SHADOW=0).
GATE_SOAK_MIN_RUNS: Final = env_int("EVOLVER_GATE_SOAK_MIN_RUNS", 20)
GATE_SOAK_MAX_FALSE_KILL: Final = 0.1
GATE_SOAK_INTERCEPT_MIN: Final = 0.05
GATE_SOAK_INTERCEPT_MAX: Final = 0.5
# Anchor evaluation (RSI P0-1): mutation paths that may weaken the verification
# machinery trigger the out-of-tree anchor suite during solidify. Plain
# constants by charter — no new env knobs during soak (演进方案.md §4).
ANCHOR_TRIGGER_SURFACES: Final[tuple[str, ...]] = (
    "src/evolver/gep/acceptance/",
    "src/evolver/gep/anchor.py",
    "src/evolver/gep/git_ops.py",
    "src/evolver/gep/hitl.py",
    # P2 (演进方案.md §11.4 #5): semi-trusted text ingress surface guarded by anchor.
    "src/evolver/gep/llm_template.py",
    "src/evolver/gep/solidify.py",
    "src/evolver/gep/supervision.py",
    "src/evolver/gep/validation_env.py",
    # Round-23 (RSI audit 5.3-3): the measurement instrument itself — three
    # consecutive rounds fixed telemetry honesty (#29/#30/#31); those
    # mutations neither triggered the anchor nor counted as structural-L5.
    # Guarded from epoch 4 by the telemetry-invariants probe.
    "src/evolver/ops/meta_report.py",
    # RSI P1-5 (round-33): the selection mechanism itself — gene lifecycle
    # governance and its selector enforcement. Mutations to these surfaces
    # must run the frozen lifecycle contracts (epoch 9), same doctrine as
    # the meter: the machinery that decides is part of what must be frozen.
    "src/evolver/gep/gene_lifecycle.py",
    "src/evolver/gep/selector.py",
    # RSI P1-4 (round-34): the failure-side channel to the executor. A
    # mutation that stops forwarding family failures to the prompt re-opens
    # the RQGM self-preference loop at the prompt layer — guarded from
    # epoch 10 by the evidence-pack-honesty probe.
    "src/evolver/gep/evidence_pack.py",
    "src/evolver/gep/prompt.py",
    "tests/gep/acceptance/",
    "tests/gep/test_solidify.py",
    # Round-37 (DEBUG #44 + RSI §6.6): the charter meter itself — the loop-
    # integrity receipt is the instrument that detects loop bypass, so a
    # mutation that quietly disables it must run the frozen contracts. Same
    # doctrine as meta_report (the machinery that decides is part of what
    # must be frozen). Advisory-only: no probe semantics changed, no epoch
    # bump — the receipt holds no rejection authority.
    "src/evolver/ops/charter_check.py",
    # RSI P1-3 (round-41): population adjudication decides WHICH candidate
    # reaches the frozen landing path — selection authority between
    # candidates, frozen from epoch 11 by the population-adjudication probe.
    "src/evolver/gep/population.py",
)
ANCHOR_PROBE_TIMEOUT_S: Final = 120.0

# --- Ops (S30.4 §11.4 #7: stable constants) ---
MAX_SILENCE_MS: Final = 30 * 60 * 1_000
CLEANUP_MAX_AGE_MS: Final = 24 * 60 * 60 * 1_000
CLEANUP_MIN_KEEP: Final = 10
CLEANUP_MAX_FILES: Final = 10
LOCK_MAX_AGE_MS: Final = 10 * 60 * 1_000

# --- Self-PR (S30.4 §11.4 #7: stable constants) ---
SELF_PR_MIN_SCORE: Final = 0.85
SELF_PR_MIN_STREAK: Final = 3
SELF_PR_MAX_FILES: Final = 3
SELF_PR_MAX_LINES: Final = 100
SELF_PR_COOLDOWN_MS: Final = 24 * 60 * 60 * 1_000
SELF_PR_REPO: Final = "EvoMap/evolver"
SELF_PR_TIMEOUT_MS: Final = 30_000

# --- Leak Check ---
LEAK_CHECK_MODE: Final = "strict"

# --- Launcher (uv / uvx / python) ---
# auto | uv | uvx | python — see evolver.uv_runtime
EVOLVER_LAUNCHER: Final = env_str("EVOLVER_LAUNCHER", "auto")

# --- Reuse attribution (P4-a Slice A) ---
REUSE_ATTRIBUTION_MODE: Final = env_str("EVOLVER_REUSE_ATTRIBUTION", "off")


def reuse_attribution_mode() -> str:
    v = (
        (os.environ.get("EVOLVER_REUSE_ATTRIBUTION") or REUSE_ATTRIBUTION_MODE or "off")
        .lower()
        .strip()
    )
    return "shadow" if v == "shadow" else "off"


# --- Outcome report mode (P4-a Slice B) ---
# Opt-in Hub reuse-OUTCOME reporting. When 'on', the evolver POSTs
# {signals, status, used_asset_ids} to the Hub so the reuse-reward attribution
# pipeline gets data. MONEY-ADJACENT — default 'off'.
OUTCOME_REPORT_MODE: Final = env_str("EVOLVER_OUTCOME_REPORT", "off")


def outcome_report_mode() -> str:
    """Resolve the outcome-report mode: 'on' or 'off'.

    Accepts on/enforce/true → 'on'; everything else → 'off'.
    Mirrors ``outcomeReportMode`` in the Node.js config.
    """
    raw = os.environ.get("EVOLVER_OUTCOME_REPORT")
    v = str(raw if raw is not None else OUTCOME_REPORT_MODE or "off").lower().strip()
    return "on" if v in ("on", "enforce", "true") else "off"


# --- Anti-abuse telemetry mode ---
# In heartbeat mode (default), clients attach a small ``meta.anti_abuse``
# envelope with low-sensitive hashes and source-confidence labels. Opt-out
# is explicit only — an empty value counts as UNSET.
ANTI_ABUSE_TELEMETRY_MODE: Final = env_str("EVOLVER_ANTI_ABUSE_TELEMETRY", "heartbeat")


def anti_abuse_telemetry_mode() -> str:
    """Resolve the anti-abuse telemetry mode: 'heartbeat' or 'off'.

    Empty/whitespace counts as UNSET (default-on). Explicit opt-out via
    0/false/no/off. Mirrors ``antiAbuseTelemetryMode`` in the Node.js config.
    """
    raw = os.environ.get("EVOLVER_ANTI_ABUSE_TELEMETRY")
    v = str(raw if raw is not None else "").lower().strip()
    if v == "":
        return "heartbeat"
    if v in ("0", "false", "no", "off"):
        return "off"
    return "heartbeat" if v in ("1", "true", "yes", "on", "heartbeat") else "off"


# --- Validator mode (opt-out, S30.4 §11.4 #7: stable constants) ---
def _validator_enabled() -> bool:
    v = (os.environ.get("EVOLVER_VALIDATOR_ENABLED") or "").lower().strip()
    return v in ("1", "true", "yes", "on")


VALIDATOR_ENABLED: Final = _validator_enabled()
VALIDATOR_STAKE_AMOUNT: Final = 100
VALIDATOR_MAX_TASKS_PER_CYCLE: Final = 2
VALIDATOR_FETCH_TIMEOUT_MS: Final = 8_000
VALIDATOR_REPORT_TIMEOUT_MS: Final = 10_000
VALIDATOR_STAKE_TIMEOUT_MS: Final = 10_000
VALIDATOR_CMD_TIMEOUT_MS: Final = 60_000
VALIDATOR_BATCH_TIMEOUT_MS: Final = 180_000

__all__ = [
    "ACCEPTANCE_DELTA_EPSILON",
    "ACCEPTANCE_REPEATS",
    "ACTIVE_WINDOW_MS",
    "ANTI_ABUSE_TELEMETRY_MODE",
    "BLAST_RADIUS_HARD_CAP_FILES",
    "BLAST_RADIUS_HARD_CAP_LINES",
    "BROADCAST_SCORE_THRESHOLD",
    "BROADCAST_SUCCESS_STREAK",
    "CANARY_TIMEOUT_MS",
    "CAPSULE_CONTENT_MAX_CHARS",
    "CLEANUP_MAX_AGE_MS",
    "CLEANUP_MAX_FILES",
    "CLEANUP_MIN_KEEP",
    "CYCLE_TIMEOUT_MS",
    "DEFAULT_PROXY_PORT",
    "DEFAULT_WEBUI_PORT",
    "DIAGNOSIS_INTERVAL",
    "DIAGNOSIS_MAX_EVENTS",
    "DORMANT_TTL_MS",
    "EVENT_POLL_TIMEOUT_MS",
    "EVOLVER_LAUNCHER",
    "GENE_BAN_BEST_THRESHOLD",
    "GENE_BAN_PER_KEY_ATTEMPTS",
    "GENE_EPIGENETIC_HARD_BOOST",
    "GENE_INERT_BAN_STREAK",
    "HEARTBEAT_FIRST_DELAY_MS",
    "HEARTBEAT_INTERVAL_MS",
    "HEARTBEAT_TIMEOUT_MS",
    "HELLO_TIMEOUT_MS",
    "HITL_MODE",
    "HITL_TTL_MS",
    "HTTP_TRANSPORT_TIMEOUT_MS",
    "HUB_SEARCH_TIMEOUT_MS",
    "IDLE_FETCH_INTERVAL_MS",
    "LEAK_CHECK_MODE",
    "LLM_CALL_DIR",
    "LOCK_MAX_AGE_MS",
    "MAX_CYCLES_PER_PROCESS",
    "MAX_REGEX_PATTERN_LEN",
    "MAX_SILENCE_MS",
    "MEMORY_FRAGMENT_MAX_CHARS",
    "MEMORY_GRAPH_READ_LIMIT",
    "MIN_PUBLISH_SCORE",
    "MULTI_PROPOSE_ROUTES",
    "NARRATIVE_SUMMARY_MAX_CHARS",
    "OUTCOME_REPORT_MODE",
    "PACKAGE_DESC_CACHE_TTL_MS",
    "PER_FILE_BYTES",
    "PER_SESSION_BYTES",
    "PROGRESS_UPDATE_MS",
    "PROMPT_MAX_CHARS",
    "PROXY_HOST",
    "PUBLIC_DEFAULT_HUB_URL",
    "RECENCY_GUARD_MS",
    "REPAIR_LOOP_THRESHOLD",
    "REUSE_ATTRIBUTION_MODE",
    "SECRET_CACHE_TTL_MS",
    "SELF_PR_COOLDOWN_MS",
    "SELF_PR_MAX_FILES",
    "SELF_PR_MAX_LINES",
    "SELF_PR_MIN_SCORE",
    "SELF_PR_MIN_STREAK",
    "SELF_PR_REPO",
    "SELF_PR_TIMEOUT_MS",
    "SESSION_ARCHIVE_KEEP",
    "SESSION_ARCHIVE_TRIGGER",
    "SKILL_ROOTS_OVERRIDE",
    "SOLIDIFY_MAX_RETRIES",
    "SOLIDIFY_RETRY_INTERVAL_MS",
    "SUPERVISION_AUTO_PAUSE_STREAK",
    "SWARM_AUTO_HIJACK",
    "SWARM_FEEDBACK_DEGRADED_THRESHOLD",
    "SWARM_TICK_LOG_MAX_CHARS",
    "TARGET_BYTES",
    "VALIDATION_TIMEOUT_MS",
    "VALIDATOR_BATCH_TIMEOUT_MS",
    "VALIDATOR_CMD_TIMEOUT_MS",
    "VALIDATOR_ENABLED",
    "VALIDATOR_FETCH_TIMEOUT_MS",
    "VALIDATOR_MAX_TASKS_PER_CYCLE",
    "VALIDATOR_REPORT_TIMEOUT_MS",
    "VALIDATOR_STAKE_AMOUNT",
    "VALIDATOR_STAKE_TIMEOUT_MS",
    "anti_abuse_telemetry_mode",
    "enforce_hub_scheme",
    "env_bool",
    "env_float",
    "env_int",
    "env_positive_int",
    "env_str",
    "hub_allow_insecure",
    "outcome_report_mode",
    "parse_hitl_mode",
    "proxy_base_url",
    "proxy_local_url",
    "resolve_hub_base",
    "resolve_hub_url",
    "resolve_proxy_port",
    "resolve_webui_port",
    "reuse_attribution_mode",
]
