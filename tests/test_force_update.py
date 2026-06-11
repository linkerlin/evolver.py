"""Tests for evolver.force_update."""

from __future__ import annotations

import pytest

from evolver.force_update import (
    _backup_dir,
    _parse_version,
    _prune_backups,
    _verify_checksum,
    apply_update,
    is_newer,
)


class TestVersionParsing:
    def test_parse(self):
        assert _parse_version("1.89.2") == (1, 89, 2)

    def test_parse_with_v(self):
        assert _parse_version("v2.0.0") == (2, 0, 0)

    def test_parse_short(self):
        assert _parse_version("1.5") == (1, 5, 0)

    def test_parse_non_numeric(self):
        assert _parse_version("1.a.3") == (1, 0, 3)

    def test_is_newer(self):
        assert is_newer("1.90.0", "1.89.2")
        assert not is_newer("1.89.2", "1.90.0")
        assert not is_newer("1.89.2", "1.89.2")

    def test_major_bump(self):
        assert is_newer("2.0.0", "1.99.99")


class TestVerifyChecksum:
    def test_match(self, tmp_path):
        import hashlib

        p = tmp_path / "f.txt"
        p.write_text("hello")
        h = hashlib.sha256(b"hello").hexdigest()
        assert _verify_checksum(p, h)

    def test_none_expected(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("hello")
        assert _verify_checksum(p, None)

    def test_mismatch(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("hello")
        assert not _verify_checksum(p, "0" * 64)


class TestBackup:
    def test_backup_dir(self, tmp_path):
        src = tmp_path / "proj"
        src.mkdir()
        (src / "a.py").write_text("x")
        backup_root = tmp_path / "backups"
        backup = _backup_dir(src, backup_root)
        assert backup.exists()
        assert (backup / "a.py").read_text() == "x"

    def test_prune_old(self, tmp_path):
        old = tmp_path / "old"
        old.mkdir()

        # Manually set mtime far in the past
        import os

        os.utime(old, (1, 1))
        _prune_backups(tmp_path, days=0)
        assert not old.exists()


class TestApplyUpdate:
    def test_success(self, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        (target / "replace.txt").write_text("old")

        source = tmp_path / "source"
        source.mkdir()
        (source / "replace.txt").write_text("new")
        (source / "new.txt").write_text("fresh")

        result = apply_update(source, target, keep={"keep.txt"})
        assert result["success"] is True
        assert (target / "replace.txt").read_text() == "new"
        assert (target / "new.txt").read_text() == "fresh"
        assert (target / "keep.txt").read_text() == "keep"

    def test_missing_target(self, tmp_path):
        with pytest.raises(RuntimeError):
            apply_update(tmp_path / "src", tmp_path / "noexist")

    def test_missing_source(self, tmp_path):
        with pytest.raises(RuntimeError):
            apply_update(tmp_path / "noexist", tmp_path / "tgt")


class TestForceUpdateDisabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("EVOLVER_FORCE_UPDATE", raising=False)
        monkeypatch.delenv("CI", raising=False)
        from evolver.force_update import force_update

        result = force_update(current_version="1.0.0")
        assert result["success"] is False
        assert result["reason"] == "disabled_in_noninteractive"
