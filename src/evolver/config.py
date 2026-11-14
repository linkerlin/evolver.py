"""Centralized configuration for evolver runtime thresholds and timeouts.

Equivalent to evolver/src/config.js, unified around :class:`EvolverConfig`
loaded from ``~/.evolver/config.json`` and optional ``EVOLVER_CONFIG``
(inline JSON object or JSON file path).
"""

from __future__ import annotations

import json
import math
import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

_ENV_WARNED: set[str] = set()
_RUNTIME_OVERRIDES: dict[str, Any] = {}
_RUNTIME_EPOCH: int = 0
_CONFIG_CACHE_KEY: tuple[Any, ...] | None = None
_CONFIG_CACHE_VALUE: EvolverConfig | None = None


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


def _coerce_bool(raw: Any, fallback: bool) -> bool:
    if raw is None:
        return fallback
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if s == "":
        return fallback
    if s in ("false", "0", "off", "no"):
        return False
    if s in ("true", "1", "on", "yes"):
        return True
    return fallback


def _coerce_int(raw: Any, fallback: int, *, min_value: int | None = None) -> int:
    if raw is None or isinstance(raw, bool):
        return fallback
    if isinstance(raw, str) and raw.strip() == "":
        return fallback
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return fallback
    if min_value is not None and val < min_value:
        return fallback
    return val


def _coerce_float(raw: Any, fallback: float, *, positive: bool = False) -> float:
    if raw is None or isinstance(raw, bool):
        return fallback
    if isinstance(raw, str) and raw.strip() == "":
        return fallback
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(val):
        return fallback
    if positive and val <= 0:
        return fallback
    return val


def _coerce_str(raw: Any, fallback: str = "") -> str:
    if raw is None:
        return fallback
    if isinstance(raw, bool):
        return "true" if raw else "false"
    return str(raw)


