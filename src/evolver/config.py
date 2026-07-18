"""Centralized configuration for evolver runtime thresholds and timeouts.

Equivalent to evolver/src/config.js.
All values support environment variable override where specified.
Groups: network, solidify, evolution, ops, limits.
"""

from __future__ import annotations

import os
import warnings
from typing import Final
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


# --- Network & A2A ---
HELLO_TIMEOUT_MS: Final = env_positive_int("EVOLVER_HELLO_TIMEOUT_MS", 15_000)
HEARTBEAT_TIMEOUT_MS: Final = env_positive_int("EVOLVER_HEARTBEAT_TIMEOUT_MS", 10_000)
HEARTBEAT_INTERVAL_MS: Final = env_positive_int("HEARTBEAT_INTERVAL_MS", 360_000)
HEARTBEAT_FIRST_DELAY_MS: Final = env_positive_int("EVOLVER_HEARTBEAT_FIRST_DELAY_MS", 30_000)
EVENT_POLL_TIMEOUT_MS: Final = env_positive_int("EVOLVER_EVENT_POLL_TIMEOUT_MS", 60_000)
HTTP_TRANSPORT_TIMEOUT_MS: Final = env_positive_int("EVOLVER_HTTP_TRANSPORT_TIMEOUT_MS", 15_000)
SECRET_CACHE_TTL_MS: Final = env_positive_int("EVOLVER_SECRET_CACHE_TTL_MS", 60_000)
HUB_SEARCH_TIMEOUT_MS: Final = env_positive_int("EVOLVER_HUB_SEARCH_TIMEOUT_MS", 8_000)

PUBLIC_DEFAULT_HUB_URL: Final = "https://evomap.ai"
DEFAULT_PROXY_PORT: Final = 8081
DEFAULT_WEBUI_PORT: Final = 8080
PROXY_HOST: Final = env_str("EVOLVER_PROXY_HOST", env_str("EVOMAP_PROXY_HOST", "127.0.0.1"))


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
        os.environ.get("A2A_HUB_URL")
        or os.environ.get("EVOMAP_HUB_URL")
        or os.environ.get("EVOLVER_DEFAULT_HUB_URL")
        or PUBLIC_DEFAULT_HUB_URL
    )
    return enforce_hub_scheme(raw)


# --- Solidify & Validation ---
BLAST_RADIUS_HARD_CAP_FILES: Final = env_int("EVOLVER_HARD_CAP_FILES", 60)
BLAST_RADIUS_HARD_CAP_LINES: Final = env_int("EVOLVER_HARD_CAP_LINES", 20_000)
VALIDATION_TIMEOUT_MS: Final = env_int("EVOLVER_VALIDATION_TIMEOUT_MS", 180_000)
CANARY_TIMEOUT_MS: Final = env_int("EVOLVER_CANARY_TIMEOUT_MS", 30_000)
CAPSULE_CONTENT_MAX_CHARS: Final = env_int("EVOLVER_CAPSULE_MAX_CHARS", 8_000)
SOLIDIFY_MAX_RETRIES: Final = env_int("SOLIDIFY_MAX_RETRIES", 2)
SOLIDIFY_RETRY_INTERVAL_MS: Final = env_int("EVOLVER_SOLIDIFY_RETRY_INTERVAL_MS", 1_000)
MIN_PUBLISH_SCORE: Final = env_float("EVOLVER_MIN_PUBLISH_SCORE", 0.78)
BROADCAST_SCORE_THRESHOLD: Final = 0.7
BROADCAST_SUCCESS_STREAK: Final = 2
MAX_REGEX_PATTERN_LEN: Final = 1_024

# --- Evolution Loop ---
REPAIR_LOOP_THRESHOLD: Final = env_int("EVOLVER_REPAIR_LOOP_THRESHOLD", 3)
GENE_BAN_PER_KEY_ATTEMPTS: Final = env_int("EVOLVER_GENE_BAN_PER_KEY_ATTEMPTS", 4)
GENE_BAN_BEST_THRESHOLD: Final = env_float("EVOLVER_GENE_BAN_BEST_THRESHOLD", 0.15)
GENE_INERT_BAN_STREAK: Final = env_int("EVOLVER_GENE_INERT_BAN_STREAK", 8)
GENE_EPIGENETIC_HARD_BOOST: Final = env_float("EVOLVER_GENE_EPIGENETIC_HARD_BOOST", -0.3)
SESSION_ARCHIVE_TRIGGER: Final = env_int("EVOLVER_SESSION_ARCHIVE_TRIGGER", 100)
SESSION_ARCHIVE_KEEP: Final = env_int("EVOLVER_SESSION_ARCHIVE_KEEP", 50)
MEMORY_FRAGMENT_MAX_CHARS: Final = env_int("EVOLVER_MEMORY_FRAGMENT_MAX_CHARS", 50_000)
IDLE_FETCH_INTERVAL_MS: Final = env_int("EVOLVER_IDLE_FETCH_INTERVAL_MS", 600_000)
# Solo / loop testability: exit the daemon loop after N cycles (0 = unlimited).
MAX_CYCLES_PER_PROCESS: Final = env_int("EVOLVER_MAX_CYCLES_PER_PROCESS", 0)
# Issue #19: hard timeout per evolve cycle (default 45 min); 0 disables via ENABLED=false.
CYCLE_TIMEOUT_MS: Final = env_int("EVOLVER_CYCLE_TIMEOUT_MS", 2_700_000)
PROGRESS_UPDATE_MS: Final = env_int("EVOLVER_PROGRESS_UPDATE_MS", 60_000)
PROMPT_MAX_CHARS: Final = env_int("EVOLVER_PROMPT_MAX_CHARS", 24_000)
ACTIVE_WINDOW_MS: Final = 24 * 60 * 60 * 1_000
TARGET_BYTES: Final = 120_000
PER_FILE_BYTES: Final = 20_000
PER_SESSION_BYTES: Final = 20_000
RECENCY_GUARD_MS: Final = 30 * 1_000
DORMANT_TTL_MS: Final = 3_600 * 1_000
PACKAGE_DESC_CACHE_TTL_MS: Final = 6 * 60 * 60 * 1_000
MEMORY_GRAPH_READ_LIMIT: Final = 1_000
NARRATIVE_SUMMARY_MAX_CHARS: Final = 3_000

