"""Identity tuple isolation for sync (ports identityTupleSync semantics)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from evolver.gep import node_identity as ni
from evolver.gep import sync

NODE_A = "node_aaaaaaaaaaaa"
NODE_B = "node_bbbbbbbbbbbb"
SECRET_A = "a" * 64
SECRET_B = "b" * 64


@pytest.fixture
def mixed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Persisted node A credentials + mailbox node B credentials."""
    home = tmp_path / "home"
    mailbox = home / "mailbox"
    mailbox.mkdir(parents=True)
    (home / "node_id").write_text(NODE_A, encoding="utf-8")
    (home / "node_secret").write_text(SECRET_A, encoding="utf-8")
    (home / "node_secret_version").write_text("3", encoding="utf-8")
    (home / "node_secret_source").write_text("hub_rotate", encoding="utf-8")
    (mailbox / "state.json").write_text(
        json.dumps(
            {
                "marker": "preserve-node-b-mailbox",
                "node_id": NODE_B,
                "node_secret": SECRET_B,
                "node_secret_source": "hub_rotate",
                "node_secret_version": "99",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    for key in (
        "A2A_NODE_ID",
        "A2A_NODE_SECRET",
        "A2A_NODE_SECRET_VERSION",
        "EVOMAP_NODE_SECRET",
        "EVOMAP_NODE_SECRET_VERSION",
        "A2A_HUB_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ni, "project_local_node_id_path", lambda: None)
    ni.reset_cached_node_id()
    yield home
    ni.reset_cached_node_id()


def _snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[str(path.relative_to(root))] = path.read_bytes().hex()
    return out


def test_resolve_tuple_isolates_persisted_a_from_mailbox_b(mixed_home: Path) -> None:
    _ = mixed_home
    identity = ni.resolve_identity_tuple(create=False)
    assert identity["node_id"] == NODE_A
    assert identity["secret"] == SECRET_A
    assert identity["version"] == 3


def test_same_node_mailbox_prefers_higher_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    mailbox = home / "mailbox"
    mailbox.mkdir(parents=True)
    (home / "node_id").write_text(NODE_A, encoding="utf-8")
    (home / "node_secret").write_text(SECRET_A, encoding="utf-8")
    (home / "node_secret_version").write_text("3", encoding="utf-8")
    (home / "node_secret_source").write_text("hub_rotate", encoding="utf-8")
    (mailbox / "state.json").write_text(
        json.dumps(
            {
                "node_id": NODE_A,
                "node_secret": SECRET_B,
                "node_secret_source": "hub_rotate",
                "node_secret_version": "99",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.delenv("A2A_NODE_SECRET", raising=False)
    monkeypatch.setattr(ni, "project_local_node_id_path", lambda: None)
    ni.reset_cached_node_id()
    identity = ni.resolve_identity_tuple(create=False)
    assert identity["node_id"] == NODE_A
    assert identity["secret"] == SECRET_B
    assert identity["version"] == 99


@respx.mock
async def test_sync_dry_run_uses_node_a_and_is_readonly(
    mixed_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    before = _snapshot(mixed_home)

    route = respx.get("http://127.0.0.1:9/a2a/assets/published-by-me").mock(
        return_value=Response(
            200, json={"assets": [], "count": 0, "has_more": False, "next_cursor": None}
        )
    )

    result = await sync.sync_all(dry_run=True, scope="published")
    assert result["ok"] is True
    assert result["identity"]["node_id"] == NODE_A
    assert result["identity"]["version"] == 3
    assert route.called
    req = route.calls.last.request
    assert req.url.params.get("node_id") == NODE_A
    assert req.headers.get("Authorization") == f"Bearer {SECRET_A}"
    assert req.headers.get("X-EvoMap-Node-Secret-Version") == "3"
    assert _snapshot(mixed_home) == before, "dry-run must remain byte-for-byte read-only"
    # Secrets must never appear in result payload text.
    dumped = json.dumps(result)
    assert SECRET_A not in dumped
    assert SECRET_B not in dumped


@respx.mock
async def test_sync_real_with_env_node_id_does_not_cross_write(
    mixed_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    monkeypatch.setenv("A2A_NODE_ID", NODE_A)
    before = _snapshot(mixed_home)

    route = respx.get("http://127.0.0.1:9/a2a/assets/published-by-me").mock(
        return_value=Response(200, json={"assets": [], "count": 0})
    )

    result = await sync.sync_all(dry_run=False, scope="published")
    assert result["ok"] is True
    assert route.called
    req = route.calls.last.request
    assert req.url.params.get("node_id") == NODE_A
    assert req.headers.get("Authorization") == f"Bearer {SECRET_A}"
    assert _snapshot(mixed_home) == before
    assert (mixed_home / "node_secret").read_text(encoding="utf-8") == SECRET_A


@respx.mock
async def test_sync_same_node_uses_newer_mailbox_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    mailbox = home / "mailbox"
    mailbox.mkdir(parents=True)
    (home / "node_id").write_text(NODE_A, encoding="utf-8")
    (home / "node_secret").write_text(SECRET_A, encoding="utf-8")
    (home / "node_secret_version").write_text("3", encoding="utf-8")
    (home / "node_secret_source").write_text("hub_rotate", encoding="utf-8")
    (mailbox / "state.json").write_text(
        json.dumps(
            {
                "node_id": NODE_A,
                "node_secret": SECRET_B,
                "node_secret_source": "hub_rotate",
                "node_secret_version": "99",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    for key in ("A2A_NODE_ID", "A2A_NODE_SECRET", "A2A_NODE_SECRET_VERSION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ni, "project_local_node_id_path", lambda: None)
    ni.reset_cached_node_id()
    before = _snapshot(home)

    route = respx.get("http://127.0.0.1:9/a2a/assets/published-by-me").mock(
        return_value=Response(200, json={"assets": []})
    )
    result = await sync.sync_all(dry_run=True, scope="published")
    assert result["ok"] is True
    req = route.calls.last.request
    assert req.url.params.get("node_id") == NODE_A
    assert req.headers.get("Authorization") == f"Bearer {SECRET_B}"
    assert req.headers.get("X-EvoMap-Node-Secret-Version") == "99"
    assert _snapshot(home) == before
