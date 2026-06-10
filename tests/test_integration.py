"""End-to-end integration tests covering the full evolver workflow.

These tests exercise multiple subsystems together:
  • run → solidify → event logging
  • WebUI endpoints reflecting runtime state
  • SQLite event store toggle + replay
  • Auth middleware protecting admin WebSocket actions
  • Recipe cache + apply
  • Peer discovery lifecycle
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evolver.cli import main
from evolver.webui.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all evolver state into tmp_path so tests do not touch ~/.evolver."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))
    yield tmp_path


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# 1. Full run → solidify cycle
# ---------------------------------------------------------------------------

class TestFullRunSolidifyCycle:
    def test_run_creates_solidify_state(self, isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["run"])
        assert code == 0
        from evolver.gep.paths import get_solidify_state_path
        state = get_solidify_state_path()
        assert state.exists(), "Solidify state should be written after run"
        data = json.loads(state.read_text())
        assert "last_run" in data
        assert "run_id" in data["last_run"]

    def test_solidify_after_run_in_git_repo(self, isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _init_git_repo(isolated_evolver_env)

        code = main(["run"])
        assert code == 0

        code = main(["solidify"])
        assert code == 0
        captured = capsys.readouterr()
        assert "Solidify succeeded" in captured.out

        from evolver.gep.paths import get_solidify_state_path
        state = json.loads(get_solidify_state_path().read_text())
        assert "last_solidify" in state

    def test_run_then_solidify_appends_events(self, isolated_evolver_env: Path) -> None:
        _init_git_repo(isolated_evolver_env)
        from evolver.gep.asset_store import read_all_events
        before = len(read_all_events())
        code = main(["run"])
        assert code == 0
        code = main(["solidify"])
        assert code == 0
        after = len(read_all_events())
        assert after > before, "Solidify should append at least one event"


# ---------------------------------------------------------------------------
# 2. WebUI reflects runtime state after run
# ---------------------------------------------------------------------------

class TestWebUIFullPipeline:
    def test_status_shows_solidify_pending_after_run(self, client: TestClient, isolated_evolver_env: Path) -> None:
        main(["run"])
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["solidify_pending"] is True

    def test_genes_endpoint_after_run(self, client: TestClient, isolated_evolver_env: Path) -> None:
        main(["run"])
        response = client.get("/genes")
        assert response.status_code == 200
        data = response.json()
        assert "genes" in data
        assert len(data["genes"]) >= 3  # seed genes always present

    def test_events_endpoint_after_run_and_solidify(self, client: TestClient, isolated_evolver_env: Path) -> None:
        _init_git_repo(isolated_evolver_env)
        main(["run"])
        main(["solidify"])
        response = client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert len(data["events"]) > 0

    def test_events_replay_api_after_run_and_solidify(self, client: TestClient, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_git_repo(isolated_evolver_env)
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        main(["run"])
        main(["solidify"])
        response = client.get("/events/replay?since_id=0&limit=100")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert len(data["events"]) > 0
        assert data["since_id"] == 0

    def test_capsules_endpoint_after_run(self, client: TestClient, isolated_evolver_env: Path) -> None:
        main(["run"])
        response = client.get("/capsules")
        assert response.status_code == 200
        data = response.json()
        assert "capsules" in data


# ---------------------------------------------------------------------------
# 3. SQLite event store full pipeline
# ---------------------------------------------------------------------------

class TestSQLiteStoreFullPipeline:
    def test_sqlite_events_after_run_and_solidify(self, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_git_repo(isolated_evolver_env)
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        from evolver.ops import sqlite_store

        before = sqlite_store.event_count()
        code = main(["run"])
        assert code == 0
        code = main(["solidify"])
        assert code == 0
        after = sqlite_store.event_count()
        assert after > before, "SQLite should contain events after solidify"

    def test_sqlite_replay_after_run_and_solidify(self, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _init_git_repo(isolated_evolver_env)
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        from evolver.ops import sqlite_store

        main(["run"])
        main(["solidify"])
        events = sqlite_store.read_events_replay(since_id=0, limit=100)
        assert len(events) > 0
        assert all("id" in e or "event_id" in e for e in events)

    def test_sqlite_range_query(self, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        from evolver.ops import sqlite_store

        sqlite_store.append_event({"id": "early", "timestamp": "2024-01-01T10:00:00Z"})
        sqlite_store.append_event({"id": "mid", "timestamp": "2024-01-01T12:00:00Z"})
        sqlite_store.append_event({"id": "late", "timestamp": "2024-01-01T14:00:00Z"})

        events = sqlite_store.read_events_range("2024-01-01T11:00:00Z", "2024-01-01T13:00:00Z")
        assert len(events) == 1
        assert events[0]["id"] == "mid"

    def test_sqlite_and_jsonl_toggle(self, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Events go to SQLite when enabled, JSONL when disabled."""
        from evolver.gep.asset_store import read_all_events, append_event_jsonl

        # JSONL mode (default)
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "0")
        append_event_jsonl({"id": "jsonl-event", "timestamp": "2024-01-01T00:00:00Z"})
        events_jsonl = read_all_events()
        assert any(e.get("id") == "jsonl-event" for e in events_jsonl)

        # SQLite mode
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        from evolver.ops import sqlite_store
        sqlite_store.append_event({"id": "sqlite-event", "timestamp": "2024-01-01T00:00:00Z"})
        events_sqlite = read_all_events()
        assert any(e.get("id") == "sqlite-event" for e in events_sqlite)