# --- Ops ---
MAX_SILENCE_MS: Final = env_int("EVOLVER_MAX_SILENCE_MS", 30 * 60 * 1_000)
CLEANUP_MAX_AGE_MS: Final = env_int("EVOLVER_CLEANUP_MAX_AGE_MS", 24 * 60 * 60 * 1_000)
CLEANUP_MIN_KEEP: Final = env_int("EVOLVER_CLEANUP_MIN_KEEP", 10)
CLEANUP_MAX_FILES: Final = env_int("EVOLVER_CLEANUP_MAX_FILES", 10)
LOCK_MAX_AGE_MS: Final = env_int("EVOLVER_LOCK_MAX_AGE_MS", 10 * 60 * 1_000)

# --- Self-PR ---
SELF_PR_MIN_SCORE: Final = env_float("EVOLVER_SELF_PR_MIN_SCORE", 0.85)
SELF_PR_MIN_STREAK: Final = env_int("EVOLVER_SELF_PR_MIN_STREAK", 3)
SELF_PR_MAX_FILES: Final = env_int("EVOLVER_SELF_PR_MAX_FILES", 3)
SELF_PR_MAX_LINES: Final = env_int("EVOLVER_SELF_PR_MAX_LINES", 100)
SELF_PR_COOLDOWN_MS: Final = env_int("EVOLVER_SELF_PR_COOLDOWN_MS", 24 * 60 * 60 * 1_000)
SELF_PR_REPO: Final = env_str("EVOLVER_SELF_PR_REPO", "EvoMap/evolver")
SELF_PR_TIMEOUT_MS: Final = env_int("EVOLVER_SELF_PR_TIMEOUT_MS", 30_000)

# --- Leak Check ---
LEAK_CHECK_MODE: Final = env_str("EVOLVER_LEAK_CHECK", "strict")

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


# --- Validator mode (opt-out) ---
def _validator_enabled() -> bool:
    v = (os.environ.get("EVOLVER_VALIDATOR_ENABLED") or "").lower().strip()
    return v in ("1", "true", "yes", "on")


VALIDATOR_ENABLED: Final = _validator_enabled()
VALIDATOR_STAKE_AMOUNT: Final = env_int("EVOLVER_VALIDATOR_STAKE_AMOUNT", 100)
VALIDATOR_MAX_TASKS_PER_CYCLE: Final = env_int("EVOLVER_VALIDATOR_MAX_TASKS_PER_CYCLE", 2)
VALIDATOR_FETCH_TIMEOUT_MS: Final = env_int("EVOLVER_VALIDATOR_FETCH_TIMEOUT_MS", 8_000)
VALIDATOR_REPORT_TIMEOUT_MS: Final = env_int("EVOLVER_VALIDATOR_REPORT_TIMEOUT_MS", 10_000)
VALIDATOR_STAKE_TIMEOUT_MS: Final = env_int("EVOLVER_VALIDATOR_STAKE_TIMEOUT_MS", 10_000)
VALIDATOR_CMD_TIMEOUT_MS: Final = env_int("EVOLVER_VALIDATOR_CMD_TIMEOUT_MS", 60_000)
VALIDATOR_BATCH_TIMEOUT_MS: Final = env_int("EVOLVER_VALIDATOR_BATCH_TIMEOUT_MS", 180_000)

__all__ = [
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
    "DORMANT_TTL_MS",
    "EVENT_POLL_TIMEOUT_MS",
    "GENE_BAN_BEST_THRESHOLD",
    "GENE_BAN_PER_KEY_ATTEMPTS",
    "GENE_EPIGENETIC_HARD_BOOST",
    "GENE_INERT_BAN_STREAK",
    "HEARTBEAT_FIRST_DELAY_MS",
    "HEARTBEAT_INTERVAL_MS",
    "HEARTBEAT_TIMEOUT_MS",
    "HELLO_TIMEOUT_MS",
    "HTTP_TRANSPORT_TIMEOUT_MS",
    "HUB_SEARCH_TIMEOUT_MS",
    "IDLE_FETCH_INTERVAL_MS",
    "LEAK_CHECK_MODE",
    "LOCK_MAX_AGE_MS",
    "MAX_CYCLES_PER_PROCESS",
    "MAX_REGEX_PATTERN_LEN",
    "MAX_SILENCE_MS",
    "MEMORY_FRAGMENT_MAX_CHARS",
    "MEMORY_GRAPH_READ_LIMIT",
    "MIN_PUBLISH_SCORE",
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
    "SOLIDIFY_MAX_RETRIES",
    "SOLIDIFY_RETRY_INTERVAL_MS",
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
    "proxy_base_url",
    "proxy_local_url",
    "resolve_hub_base",
    "resolve_hub_url",
    "resolve_proxy_port",
    "resolve_webui_port",
    "reuse_attribution_mode",
]
