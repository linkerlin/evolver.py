"""Node id resolution chain — ports core of ``nodeIdResolution.test.js``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep import node_identity as ni
from evolver.gep.canonical_identity_lock import (
    _reset_canonical_identity_lock_timing_for_testing,
    _set_canonical_identity_lock_timing_for_testing,
    acquire_canonical_identity_lock,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / ".evomap"
    h.mkdir()
    monkeypatch.setenv("EVOLVER_HOME", str(h))
    for key in (
        "A2A_NODE_ID",
        "A2A_NODE_SECRET",
        "A2A_NODE_SECRET_VERSION",
        "EVOMAP_NODE_SECRET",
        "EVOMAP_NODE_SECRET_VERSION",
        "EVOMAP_DEVICE_ID",
        "AGENT_NAME",
    ):
        monkeypatch.delenv(key, raising=False)
    ni.reset_cached_node_id()
    # Avoid project-local .evomap_node_id polluting resolution.
    monkeypatch.setattr(ni, "project_local_node_id_path", lambda: None)
    yield h
    ni.reset_cached_node_id()


def test_env_valid_12_hex(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = home
    monkeypatch.setenv("A2A_NODE_ID", "node_abcdef012345")
    assert ni.get_or_create_node_id() == "node_abcdef012345"


def test_env_valid_16_hex_hub_issued(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = home
    monkeypatch.setenv("A2A_NODE_ID", "node_71c0a711a894cbf3")
    assert ni.get_or_create_node_id() == "node_71c0a711a894cbf3"


def test_env_malformed_warns_but_uses(
    home: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _ = home
    monkeypatch.setenv("A2A_NODE_ID", "test-node")
    with caplog.at_level("WARNING"):
        assert ni.get_or_create_node_id() == "test-node"
    assert any("unexpected format" in r.message for r in caplog.records)


def test_loads_persisted_12_hex(home: Path) -> None:
    (home / "node_id").write_text("node_112233445566", encoding="utf-8")
    assert ni.get_or_create_node_id() == "node_112233445566"


def test_loads_persisted_16_hex(home: Path) -> None:
    (home / "node_id").write_text("node_71c0a711a894cbf3", encoding="utf-8")
    assert ni.get_or_create_node_id() == "node_71c0a711a894cbf3"


def test_promotes_mailbox_only_id(home: Path) -> None:
    mailbox = home / "mailbox"
    mailbox.mkdir()
    (mailbox / "state.json").write_text(
        json.dumps({"node_id": "node_eeeeeeeeeeee", "node_secret": "secret"}),
        encoding="utf-8",
    )
    assert ni.get_or_create_node_id() == "node_eeeeeeeeeeee"
    assert (home / "node_id").read_text(encoding="utf-8") == "node_eeeeeeeeeeee"


def test_ignores_malformed_mailbox_and_mints(home: Path) -> None:
    mailbox = home / "mailbox"
    mailbox.mkdir()
    (mailbox / "state.json").write_text(
        json.dumps({"node_id": "not-a-valid-id", "node_secret": "x"}),
        encoding="utf-8",
    )
    nid = ni.get_or_create_node_id()
    assert ni.is_valid_node_id(nid)
    assert nid != "not-a-valid-id"
    assert (home / "node_id").read_text(encoding="utf-8") == nid


def test_repairs_malformed_persisted(home: Path) -> None:
    (home / "node_id").write_text("not-a-valid-id", encoding="utf-8")
    nid = ni.get_or_create_node_id()
    assert ni.is_valid_node_id(nid)
    assert (home / "node_id").read_text(encoding="utf-8") == nid


def test_clears_orphan_credentials_before_claim(home: Path) -> None:
    (home / "node_secret").write_text("a" * 64, encoding="utf-8")
    (home / "node_secret_version").write_text("7", encoding="utf-8")
    (home / "node_secret_source").write_text("hub_rotate", encoding="utf-8")
    nid = ni.get_or_create_node_id()
    assert ni.is_valid_node_id(nid)
    assert not (home / "node_secret").exists()
    assert not (home / "node_secret_version").exists()
    assert not (home / "node_secret_source").exists()


def test_clears_ownerless_mailbox_before_fresh_identity(home: Path) -> None:
    mailbox = home / "mailbox"
    mailbox.mkdir()
    state_file = mailbox / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "node_secret": "b" * 64,
                "node_secret_version": "9",
                "node_secret_source": "hub_rotate",
            }
        ),
        encoding="utf-8",
    )
    nid = ni.get_or_create_node_id()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["node_id"] == nid
    assert state["node_secret"] == ""
    assert state["node_secret_version"] == ""
    assert state["node_secret_source"] == ""


def test_fallback_stable_across_calls(home: Path) -> None:
    _ = home
    first = ni.get_or_create_node_id()
    assert ni.is_valid_node_id(first)
    ni.reset_cached_node_id()
    second = ni.get_or_create_node_id()
    assert second == first


def test_two_homes_get_different_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ids: list[str] = []
    for i in range(2):
        h = tmp_path / f"home{i}" / ".evomap"
        h.mkdir(parents=True)
        monkeypatch.setenv("EVOLVER_HOME", str(h))
        monkeypatch.delenv("A2A_NODE_ID", raising=False)
        monkeypatch.setattr(ni, "project_local_node_id_path", lambda: None)
        ni.reset_cached_node_id()
        ids.append(ni.get_or_create_node_id())
    assert ni.is_valid_node_id(ids[0])
    assert ni.is_valid_node_id(ids[1])
    assert ids[0] != ids[1]


def test_lock_timeout_fails_closed(home: Path) -> None:
    path = home / "node_id"
    _set_canonical_identity_lock_timing_for_testing({"waitMs": 1, "timeoutMs": 25})
    release = acquire_canonical_identity_lock(path)
    try:
        with pytest.raises(ni.NodeIdPersistError) as exc_info:
            ni.get_or_create_node_id()
        assert exc_info.value.code == "CANONICAL_IDENTITY_LOCK_TIMEOUT"
        assert not path.exists() or path.read_text(encoding="utf-8").strip() == ""
    finally:
        release()
        _reset_canonical_identity_lock_timing_for_testing()


def test_adopts_winner_when_file_already_claimed(home: Path) -> None:
    winner = "node_bbbbbbbbbbbb"
    (home / "node_id").write_text(winner, encoding="utf-8")
    # Cache empty, but file exists — must load winner, not mint.
    ni.reset_cached_node_id()
    assert ni.get_or_create_node_id() == winner