@dataclass(frozen=True)
class EvolverConfig:
    """Typed unified runtime configuration (P0-4 Slice D).

    Consolidates low-frequency runtime knobs into ``~/.evolver/config.json``
    and ``EVOLVER_CONFIG`` (inline JSON or file path), keeping the process
    environment footprint compact and auditable.
    """

    adaptive_mutation: bool = True
    adaptive_mutation_shift: float = 0.2
    anti_abuse_telemetry: str = ""
    applied_gene_cooldown_events: int = 5
    applied_gene_cooldown_penalty: float = 0.25
    atp: str = "auto"
    atp_autobuy: str = ""
    atp_autodeliver: bool = True
    autopoiesis: bool = True
    autopoiesis_log_path: str = ""
    autopoiesis_write: bool = True
    conv_sniff_mode: str = "off"
    cycle_timeout_ms: int = 2_700_000
    progress_update_ms: int = 60_000
    idle_fetch_interval_ms: int = 600_000
    default_hub_url: str = ""
    enforce_idle_scheduler: bool = False
    env_mode: str = ""
    eval_worktree_whitelist: str = ""
    feedback_degraded_threshold: float = 0.5
    force_update: bool = False
    force_update_retry_cooldown_ms: int = 300_000
    gene_inert_ban_streak: int = 8
    github_repo: str = ""
    hitl_ttl_ms: int = 30 * 60 * 1_000
    innovation_log_path: str = ""
    learning_signals: bool = True
    max_cycles_per_process: int = 0
    memory_graph_auto_rotate: bool = True
    memory_graph_max_size_mb: float = 100.0
    memory_graph_retention_count: int = 7
    rotate_gzip_max_mb: float = 32.0
    outcome_report: str = "off"
    proxy_lifecycle: bool = True
    quiet_legacy_warning: bool = False
    repair_loop_degraded: bool = True
    reuse_attribution: str = "off"
    rollback_mode: str = "stash"
    sandbox_require_isolation: bool = False
    sandbox_strict: bool = False
    self_repair_hard_reset: bool = False
    session_source: str = "auto"
    skill_update_interval_sec: float = 300.0
    soak_allow_inside: bool = False
    sqlite_store: bool = False
    suicide: bool = True
    suicide_windows: bool = False
    supervision_auto_pause_streak: int = 3
    swarm_gate_handoff: str = "human"
    test_mode: bool = False
    trace_level: str = "minimal"
    trigger_max_cycles_per_day: int = 0
    trigger_max_tokens_per_day: int = 0
    trigger_per_pattern_cap: int = 0
    validator_enabled: bool = False
    verbose: bool = False
    webui_github: bool = True

    @classmethod
    def _flatten_layer(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = dict(raw)
        runtime_sub = data.get("runtime")
        if isinstance(runtime_sub, Mapping):
            merged = dict(runtime_sub)
            merged.update({k: v for k, v in data.items() if k != "runtime"})
            data = merged

        # Support optional nested sections (e.g. {"autopoiesis": {"enabled": false}})
        auto_sec = data.get("autopoiesis")
        if isinstance(auto_sec, Mapping):
            if "enabled" in auto_sec:
                data["autopoiesis"] = auto_sec["enabled"]
            if "write" in auto_sec and "autopoiesis_write" not in data:
                data["autopoiesis_write"] = auto_sec["write"]
            if "log_path" in auto_sec and "autopoiesis_log_path" not in data:
                data["autopoiesis_log_path"] = auto_sec["log_path"]

        mem_sec = data.get("memory_graph")
        if isinstance(mem_sec, Mapping):
            if "auto_rotate" in mem_sec and "memory_graph_auto_rotate" not in data:
                data["memory_graph_auto_rotate"] = mem_sec["auto_rotate"]
            if "max_size_mb" in mem_sec and "memory_graph_max_size_mb" not in data:
                data["memory_graph_max_size_mb"] = mem_sec["max_size_mb"]
            if "retention_count" in mem_sec and "memory_graph_retention_count" not in data:
                data["memory_graph_retention_count"] = mem_sec["retention_count"]
            if "gzip_max_mb" in mem_sec and "rotate_gzip_max_mb" not in data:
                data["rotate_gzip_max_mb"] = mem_sec["gzip_max_mb"]
            data.pop("memory_graph", None)

        trig_sec = data.get("trigger")
        if isinstance(trig_sec, Mapping):
            if "max_cycles_per_day" in trig_sec and "trigger_max_cycles_per_day" not in data:
                data["trigger_max_cycles_per_day"] = trig_sec["max_cycles_per_day"]
            if "max_tokens_per_day" in trig_sec and "trigger_max_tokens_per_day" not in data:
                data["trigger_max_tokens_per_day"] = trig_sec["max_tokens_per_day"]
            if "per_pattern_cap" in trig_sec and "trigger_per_pattern_cap" not in data:
                data["trigger_per_pattern_cap"] = trig_sec["per_pattern_cap"]
            data.pop("trigger", None)
        return data

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvolverConfig:
        defaults = cls()
        data = cls._flatten_layer(raw)

        return cls(
            adaptive_mutation=_coerce_bool(
                data.get("adaptive_mutation"), defaults.adaptive_mutation
            ),
            adaptive_mutation_shift=_coerce_float(
                data.get("adaptive_mutation_shift"), defaults.adaptive_mutation_shift
            ),
            anti_abuse_telemetry=_coerce_str(
                data.get("anti_abuse_telemetry"), defaults.anti_abuse_telemetry
            ),
            applied_gene_cooldown_events=_coerce_int(
                data.get("applied_gene_cooldown_events"), defaults.applied_gene_cooldown_events
            ),
            applied_gene_cooldown_penalty=_coerce_float(
                data.get("applied_gene_cooldown_penalty"), defaults.applied_gene_cooldown_penalty
            ),
            atp=_coerce_str(data.get("atp"), defaults.atp),
            atp_autobuy=_coerce_str(data.get("atp_autobuy"), defaults.atp_autobuy),
            atp_autodeliver=_coerce_bool(data.get("atp_autodeliver"), defaults.atp_autodeliver),
            autopoiesis=_coerce_bool(data.get("autopoiesis"), defaults.autopoiesis),
            autopoiesis_log_path=_coerce_str(
                data.get("autopoiesis_log_path"), defaults.autopoiesis_log_path
            ),
            autopoiesis_write=_coerce_bool(
                data.get("autopoiesis_write"), defaults.autopoiesis_write
            ),
            conv_sniff_mode=_coerce_str(
                data.get("conv_sniff_mode", data.get("conv_sniff_enabled")),
                defaults.conv_sniff_mode,
            ),
            cycle_timeout_ms=_coerce_int(
                data.get("cycle_timeout_ms"), defaults.cycle_timeout_ms, min_value=1
            ),
            progress_update_ms=_coerce_int(
                data.get("progress_update_ms"), defaults.progress_update_ms, min_value=1
            ),
            idle_fetch_interval_ms=_coerce_int(
                data.get("idle_fetch_interval_ms"), defaults.idle_fetch_interval_ms, min_value=1
            ),
            default_hub_url=_coerce_str(data.get("default_hub_url"), defaults.default_hub_url),
            enforce_idle_scheduler=_coerce_bool(
                data.get("enforce_idle_scheduler"), defaults.enforce_idle_scheduler
            ),
            env_mode=_coerce_str(data.get("env_mode", data.get("env")), defaults.env_mode),
            eval_worktree_whitelist=_coerce_str(
                data.get("eval_worktree_whitelist"), defaults.eval_worktree_whitelist
            ),
            feedback_degraded_threshold=_coerce_float(
                data.get("feedback_degraded_threshold"), defaults.feedback_degraded_threshold
            ),
            force_update=_coerce_bool(data.get("force_update"), defaults.force_update),
            force_update_retry_cooldown_ms=_coerce_int(
                data.get("force_update_retry_cooldown_ms"),
                defaults.force_update_retry_cooldown_ms,
                min_value=1,
            ),
            gene_inert_ban_streak=_coerce_int(
                data.get("gene_inert_ban_streak"), defaults.gene_inert_ban_streak
            ),
            github_repo=_coerce_str(data.get("github_repo"), defaults.github_repo),
            hitl_ttl_ms=_coerce_int(data.get("hitl_ttl_ms"), defaults.hitl_ttl_ms, min_value=1),
            innovation_log_path=_coerce_str(
                data.get("innovation_log_path"), defaults.innovation_log_path
            ),
            learning_signals=_coerce_bool(data.get("learning_signals"), defaults.learning_signals),
            max_cycles_per_process=_coerce_int(
                data.get("max_cycles_per_process"), defaults.max_cycles_per_process, min_value=0
            ),
            memory_graph_auto_rotate=_coerce_bool(
                data.get("memory_graph_auto_rotate"), defaults.memory_graph_auto_rotate
            ),
            memory_graph_max_size_mb=_coerce_float(
                data.get("memory_graph_max_size_mb"),
                defaults.memory_graph_max_size_mb,
                positive=True,
            ),
            memory_graph_retention_count=_coerce_int(
                data.get("memory_graph_retention_count"),
                defaults.memory_graph_retention_count,
                min_value=0,
            ),
            rotate_gzip_max_mb=_coerce_float(
                data.get("rotate_gzip_max_mb"), defaults.rotate_gzip_max_mb, positive=True
            ),
            outcome_report=_coerce_str(data.get("outcome_report"), defaults.outcome_report),
            proxy_lifecycle=_coerce_bool(data.get("proxy_lifecycle"), defaults.proxy_lifecycle),
            quiet_legacy_warning=_coerce_bool(
                data.get("quiet_legacy_warning"), defaults.quiet_legacy_warning
            ),
            repair_loop_degraded=_coerce_bool(
                data.get("repair_loop_degraded"), defaults.repair_loop_degraded
            ),
            reuse_attribution=_coerce_str(
                data.get("reuse_attribution"), defaults.reuse_attribution
            ),
            rollback_mode=_coerce_str(data.get("rollback_mode"), defaults.rollback_mode)
            .strip()
            .lower()
            or defaults.rollback_mode,
            sandbox_require_isolation=_coerce_bool(
                data.get("sandbox_require_isolation"), defaults.sandbox_require_isolation
            ),
            sandbox_strict=_coerce_bool(data.get("sandbox_strict"), defaults.sandbox_strict),
            self_repair_hard_reset=_coerce_bool(
                data.get("self_repair_hard_reset"), defaults.self_repair_hard_reset
            ),
            session_source=_coerce_str(data.get("session_source"), defaults.session_source)
            .strip()
            .lower()
            or defaults.session_source,
            skill_update_interval_sec=max(
                30.0,
                _coerce_float(
                    data.get("skill_update_interval_sec"),
                    defaults.skill_update_interval_sec,
                    positive=True,
                ),
            ),
            soak_allow_inside=_coerce_bool(
                data.get("soak_allow_inside"), defaults.soak_allow_inside
            ),
            sqlite_store=_coerce_bool(data.get("sqlite_store"), defaults.sqlite_store),
            suicide=_coerce_bool(data.get("suicide"), defaults.suicide),
            suicide_windows=_coerce_bool(data.get("suicide_windows"), defaults.suicide_windows),
            supervision_auto_pause_streak=_coerce_int(
                data.get("supervision_auto_pause_streak"),
                defaults.supervision_auto_pause_streak,
                min_value=0,
            ),
            swarm_gate_handoff=_coerce_str(
                data.get("swarm_gate_handoff"), defaults.swarm_gate_handoff
            ).strip()
            or defaults.swarm_gate_handoff,
            test_mode=_coerce_bool(data.get("test_mode"), defaults.test_mode),
            trace_level=_coerce_str(data.get("trace_level"), defaults.trace_level).strip().lower()
            or defaults.trace_level,
            trigger_max_cycles_per_day=_coerce_int(
                data.get("trigger_max_cycles_per_day"),
                defaults.trigger_max_cycles_per_day,
                min_value=0,
            ),
            trigger_max_tokens_per_day=_coerce_int(
                data.get("trigger_max_tokens_per_day"),
                defaults.trigger_max_tokens_per_day,
                min_value=0,
            ),
            trigger_per_pattern_cap=_coerce_int(
                data.get("trigger_per_pattern_cap"),
                defaults.trigger_per_pattern_cap,
                min_value=0,
            ),
            validator_enabled=_coerce_bool(
                data.get("validator_enabled"), defaults.validator_enabled
            ),
            verbose=_coerce_bool(data.get("verbose"), defaults.verbose),
            webui_github=_coerce_bool(data.get("webui_github"), defaults.webui_github),
        )


def _settings_config_file() -> Path:
    raw = os.environ.get("EVOLVER_STATE_ROOT") or os.environ.get("EVOLVER_SETTINGS_DIR")
    base = Path(raw).expanduser() if raw and raw.strip() else (Path.home() / ".evolver")
    return base / "config.json"


def parse_config_payload(raw_spec: str | None) -> dict[str, Any]:
    """Parse ``EVOLVER_CONFIG`` payload (inline JSON object or JSON file path)."""
    if not raw_spec or not raw_spec.strip():
        return {}
    spec = raw_spec.strip()
    if spec.startswith("{"):
        try:
            parsed = json.loads(spec)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    path = Path(spec).expanduser()
    try:
        if path.is_file():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return dict(parsed) if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def set_runtime_config_override(**overrides: Any) -> None:
    """Set in-process runtime config overrides (bumps cache epoch immediately)."""
    global _RUNTIME_EPOCH
    _RUNTIME_OVERRIDES.update(overrides)
    _RUNTIME_EPOCH += 1


def clear_runtime_config_overrides(*keys: str) -> None:
    """Clear selected (or all, when empty) in-process runtime config overrides."""
    global _RUNTIME_EPOCH
    if keys:
        for k in keys:
            _RUNTIME_OVERRIDES.pop(k, None)
    else:
        _RUNTIME_OVERRIDES.clear()
    _RUNTIME_EPOCH += 1


def merge_env_config(**updates: Any) -> str:
    """Merge *updates* into ``os.environ["EVOLVER_CONFIG"]`` as inline JSON."""
    current = parse_config_payload(os.environ.get("EVOLVER_CONFIG"))
    for k, v in updates.items():
        if v is None:
            current.pop(k, None)
        else:
            current[k] = v
    encoded = json.dumps(current, separators=(",", ":")) if current else ""
    if encoded:
        os.environ["EVOLVER_CONFIG"] = encoded
    else:
        os.environ.pop("EVOLVER_CONFIG", None)
    return encoded


def get_config() -> EvolverConfig:
    """Return active :class:`EvolverConfig` (cached by env + file mtime + epoch)."""
    global _CONFIG_CACHE_KEY, _CONFIG_CACHE_VALUE

    cfg_file = _settings_config_file()
    try:
        file_mtime = cfg_file.stat().st_mtime_ns if cfg_file.is_file() else 0
    except OSError:
        file_mtime = 0

    env_spec = os.environ.get("EVOLVER_CONFIG", "")
    spec_mtime = 0
    if env_spec and not env_spec.lstrip().startswith("{"):
        try:
            spec_path = Path(env_spec.strip()).expanduser()
            spec_mtime = spec_path.stat().st_mtime_ns if spec_path.is_file() else -1
        except OSError:
            spec_mtime = -1

    cache_key = (str(cfg_file), file_mtime, env_spec, spec_mtime, _RUNTIME_EPOCH)
    if _CONFIG_CACHE_VALUE is not None and cache_key == _CONFIG_CACHE_KEY:
        return _CONFIG_CACHE_VALUE

    merged: dict[str, Any] = {}
    if file_mtime > 0:
        try:
            disk_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            if isinstance(disk_data, dict):
                merged.update(EvolverConfig._flatten_layer(disk_data))
        except (OSError, json.JSONDecodeError):
            pass

    if env_spec:
        merged.update(EvolverConfig._flatten_layer(parse_config_payload(env_spec)))

    if _RUNTIME_OVERRIDES:
        merged.update(EvolverConfig._flatten_layer(_RUNTIME_OVERRIDES))

    cfg = EvolverConfig.from_mapping(merged)
    _CONFIG_CACHE_KEY = cache_key
    _CONFIG_CACHE_VALUE = cfg
    return cfg


_BOOT_CFG = get_config()

# --- Network & A2A (S30.4 §11.4 #7: stable constants) ---
HELLO_TIMEOUT_MS: Final = 15_000
HEARTBEAT_TIMEOUT_MS: Final = 10_000
HEARTBEAT_INTERVAL_MS: Final = env_positive_int("HEARTBEAT_INTERVAL_MS", 360_000)
HEARTBEAT_FIRST_DELAY_MS: Final = 30_000
EVENT_POLL_TIMEOUT_MS: Final = 60_000
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
    """True only when ``EVOMAP_HUB_ALLOW_INSECURE`` is exactly ``"1"``."""
    return os.environ.get("EVOMAP_HUB_ALLOW_INSECURE") == "1"


def enforce_hub_scheme(url: str) -> str:
    """Refuse non-``https://`` Hub URLs unless insecure bypass is set."""
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
      3. EvolverConfig.default_hub_url
      4. PUBLIC_DEFAULT_HUB_URL
    """
    if os.environ.get("EVOLVER_SOLO", "") == "1":
        return ""
    cfg_hub = get_config().default_hub_url.strip()
    raw = (
        os.environ.get("A2A_HUB_URL")
        or os.environ.get("EVOMAP_HUB_URL")
        or cfg_hub
        or PUBLIC_DEFAULT_HUB_URL
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

# --- Self-Harness causal diagnosis ---
DIAGNOSIS_INTERVAL: Final = 1
DIAGNOSIS_MAX_EVENTS: Final = 20

# --- Self-Harness acceptance gate ---
ACCEPTANCE_REPEATS: Final = 2
ACCEPTANCE_DELTA_EPSILON: Final = 0.0
ACCEPTANCE_SHADOW: Final = env_bool("EVOLVER_ACCEPTANCE_SHADOW", True)

# --- Self-Harness multi-proposer ---
MULTI_PROPOSE_ROUTES: Final = 1

# --- Sprint 22.2 fitness cascade ---
FITNESS_PYTEST_TIMEOUT_MS: Final = 600_000
FITNESS_CASCADE_COMMANDS: Final[list[dict[str, Any]]] = [
    {"command": ["ruff", "check", "src", "tests"]},
    {"command": ["mypy", "src"]},
    {"command": ["pytest", "-m", "not slow", "-q"], "timeout_ms": FITNESS_PYTEST_TIMEOUT_MS},
]

# --- Self-Harness external LLM templates ---
LLM_CALL_DIR: Final = env_str("EVOLVER_LLM_CALL_DIR", "<GEP_ASSETS_DIR>/llm_calls")

MIN_PUBLISH_SCORE: Final = 0.78
BROADCAST_SCORE_THRESHOLD: Final = 0.7
BROADCAST_SUCCESS_STREAK: Final = 2
MAX_REGEX_PATTERN_LEN: Final = 1_024

# --- Evolution Loop ---
REPAIR_LOOP_THRESHOLD: Final = 3
GENE_BAN_PER_KEY_ATTEMPTS: Final = 4
GENE_BAN_BEST_THRESHOLD: Final = 0.15
GENE_INERT_BAN_STREAK: Final = _BOOT_CFG.gene_inert_ban_streak
APPLIED_GENE_COOLDOWN_EVENTS: Final = _BOOT_CFG.applied_gene_cooldown_events
APPLIED_GENE_COOLDOWN_PENALTY: Final = _BOOT_CFG.applied_gene_cooldown_penalty
GENE_EPIGENETIC_HARD_BOOST: Final = -0.3
SESSION_ARCHIVE_TRIGGER: Final = 100
SESSION_ARCHIVE_KEEP: Final = 50
MEMORY_FRAGMENT_MAX_CHARS: Final = 50_000
IDLE_FETCH_INTERVAL_MS: Final = _BOOT_CFG.idle_fetch_interval_ms
MAX_CYCLES_PER_PROCESS: Final = _BOOT_CFG.max_cycles_per_process
CYCLE_TIMEOUT_MS: Final = _BOOT_CFG.cycle_timeout_ms
PROGRESS_UPDATE_MS: Final = _BOOT_CFG.progress_update_ms
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
SWARM_AUTO_HIJACK: Final = env_bool("EVOLVER_SWARM_AUTO_HIJACK", False)
SWARM_GATE_HANDOFF: Final = _BOOT_CFG.swarm_gate_handoff
SWARM_TICK_LOG_MAX_CHARS: Final = 8_000
SWARM_FEEDBACK_DEGRADED_THRESHOLD: Final = _BOOT_CFG.feedback_degraded_threshold
HITL_MODE: Final = parse_hitl_mode(os.environ.get("EVOLVER_HITL_MODE"), default="off")
HITL_TTL_MS: Final = _BOOT_CFG.hitl_ttl_ms
SUPERVISION_AUTO_PAUSE_STREAK: Final = _BOOT_CFG.supervision_auto_pause_streak
SKILL_ROOTS_OVERRIDE: Final = env_str("EVOLVER_SKILL_ROOTS", "")
ADAPTIVE_MUTATION_ENABLED: Final = _BOOT_CFG.adaptive_mutation
ADAPTIVE_MUTATION_SHIFT: Final = _BOOT_CFG.adaptive_mutation_shift

GATE_SOAK_MIN_RUNS: Final = env_int("EVOLVER_GATE_SOAK_MIN_RUNS", 20)
GATE_SOAK_MAX_FALSE_KILL: Final = 0.1
GATE_SOAK_INTERCEPT_MIN: Final = 0.05
GATE_SOAK_INTERCEPT_MAX: Final = 0.5

ANCHOR_TRIGGER_SURFACES: Final[tuple[str, ...]] = (
    "src/evolver/gep/acceptance/",
    "src/evolver/gep/anchor.py",
    "src/evolver/gep/git_ops.py",
    "src/evolver/gep/hitl.py",
    "src/evolver/gep/llm_template.py",
    "src/evolver/gep/solidify.py",
    "src/evolver/gep/supervision.py",
    "src/evolver/gep/validation_env.py",
    "src/evolver/ops/meta_report.py",
    "src/evolver/gep/gene_lifecycle.py",
    "src/evolver/gep/selector.py",
    "src/evolver/gep/evidence_pack.py",
    "src/evolver/gep/prompt.py",
    "tests/gep/acceptance/",
    "tests/gep/test_solidify.py",
    "src/evolver/ops/charter_check.py",
    "src/evolver/gep/population.py",
    "src/evolver/ops/cleanup.py",
    "src/evolver/bench/",
    "src/evolver/gep/hypothesis.py",
    "src/evolver/gep/val_seal.py",
)
ANCHOR_PROBE_TIMEOUT_S: Final = 120.0

# --- Ops ---
MAX_SILENCE_MS: Final = 30 * 60 * 1_000
CLEANUP_MAX_AGE_MS: Final = 24 * 60 * 60 * 1_000
CLEANUP_MIN_KEEP: Final = 10
CLEANUP_MAX_FILES: Final = 10
LOCK_MAX_AGE_MS: Final = 10 * 60 * 1_000

# --- Self-PR ---
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
EVOLVER_LAUNCHER: Final = env_str("EVOLVER_LAUNCHER", "auto")

# --- Reuse attribution (P4-a Slice A) ---
REUSE_ATTRIBUTION_MODE: Final = _BOOT_CFG.reuse_attribution


def reuse_attribution_mode() -> str:
    v = (get_config().reuse_attribution or REUSE_ATTRIBUTION_MODE or "off").lower().strip()
    return "shadow" if v == "shadow" else "off"


# --- Outcome report mode (P4-a Slice B) ---
OUTCOME_REPORT_MODE: Final = _BOOT_CFG.outcome_report


def outcome_report_mode() -> str:
    """Resolve the outcome-report mode: 'on' or 'off'."""
    v = str(get_config().outcome_report or OUTCOME_REPORT_MODE or "off").lower().strip()
    return "on" if v in ("on", "enforce", "true") else "off"


# --- Anti-abuse telemetry mode ---
ANTI_ABUSE_TELEMETRY_MODE: Final = _BOOT_CFG.anti_abuse_telemetry or "heartbeat"


def anti_abuse_telemetry_mode() -> str:
    """Resolve the anti-abuse telemetry mode: 'heartbeat' or 'off'."""
    v = str(get_config().anti_abuse_telemetry or "").lower().strip()
    if v == "":
        return "heartbeat"
    if v in ("0", "false", "no", "off"):
        return "off"
    return "heartbeat" if v in ("1", "true", "yes", "on", "heartbeat") else "off"


# --- Validator mode ---
def _validator_enabled() -> bool:
    if os.environ.get("EVOLVER_SOLO", "") == "1":
        return False
    return bool(get_config().validator_enabled)


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
    "ACCEPTANCE_SHADOW",
    "ACTIVE_WINDOW_MS",
    "ADAPTIVE_MUTATION_ENABLED",
    "ADAPTIVE_MUTATION_SHIFT",
    "ANCHOR_PROBE_TIMEOUT_S",
    "ANCHOR_TRIGGER_SURFACES",
    "ANTI_ABUSE_TELEMETRY_MODE",
    "APPLIED_GENE_COOLDOWN_EVENTS",
    "APPLIED_GENE_COOLDOWN_PENALTY",
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
    "FITNESS_CASCADE_COMMANDS",
    "FITNESS_PYTEST_TIMEOUT_MS",
    "GATE_SOAK_INTERCEPT_MAX",
    "GATE_SOAK_INTERCEPT_MIN",
    "GATE_SOAK_MAX_FALSE_KILL",
    "GATE_SOAK_MIN_RUNS",
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
    "HUB_FETCH_RETRIES",
    "HUB_FETCH_RETRY_BACKOFF_MS",
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
    "SWARM_GATE_HANDOFF",
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
    "EvolverConfig",
    "_validator_enabled",
    "anti_abuse_telemetry_mode",
    "clear_runtime_config_overrides",
    "enforce_hub_scheme",
    "env_bool",
    "env_float",
    "env_int",
    "env_positive_int",
    "env_str",
    "get_config",
    "hub_allow_insecure",
    "merge_env_config",
    "outcome_report_mode",
    "parse_config_payload",
    "parse_hitl_mode",
    "proxy_base_url",
    "proxy_local_url",
    "resolve_hub_base",
    "resolve_hub_url",
    "resolve_proxy_port",
    "resolve_webui_port",
    "reuse_attribution_mode",
    "set_runtime_config_override",
]
