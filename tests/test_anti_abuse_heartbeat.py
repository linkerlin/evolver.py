"""Tests for evolver.gep.anti_abuse_telemetry — heartbeat envelope builder.

Equivalent to evolver/test/antiAbuseTelemetry.test.js.
"""

from __future__ import annotations

from evolver.gep.anti_abuse_telemetry import (
    AbuseDetector,
    _pseudonym,
    build_heartbeat_anti_abuse,
)

_SUSPICION_THRESHOLD = 0.7


def test_pseudonym_stable_and_nonreversible() -> None:
    """Same input + salt → same output; different salt → different output."""
    h1 = _pseudonym("device-123", salt="salt-a")
    h2 = _pseudonym("device-123", salt="salt-a")
    h3 = _pseudonym("device-123", salt="salt-b")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex


def test_pseudonym_empty_returns_none() -> None:
    assert _pseudonym("", salt="x") is None
    assert _pseudonym(None, salt="x") is None  # type: ignore[arg-type]


def test_build_heartbeat_envelope_structure() -> None:
    """The envelope has the required top-level fields and privacy properties."""
    env = build_heartbeat_anti_abuse(
        env_fingerprint={"platform": "linux", "arch": "x86_64", "device_id": "dev-1"},
        node_id="node-abc",
        task_metrics={"pending": 3, "completed": 10},
        repo_root=None,
    )
    assert env["schema_version"] == "1.0.0"
    assert env["event_type"] == "anti_abuse_telemetry"
    assert env["purpose"] == "heartbeat"
    assert env["pii_class"] == "k_anonymity"
    assert env["consent_level"] == "opt_in"
    # Identity
    assert env["identity"]["node_id"] == "node-abc"
    assert env["identity"]["account_id"] is None
    # Device pseudonyms are present and hashed
    assert env["device"]["device_pseudonym"] is not None
    assert env["device"]["platform"] == "linux"
    # Source confidence labels mark hub-required fields
    sc = env["source_confidence"]
    assert sc["payout"] == "hub_required"
    assert sc["risk_decision"] == "hub_service"
    # Task timing extracted
    assert env["task_timing"]["pending"] == 3
    assert env["task_timing"]["completed"] == 10


def test_build_heartbeat_no_task_metrics() -> None:
    """When task_metrics is None, task_timing is null."""
    env = build_heartbeat_anti_abuse(
        env_fingerprint={},
        node_id=None,
        task_metrics=None,
    )
    assert env["task_timing"] is None
    assert env["identity"]["node_id"] is None


def test_build_heartbeat_device_pseudonym_absent_when_no_device_id() -> None:
    """When device_id is missing, device_pseudonym is null and field is unavailable."""
    env = build_heartbeat_anti_abuse(
        env_fingerprint={},  # no device_id
        node_id="n1",
    )
    assert env["device"]["device_pseudonym"] is None
    fields = [u["field"] for u in env["unavailable_fields"]]
    assert "device_pseudonym" in fields


def test_abuse_detector_basic() -> None:
    """Existing AbuseDetector still works."""
    d = AbuseDetector()
    assert d.get_score() < _SUSPICION_THRESHOLD
    d.reset_progress()
    assert d.get_score() < _SUSPICION_THRESHOLD