# ---------------------------------------------------------------------------
# 4. Auth + WebSocket full flow
# ---------------------------------------------------------------------------

class TestAuthWebSocketFullFlow:
    def test_websocket_run_with_admin_token(self, client: TestClient, isolated_evolver_env: Path) -> None:
        from evolver.ops.auth_middleware import create_token

        token = create_token(role="admin")
        with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "run"})
            data = ws.receive_json()
            assert data["type"] == "status"

    def test_websocket_solidify_with_admin_token(self, client: TestClient, isolated_evolver_env: Path) -> None:
        from evolver.ops.auth_middleware import create_token

        token = create_token(role="admin")
        with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "solidify"})
            data = ws.receive_json()
            assert data["type"] == "status"

    def test_websocket_run_unauthorized_no_token(self, client: TestClient, isolated_evolver_env: Path) -> None:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "run"})
            with pytest.raises(Exception):
                ws.receive_json()

    def test_websocket_run_readonly_token_fails(self, client: TestClient, isolated_evolver_env: Path) -> None:
        from evolver.ops.auth_middleware import create_token

        token = create_token(role="readonly")
        with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "run"})
            with pytest.raises(Exception):
                ws.receive_json()

    def test_websocket_status_no_token_ok(self, client: TestClient, isolated_evolver_env: Path) -> None:
        """Read-only actions should work without a token."""
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "status"})
            data = ws.receive_json()
            assert data["type"] == "status"


# ---------------------------------------------------------------------------
# 5. Recipe cache + apply
# ---------------------------------------------------------------------------

class TestRecipeCacheAndApply:
    def test_cache_recipe_and_apply(self, isolated_evolver_env: Path) -> None:
        import asyncio
        from evolver.recipe.cache import cache_recipe, get_cached_recipe
        from evolver.recipe.client import apply_recipe

        recipe = {
            "id": "test-recipe",
            "files": [
                {"path": "/README.md", "content": "# Hello {{name}}"},
                {"path": "/src/main.py", "content": "print('hello {{name}}')"},
            ],
            "variables": [{"name": "name", "default": "world"}],
        }
        cache_recipe(recipe)

        cached = get_cached_recipe("test-recipe")
        assert cached is not None
        assert cached["id"] == "test-recipe"

        target = isolated_evolver_env / "recipe_output"
        result = asyncio.run(apply_recipe("test-recipe", target_dir=str(target), use_cache=True))
        assert result["ok"] is True
        assert "README.md" in result["applied"]
        assert "src/main.py" in result["applied"]

        readme = (target / "README.md").read_text()
        assert "# Hello world" in readme

    def test_apply_recipe_conflict_detection(self, isolated_evolver_env: Path) -> None:
        import asyncio
        from evolver.recipe.cache import cache_recipe
        from evolver.recipe.client import apply_recipe

        recipe = {
            "id": "conflict-recipe",
            "files": [{"path": "/existing.txt", "content": "new content"}],
            "variables": [],
        }
        cache_recipe(recipe)

        target = isolated_evolver_env / "recipe_conflict"
        target.mkdir(parents=True, exist_ok=True)
        (target / "existing.txt").write_text("old content")

        result = asyncio.run(apply_recipe("conflict-recipe", target_dir=str(target), use_cache=True))
        assert result["ok"] is True
        assert "existing.txt" in result.get("conflicts", [])
        assert "existing.txt" not in result.get("applied", [])

    def test_list_cached_recipes(self, isolated_evolver_env: Path) -> None:
        from evolver.recipe.cache import cache_recipe, list_cached_recipes, clear_cache

        clear_cache()
        cache_recipe({"id": "r1", "files": []})
        cache_recipe({"id": "r2", "files": []})

        recipes = list_cached_recipes()
        assert len(recipes) == 2
        ids = {r["id"] for r in recipes}
        assert ids == {"r1", "r2"}


