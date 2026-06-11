"""Tests for evolver.adapters.reset_secret."""

from __future__ import annotations

from pathlib import Path

from evolver.adapters.reset_secret import (
    _generate_node_id,
    _generate_secret,
    _update_env_file,
    reset_local_secret,
)


class TestGenerateSecret:
    def test_length(self) -> None:
        s = _generate_secret()
        assert len(s) == 64  # 32 bytes -> 64 hex chars

    def test_uniqueness(self) -> None:
        assert _generate_secret() != _generate_secret()

    def test_custom_length(self) -> None:
        s = _generate_secret(length=16)
        assert len(s) == 32


class TestGenerateNodeId:
    def test_prefix(self) -> None:
        nid = _generate_node_id()
        assert nid.startswith("node_")

    def test_length(self) -> None:
        nid = _generate_node_id()
        assert len(nid) == len("node_") + 16  # 8 bytes hex


class TestUpdateEnvFile:
    def test_creates_file(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        assert not env_path.exists()
        _update_env_file(env_path, "A2A_NODE_SECRET", "abc123")
        assert env_path.exists()
        content = env_path.read_text()
        assert "A2A_NODE_SECRET=abc123" in content

    def test_updates_existing_key(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("FOO=1\nA2A_NODE_SECRET=old\nBAR=2\n", encoding="utf-8")
        _update_env_file(env_path, "A2A_NODE_SECRET", "new")
        content = env_path.read_text()
        assert "A2A_NODE_SECRET=new" in content
        assert "old" not in content
        assert "FOO=1" in content
        assert "BAR=2" in content

    def test_appends_if_missing(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("FOO=1\n", encoding="utf-8")
        _update_env_file(env_path, "A2A_NODE_SECRET", "val")
        lines = env_path.read_text().splitlines()
        assert lines[-1] == "A2A_NODE_SECRET=val"

    def test_handles_whitespace_variants(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("A2A_NODE_SECRET = old\n", encoding="utf-8")
        _update_env_file(env_path, "A2A_NODE_SECRET", "new")
        content = env_path.read_text()
        assert "A2A_NODE_SECRET=new" in content
        assert "old" not in content


class TestResetLocalSecret:
    def test_invalid_directory(self) -> None:
        result = reset_local_secret(project_dir="/nonexistent/path/12345")
        assert result["ok"] is False
        assert "Not a directory" in result["error"]

    def test_creates_env(self, tmp_path: Path) -> None:
        result = reset_local_secret(project_dir=tmp_path)
        assert result["ok"] is True
        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "A2A_NODE_SECRET=" in content
        assert result["secret"] in content
        assert result["node_id"] is None

    def test_also_node_id(self, tmp_path: Path) -> None:
        result = reset_local_secret(project_dir=tmp_path, also_node_id=True)
        assert result["ok"] is True
        assert result["node_id"] is not None
        env_path = tmp_path / ".env"
        content = env_path.read_text()
        assert f"A2A_NODE_ID={result['node_id']}" in content

    def test_dry_run(self, tmp_path: Path) -> None:
        result = reset_local_secret(project_dir=tmp_path, dry_run=True)
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert not (tmp_path / ".env").exists()

    def test_preserves_existing_env(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("FOO=bar\n", encoding="utf-8")
        result = reset_local_secret(project_dir=tmp_path)
        assert result["ok"] is True
        content = env_path.read_text()
        assert "FOO=bar" in content
        assert "A2A_NODE_SECRET=" in content
