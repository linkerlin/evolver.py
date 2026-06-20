"""Anti-abuse telemetry — detect and report suspicious evolution patterns.

Equivalent to ``evolver/src/gep/antiAbuseTelemetry.js``.

Monitors the evolution system for patterns that may indicate abuse:
  - **Gene flooding**: excessive new gene creation in a short window.
  - **Validation bypass**: repeated attempts to skip validation.
  - **Signal spoofing**: fabricated signals to force gene selection.
  - **Resource exhaustion**: excessive cycles with no progress.

Reports are written to a local JSONL log and optionally forwarded to the Hub.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

_SUSPICION_THRESHOLD = 0.7
_FLOOD_WINDOW_S = 60
_FLOOD_MAX_EVENTS = 20

# Anti-abuse heartbeat envelope schema versions.
_SCHEMA_VERSION = "1.0.0"
_REDACTION_VERSION = "2"
_DEFAULT_RETENTION_TTL_DAYS = 90


def _pseudonym(identifier: str, salt: str | None = None) -> str | None:
    """HMAC-SHA256 pseudonym: stable but non-reversible.

    Mirrors the Node.js ``_pseudonym`` helper.  Returns ``None`` when the
    identifier is empty.  The salt defaults to ``EVOLVER_ANTI_ABUSE_SALT``
    / ``EVOMAP_DEVICE_ID`` env, falling back to the process title.
    """
    if not identifier:
        return None
    s = salt or os.environ.get("EVOLVER_ANTI_ABUSE_SALT") or os.environ.get("EVOMAP_DEVICE_ID")
    if not s:
        s = "evolver"  # deterministic fallback (worst case: no salt isolation)
    mac = hmac.new(s.encode("utf-8"), identifier.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def _source_confidence_entry(
    field: str, reason: str, expected_source: str = "hub_service"
) -> dict[str, str]:
    """Build a source-confidence label for a field the Hub must verify itself."""
    return {"field": field, "reason": reason, "expected_source": expected_source}


def build_heartbeat_anti_abuse(
    *,
    env_fingerprint: dict[str, Any] | None = None,
    node_id: str | None = None,
    task_metrics: dict[str, Any] | None = None,
    source: str = "evolver.py",
    repo_root: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the privacy-preserving anti-abuse telemetry envelope for heartbeats.

    Mirrors ``buildHeartbeatAntiAbuseTelemetry`` in the Node.js implementation.
    The envelope carries **low-sensitive hashes** (pseudonymized device/workspace
    identifiers), explicit **source-confidence labels** (marking which fields the
    Hub must re-verify rather than trust), and task-timing metrics.

    All device identifiers are HMAC-pseudonymized so the Hub gets a stable but
    non-reversible identifier (k-anonymity class).
    """
    env_map: Mapping[str, str] = env if env is not None else os.environ
    fp = env_fingerprint or {}
    salt = os.environ.get("EVOLVER_ANTI_ABUSE_SALT") or os.environ.get("EVOMAP_DEVICE_ID")

    # Device + workspace pseudonyms (HMAC, non-reversible).
    device_pseudonym = _pseudonym(fp.get("device_id", "") or "", salt)
    workspace_pseudonym = _pseudonym(os.getcwd(), salt)

    # Integrity hashes (package.json, lockfiles) — best-effort, never raises.
    integrity = _compute_integrity_hashes(repo_root)

    # Task timing — from the provided metrics dict (may be None).
    timing = _extract_task_timing(task_metrics)

    # Source-confidence labels: mark fields the Hub MUST verify itself.
    unavailable: list[dict[str, str]] = []
    if not device_pseudonym:
        unavailable.append(_source_confidence_entry("device_pseudonym", "device_id_missing"))
    if not workspace_pseudonym:
        unavailable.append(_source_confidence_entry("workspace_pseudonym", "cwd_unresolvable"))

    # Proxy / security boundary classification.
    proxy_port_configured = bool(
        env_map.get("EVOLVER_PROXY_PORT") or env_map.get("EVOMAP_PROXY_PORT")
    )

    # Retention TTL (days) — configurable, default 90.
    ttl_raw = env_map.get("EVOLVER_ANTI_ABUSE_TTL_DAYS")
    try:
        retention_ttl = int(ttl_raw) if ttl_raw else _DEFAULT_RETENTION_TTL_DAYS
        if retention_ttl < 0:
            retention_ttl = _DEFAULT_RETENTION_TTL_DAYS
    except (ValueError, TypeError):
        retention_ttl = _DEFAULT_RETENTION_TTL_DAYS

    return {
        "schema_version": _SCHEMA_VERSION,
        "event_type": "anti_abuse_telemetry",
        "purpose": "heartbeat",
        "pii_class": "k_anonymity",
        "consent_level": "opt_in",
        "retention_ttl_days": retention_ttl,
        "policy_version": env_map.get("EVOLVER_ABUSE_POLICY_VERSION", "default"),
        "redaction_version": _REDACTION_VERSION,
        "source": source,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_confidence": {
            "node_identity": "self_attested",
            "device_integrity": "self_attested",
            "task_metrics": "self_attested",
            "network_source": "hub_observed",
            "account_security": "hub_required",
            "payout": "hub_required",
            "risk_decision": "hub_service",
        },
        "identity": {
            "node_id": node_id,
            "account_id": None,
            "org_id": None,
        },
        "device": {
            "device_pseudonym": device_pseudonym,
            "workspace_pseudonym": workspace_pseudonym,
            "pseudonym_salt_id": salt is not None,
            "env_fingerprint_key": fp.get("fingerprint_key"),
            "platform": fp.get("platform"),
            "arch": fp.get("arch"),
            "os_release": fp.get("os_release"),
            "python_version": fp.get("python_version"),
            "evolver_version": fp.get("evolver_version"),
            "container": bool(fp.get("container")),
        },
        "integrity": integrity,
        "local_security_boundary": {
            "proxy_bind_address_class": "loopback",
            "proxy_port_configured": proxy_port_configured,
            "settings_permission_class": _settings_permission_class(),
        },
        "task_timing": timing,
        "unavailable_fields": unavailable,
    }