# ---------------------------------------------------------------------------
# 6. Peer discovery lifecycle
# ---------------------------------------------------------------------------

class TestPeerLifecycle:
    def test_add_list_remove_peer(self, isolated_evolver_env: Path) -> None:
        from evolver.gep.discovery import add_peer, list_peers, remove_peer

        add_peer("node-1", "http://localhost:8001", {"version": "1.0"})
        peers = list_peers()
        assert len(peers) == 1
        assert peers[0]["node_id"] == "node-1"
        assert peers[0]["endpoint"] == "http://localhost:8001"

        removed = remove_peer("node-1")
        assert removed is True
        assert len(list_peers()) == 0

    def test_peer_persistence_round_trip(self, isolated_evolver_env: Path) -> None:
        from evolver.gep.discovery import add_peer, list_peers, save_peers, load_peers

        add_peer("persist-node", "http://localhost:9000")
        save_peers()

        # Simulate fresh process by clearing in-memory registry
        from evolver.gep import discovery as disc
        disc._PEERS.clear()

        loaded = load_peers()
        # Re-populate registry
        for nid, info in loaded.items():
            disc._PEERS[nid] = info

        peers = list_peers()
        assert any(p["node_id"] == "persist-node" for p in peers)

    def test_stale_peer_filtering(self, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import time
        from evolver.gep.discovery import add_peer, list_peers

        add_peer("fresh-node", "http://localhost:8001")
        # Manually add a stale peer
        from evolver.gep import discovery as disc
        disc._PEERS["stale-node"] = {
            "endpoint": "http://localhost:8002",
            "last_seen": time.time() - 1000,  # way past TTL
            "metadata": {},
        }

        peers = list_peers()
        ids = {p["node_id"] for p in peers}
        assert "fresh-node" in ids
        assert "stale-node" not in ids


# ---------------------------------------------------------------------------
# 7. Cross-subsystem: run → WebUI → replay → CLI token
# ---------------------------------------------------------------------------

class TestCrossSubsystemWorkflow:
    def test_run_then_webui_then_replay(self, client: TestClient, isolated_evolver_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Most comprehensive integration: run cycle → WebUI state → event replay → auth."""
        _init_git_repo(isolated_evolver_env)
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        # 1. Run + solidify cycle
        code = main(["run"])
        assert code == 0
        code = main(["solidify"])
        assert code == 0

        # 2. WebUI status shows no pending solidify
        response = client.get("/status")
        assert response.status_code == 200
        status = response.json()
        assert status["solidify_pending"] is False
        assert status["total_events"] > 0

        # 3. Events endpoint has data
        response = client.get("/events")
        assert response.status_code == 200
        events_data = response.json()
        assert len(events_data["events"]) > 0

        # 4. Replay API returns same events (SQLite only)
        response = client.get("/events/replay?since_id=0&limit=100")
        assert response.status_code == 200
        replay_data = response.json()
        assert len(replay_data["events"]) == len(events_data["events"])

        # 5. Generate admin token via CLI
        from evolver.ops.auth_middleware import create_token
        token = create_token(role="admin")

        # 6. WebSocket run with admin token works
        with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "run"})
            data = ws.receive_json()
            assert data["type"] == "status"

        # 7. WebSocket run without token fails
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"action": "run"})
            with pytest.raises(Exception):
                ws.receive_json()

    def test_solidify_in_git_clears_pending(self, client: TestClient, isolated_evolver_env: Path) -> None:
        _init_git_repo(isolated_evolver_env)

        main(["run"])
        response = client.get("/status")
        assert response.json()["solidify_pending"] is True

        main(["solidify"])
        response = client.get("/status")
        assert response.json()["solidify_pending"] is False