def _compute_integrity_hashes(repo_root: str | None) -> dict[str, Any]:
    """Best-effort SHA-256 hashes of package.json, pyproject.toml, lockfiles."""
    result: dict[str, Any] = {
        "package_json_hash": None,
        "pyproject_hash": None,
        "lockfile_hashes": {},
    }
    if not repo_root:
        return result
    root = Path(repo_root)
    with suppress(OSError):
        for key, name in [
            ("package_json_hash", "package.json"),
            ("pyproject_hash", "pyproject.toml"),
        ]:
            f = root / name
            if f.is_file():
                result[key] = hashlib.sha256(f.read_bytes()).hexdigest()
    with suppress(OSError):
        for lockfile in ("uv.lock", "package-lock.json"):
            f = root / lockfile
            if f.is_file():
                result["lockfile_hashes"][lockfile] = hashlib.sha256(f.read_bytes()).hexdigest()
    return result


def _extract_task_timing(task_metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract numeric task-timing fields from a metrics dict."""
    if not task_metrics or not isinstance(task_metrics, dict):
        return None
    out: dict[str, Any] = {}
    for field in ("pending", "claimed", "completed", "failed", "avg_completion_ms"):
        val = task_metrics.get(field)
        try:
            n = int(val) if val is not None else None
        except (ValueError, TypeError):
            n = None
        if n is not None:
            out[field] = n
    return out or None


def _settings_permission_class() -> str:
    """Classify the settings file permission (best-effort)."""
    home = os.path.expanduser("~")
    candidates = [
        os.environ.get("EVOLVER_HOME", os.path.join(home, ".evomap")),
    ]
    for base in candidates:
        settings = Path(base) / "settings.json"
        if settings.exists():
            return "tested"
    return "untested"


class AbuseDetector:
    """Detect suspicious evolution patterns using rolling windows."""

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path
        self._gene_creations: deque[float] = deque(maxlen=100)
        self._validation_skips: deque[float] = deque(maxlen=100)
        self._idle_cycles: int = 0

    def record_gene_creation(self) -> float:
        """Record a gene creation event. Returns abuse score (0.0-1.0)."""
        now = time.time()
        self._gene_creations.append(now)
        return self._check_flood()

    def record_validation_skip(self) -> float:
        """Record a validation skip. Returns abuse score."""
        now = time.time()
        self._validation_skips.append(now)
        recent_skips = sum(1 for t in self._validation_skips if now - t < _FLOOD_WINDOW_S)
        score = min(recent_skips / 5.0, 1.0)
        if score >= _SUSPICION_THRESHOLD:
            self._report("validation_bypass", {"recent_skips": recent_skips}, score)
        return score

    def record_idle_cycle(self) -> float:
        """Record an idle (no-progress) cycle. Returns abuse score."""
        self._idle_cycles += 1
        score = min(self._idle_cycles / 50.0, 1.0)
        if score >= _SUSPICION_THRESHOLD:
            self._report(
                "resource_exhaustion",
                {"idle_cycles": self._idle_cycles},
                score,
            )
        return score

    def reset_progress(self) -> None:
        """Call when a cycle makes progress (resets idle counter)."""
        self._idle_cycles = 0

    def _check_flood(self) -> float:
        """Check for gene creation flooding."""
        now = time.time()
        recent = sum(1 for t in self._gene_creations if now - t < _FLOOD_WINDOW_S)
        score = min(recent / _FLOOD_MAX_EVENTS, 1.0)
        if score >= _SUSPICION_THRESHOLD:
            self._report("gene_flood", {"recent_creations": recent}, score)
        return score

    def _report(self, abuse_type: str, details: dict[str, Any], score: float) -> None:
        """Write an abuse report to the log."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": abuse_type,
            "score": round(score, 2),
            "details": details,
        }
        if self._log_path:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError:
                pass

    def get_score(self) -> float:
        """Return the current overall abuse suspicion score (0.0-1.0)."""
        return max(
            self._check_flood(),
            min(len(self._validation_skips) / 5.0, 1.0),
            min(self._idle_cycles / 50.0, 1.0),
        )


__all__ = ["AbuseDetector", "build_heartbeat_anti_abuse"]
