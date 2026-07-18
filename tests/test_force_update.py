"""Tests for evolver.force_update."""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path

import pytest

import evolver.force_update as fu
from evolver.force_update import (
    FORCE_UPDATE_BUSY,
    FORCE_UPDATE_FAIL_CODES,
    FORCE_UPDATE_NOOP,
    KEEP_LIST,
    _backup_dir,
    _normalize_version_floor,
    _parse_version,
    _prune_backups,
    _safe_extract,
    _satisfies_floor,
    _verify_checksum,
    apply_update,
    check_install_guard,
    execute_force_update,
    force_update,
    has_strong_evolver_install_markers,
    install_downloaded_tree,
    is_force_update_failure,
    is_force_update_keep_entry,
    is_newer,
    report_force_update_outcome,
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

        result = force_update(current_version="1.0.0")
        assert result["success"] is False
        assert result["reason"] == "disabled_in_noninteractive"


# ---------------------------------------------------------------------------
# v1.90.0 contract: sentinels, idempotent floor, concurrency guard, coded failures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_in_flight() -> None:
    fu._reset_in_flight_for_testing()
    yield
    fu._reset_in_flight_for_testing()


class TestSentinels:
    def test_busy_and_noop_are_distinct_singletons(self) -> None:
        assert FORCE_UPDATE_BUSY is not FORCE_UPDATE_NOOP
        for other in (True, False, None, 0, 1, "", "true"):
            assert FORCE_UPDATE_BUSY is not other
            assert FORCE_UPDATE_NOOP is not other


class TestVersionFloor:
    def test_normalize_strips_operators_and_v(self) -> None:
        assert _normalize_version_floor(">=1.88.0") == "1.88.0"
        assert _normalize_version_floor("v1.88.0") == "1.88.0"
        assert _normalize_version_floor("  =1.88.3 ") == "1.88.3"

    def test_satisfies_floor_exact_and_newer(self) -> None:
        assert _satisfies_floor("1.89.14", "1.89.14") is True  # exact
        assert _satisfies_floor("1.89.14", ">=1.85.0") is True  # newer than floor
        assert _satisfies_floor("1.89.14", "1.85.0") is True  # bare floor, current newer

    def test_satisfies_floor_below(self) -> None:
        assert _satisfies_floor("1.85.0", "1.89.0") is False


class TestIdempotentNoop:
    """required_version is a minimum floor: a satisfied install must NOOP."""

    @staticmethod
    def _assert_noop(monkeypatch: pytest.MonkeyPatch, required: str, current: str) -> None:
        """required is a floor: if current satisfies it, NOOP (no download)."""
        monkeypatch.setattr(fu, "force_update", lambda **_kw: pytest.fail("must not download"))
        assert (
            execute_force_update(required_version=required, current_version=current)
            is FORCE_UPDATE_NOOP
        )

    def test_exact_match_returns_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, "1.89.14", "1.89.14")

    def test_range_form_after_operator_strip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, ">=1.89.0", "1.89.14")

    def test_newer_current_does_not_downgrade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, "1.85.0", "1.89.14")

    def test_leading_v_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, "v1.85.0", "v1.89.14")

    def test_version_mismatch_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # current < required → not NOOP → proceeds to force_update (here: disabled).
        disabled = {
            "ok": False,
            "success": False,
            "code": "disabled_in_noninteractive",
            "detail": "x",
        }
        monkeypatch.setattr(fu, "force_update", lambda **_kw: disabled)
        result = execute_force_update(required_version="9999.0.0", current_version="1.89.14")
        assert result is not FORCE_UPDATE_NOOP

    def test_bad_required_version_is_coded_failure(self) -> None:
        result = execute_force_update(required_version="not-a-version", current_version="1.89.14")
        assert is_force_update_failure(result)
        assert result["code"] == "bad_required_version"

    def test_unparsable_current_is_coded_failure(self) -> None:
        # #213 anti-downgrade guard: refuse to act on an install we can't version-check.
        result = execute_force_update(required_version="1.85.0", current_version="garbage")
        assert is_force_update_failure(result)
        assert result["code"] == "current_version_unparsable"


class TestConcurrencyGuard:
    def test_reentrant_call_returns_busy_without_second_download(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict] = []

        def fake_force_update(**kw: object) -> object:
            calls.append(kw)
            # Simulate a re-entrant call landing mid-upgrade.
            return execute_force_update(required_version="0.0.1", current_version="1.89.14")

        monkeypatch.setattr(fu, "force_update", fake_force_update)
        # required newer than current → falls through into force_update.
        result = execute_force_update(required_version="9999.0.0", current_version="1.89.14")
        assert result is FORCE_UPDATE_BUSY
        assert len(calls) == 1  # the inner download path was entered exactly once
        assert fu._in_flight is False  # mutex reset after return

    def test_mutex_resets_on_throw(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**_kw: object) -> None:
            raise RuntimeError("simulated upgrade failure")

        monkeypatch.setattr(fu, "force_update", boom)
        with pytest.raises(RuntimeError):
            execute_force_update(required_version="9999.0.0", current_version="1.89.14")
        assert fu._in_flight is False  # finally semantics


class TestFailureCodes:
    def test_failure_is_frozen_with_code_and_detail(self) -> None:
        result = fu._failure("copy_failed", "src/evolver/cli.py")
        assert result["ok"] is False
        assert isinstance(result["code"], str)
        assert isinstance(result["detail"], str)
        with pytest.raises((TypeError, AttributeError)):
            result["code"] = "tampered"  # frozen — mutation must fail

    def test_is_force_update_failure(self) -> None:
        f = fu._failure("copy_failed", "x")
        assert is_force_update_failure(f) is True
        assert is_force_update_failure(True) is False
        assert is_force_update_failure(False) is False
        assert is_force_update_failure(None) is False
        assert is_force_update_failure({"success": True}) is False

    def test_fail_codes_registry_well_formed(self) -> None:
        assert isinstance(FORCE_UPDATE_FAIL_CODES, frozenset)
        assert FORCE_UPDATE_FAIL_CODES  # non-empty
        assert all(isinstance(c, str) and c for c in FORCE_UPDATE_FAIL_CODES)
        assert "disabled_in_noninteractive" in FORCE_UPDATE_FAIL_CODES


class TestReportOutcome:
    def test_noop_writes_skipped_without_from_version(self, tmp_path: Path) -> None:
        state = tmp_path / "fu-state.json"
        rec = report_force_update_outcome(noop=True, updated=True, state_path=state)
        assert rec == {"status": "skipped"}  # noop wins defensively
        assert "from_version" not in rec

    def test_updated_writes_success_with_from_version(self) -> None:
        rec = report_force_update_outcome(updated=True, from_version="1.89.2", to_version="1.89.14")
        assert rec["status"] == "success"
        assert rec["from_version"] == "1.89.2"


class TestSafeExtract:
    def test_skips_path_traversal_entries(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("safe.txt", "ok")
            zf.writestr("../../escaped.txt", "pwned")
            zf.writestr("sub/inner.txt", "inner")
        dest = tmp_path / "dest"
        dest.mkdir()
        with zipfile.ZipFile(archive, "r") as zf:
            _safe_extract(zf, dest)
        assert (dest / "safe.txt").read_text() == "ok"
        assert (dest / "sub" / "inner.txt").read_text() == "inner"
        # The traversal entry must not escape dest.
        assert not (tmp_path / "escaped.txt").exists()


# ---------------------------------------------------------------------------
# Sprint 14.2: keep-list expansion, mid-copy wedge, install-guard / bootstrap
# ---------------------------------------------------------------------------


def _write_pkg(root: Path, version: str, *, name: str = "@evomap/evolver") -> None:
    (root / "package.json").write_text(
        json.dumps({"name": name, "version": version}),
        encoding="utf-8",
    )


def _populate_old_install(root: Path, version: str = "1.0.0") -> None:
    _write_pkg(root, version)
    (root / "index.js").write_text("// old", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "evolve.js").write_text("// old src", encoding="utf-8")


def _populate_download(root: Path, version: str) -> None:
    _write_pkg(root, version)
    (root / "index.js").write_text(f"// v{version}", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "evolve.js").write_text(f"// src v{version}", encoding="utf-8")


def _populate_keeplist_install(root: Path) -> None:
    _populate_old_install(root)
    (root / "node_modules").mkdir()
    (root / "memory").mkdir()
    (root / ".git").mkdir()
    (root / "MEMORY.md").write_text("# mem\n", encoding="utf-8")
    (root / ".env").write_text(
        "A2A_HUB_URL=https://hub.example.com\nA2A_NODE_SECRET=s3cr3t\n",
        encoding="utf-8",
    )
    (root / ".env.local").write_text("DEBUG=1\n", encoding="utf-8")
    (root / "USER.md").write_text("# my notes\n", encoding="utf-8")
    (root / ".evolver").mkdir()
    (root / ".evolver" / "config.json").write_text('{"workspaceId":"wid_test"}', encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "evolver.log").write_text("local log\n", encoding="utf-8")
    (root / "skills").mkdir()
    (root / "skills" / "mine.md").write_text("skill", encoding="utf-8")


class TestKeepList:
    def test_keep_list_covers_node_v18915_entries(self) -> None:
        for name in (
            "node_modules",
            "memory",
            ".git",
            "MEMORY.md",
            ".env",
            ".env.local",
            "USER.md",
            ".evolver",
            "logs",
            "skills",
            ".evomap",
        ):
            assert is_force_update_keep_entry(name), name
            assert name in KEEP_LIST

    def test_install_preserves_keep_list_and_replaces_code(self, tmp_path: Path) -> None:
        install = tmp_path / "install"
        download = tmp_path / "download"
        install.mkdir()
        download.mkdir()
        _populate_keeplist_install(install)
        _populate_download(download, "999.999.999")
        # Release archive ships poisoned keep-list paths — must not win.
        (download / ".env").write_text("A2A_NODE_SECRET=from-release\n", encoding="utf-8")
        (download / "USER.md").write_text("# release\n", encoding="utf-8")
        (download / "memory").mkdir()
        (download / "memory" / "state.json").write_text('{"from":"release"}', encoding="utf-8")

        result = install_downloaded_tree(install, download, required_version="999.999.999")
        assert result.get("ok") is True or result.get("success") is True
        assert (install / ".env").read_text(encoding="utf-8") == (
            "A2A_HUB_URL=https://hub.example.com\nA2A_NODE_SECRET=s3cr3t\n"
        )
        assert (install / ".env.local").read_text(encoding="utf-8") == "DEBUG=1\n"
        assert (install / "USER.md").read_text(encoding="utf-8") == "# my notes\n"
        assert (install / ".evolver" / "config.json").read_text(encoding="utf-8") == (
            '{"workspaceId":"wid_test"}'
        )
        assert (install / "logs" / "evolver.log").read_text(encoding="utf-8") == "local log\n"
        assert (install / "memory").is_dir()
        assert (install / ".git").is_dir()
        assert (install / "MEMORY.md").read_text(encoding="utf-8") == "# mem\n"
        assert (install / "skills" / "mine.md").read_text(encoding="utf-8") == "skill"
        assert (install / "index.js").read_text(encoding="utf-8") == "// v999.999.999"
        assert (install / "src" / "evolve.js").read_text(encoding="utf-8") == (
            "// src v999.999.999"
        )
        assert (
            json.loads((install / "package.json").read_text(encoding="utf-8"))["version"]
            == "999.999.999"
        )

    def test_apply_update_also_respects_expanded_keep_list(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        source = tmp_path / "source"
        target.mkdir()
        source.mkdir()
        (target / ".env").write_text("SECRET=local\n", encoding="utf-8")
        (target / "USER.md").write_text("mine", encoding="utf-8")
        (target / "code.py").write_text("old", encoding="utf-8")
        (source / ".env").write_text("SECRET=release\n", encoding="utf-8")
        (source / "code.py").write_text("new", encoding="utf-8")
        result = apply_update(source, target)
        assert result["success"] is True
        assert (target / ".env").read_text(encoding="utf-8") == "SECRET=local\n"
        assert (target / "USER.md").read_text(encoding="utf-8") == "mine"
        assert (target / "code.py").read_text(encoding="utf-8") == "new"


class TestMidCopyWedge:
    def test_mid_copy_failure_leaves_old_package_json(self, tmp_path: Path) -> None:
        install = tmp_path / "install"
        download = tmp_path / "download"
        install.mkdir()
        download.mkdir()
        _populate_old_install(install, "1.0.0")
        _populate_download(download, "2.0.0")

        real_copy_tree = shutil.copytree

        def boom_src(src: Path, dst: Path) -> None:
            if src.name == "src":
                raise OSError(errno.ENOSPC, "no space left on device")
            if dst.exists():
                shutil.rmtree(dst)
            real_copy_tree(src, dst)

        fu._copy_tree_fn = boom_src  # type: ignore[assignment]
        try:
            result = install_downloaded_tree(install, download, required_version="2.0.0")
        finally:
            fu._copy_tree_fn = None

        assert is_force_update_failure(result)
        assert result["code"] == "copy_failed"
        assert (install / "package.json").is_file()
        assert (
            json.loads((install / "package.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
        )

    def test_next_attempt_self_heals_after_mid_copy_failure(self, tmp_path: Path) -> None:
        install = tmp_path / "install"
        download = tmp_path / "download"
        install.mkdir()
        download.mkdir()
        _populate_old_install(install, "1.0.0")
        _populate_download(download, "2.0.0")

        real_copy_tree = shutil.copytree
        fail_once = {"n": 0}

        def boom_once(src: Path, dst: Path) -> None:
            if src.name == "src" and fail_once["n"] == 0:
                fail_once["n"] += 1
                raise OSError(errno.ENOSPC, "no space left on device")
            if dst.exists():
                shutil.rmtree(dst)
            real_copy_tree(src, dst)

        fu._copy_tree_fn = boom_once  # type: ignore[assignment]
        try:
            first = install_downloaded_tree(install, download, required_version="2.0.0")
            assert is_force_update_failure(first)
            # Rebuild download (install_downloaded_tree may remove temp_target)
            if not download.exists():
                download.mkdir()
                _populate_download(download, "2.0.0")
            fu._copy_tree_fn = None
            second = install_downloaded_tree(install, download, required_version="2.0.0")
        finally:
            fu._copy_tree_fn = None

        assert second.get("ok") is True or second.get("success") is True
        assert (
            json.loads((install / "package.json").read_text(encoding="utf-8"))["version"] == "2.0.0"
        )
        assert (install / "src" / "evolve.js").read_text(encoding="utf-8") == "// src v2.0.0"
        assert (install / "index.js").read_text(encoding="utf-8") == "// v2.0.0"

    def test_package_json_commit_failure_restores_old_marker(self, tmp_path: Path) -> None:
        install = tmp_path / "install"
        download = tmp_path / "download"
        install.mkdir()
        download.mkdir()
        _populate_old_install(install, "1.0.0")
        _populate_download(download, "2.0.0")

        def boom_pkg_commit(src: Path, dst: Path) -> None:
            if src.name.endswith(".evolver-tmp") and dst.name == "package.json":
                raise OSError(errno.EPERM, "package.json is locked")
            os.replace(src, dst)

        fu._rename_fn = boom_pkg_commit  # type: ignore[assignment]
        try:
            result = install_downloaded_tree(install, download, required_version="2.0.0")
        finally:
            fu._rename_fn = None

        assert is_force_update_failure(result)
        assert result["code"] == "copy_failed"
        assert "package.json commit" in result["detail"]
        assert (
            json.loads((install / "package.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
        )
        leftovers = [
            p.name
            for p in install.iterdir()
            if re.fullmatch(r"package\.json\..*evolver-(tmp|old)", p.name)
        ]
        assert leftovers == []


class TestInstallGuard:
    def test_name_mismatch_fail_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "bad"
        root.mkdir()
        _write_pkg(root, "1.0.0", name="totally-unrelated")
        result = check_install_guard(root)
        assert is_force_update_failure(result)
        assert result["code"] == "install_guard_name_mismatch"

    def test_unreadable_without_markers_fail_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        result = check_install_guard(root)
        assert is_force_update_failure(result)
        assert result["code"] == "install_guard_unreadable"

    def test_strong_markers_allow_bootstrap_recovery(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = tmp_path / "boot"
        root.mkdir()
        # Required marker + two others (no package.json).
        fu_path = root / "src" / "evolver" / "force_update.py"
        fu_path.parent.mkdir(parents=True)
        fu_path.write_text(
            "def execute_force_update(): ...\nFORCE_UPDATE_FAIL_CODES = set()\n",
            encoding="utf-8",
        )
        paths_py = root / "src" / "evolver" / "gep" / "paths.py"
        paths_py.parent.mkdir(parents=True)
        paths_py.write_text(
            "def get_repo_root(): ...\ndef get_evolver_install_root(): ...\n",
            encoding="utf-8",
        )
        a2a = root / "src" / "evolver" / "gep" / "a2a_protocol.py"
        a2a.write_text(
            "def report_force_update_outcome(): ...\nA2A = True\n",
            encoding="utf-8",
        )
        assert has_strong_evolver_install_markers(root) is True
        with caplog.at_level(logging.WARNING):
            result = check_install_guard(root)
        assert result is None
        assert "bootstrap recovery allowed" in caplog.text

    def test_recover_package_json_from_evolver_old(self, tmp_path: Path) -> None:
        root = tmp_path / "rec"
        root.mkdir()
        backup = root / "package.json.12345.evolver-old"
        backup.write_text(
            json.dumps({"name": "@evomap/evolver", "version": "1.2.3"}),
            encoding="utf-8",
        )
        assert check_install_guard(root) is None
        assert (root / "package.json").is_file()
        assert not backup.exists()

    def test_version_mismatch_and_incomplete_download(self, tmp_path: Path) -> None:
        install = tmp_path / "install"
        download = tmp_path / "download"
        install.mkdir()
        download.mkdir()
        _populate_old_install(install)
        _write_pkg(download, "3.0.0")
        (download / "index.js").write_text("// v3", encoding="utf-8")
        bad = install_downloaded_tree(install, download, required_version="9.0.0")
        assert is_force_update_failure(bad)
        assert bad["code"] == "downloaded_version_mismatch"

        # Missing index → incomplete
        (download / "index.js").unlink()
        incomplete = install_downloaded_tree(install, download, required_version="3.0.0")
        assert is_force_update_failure(incomplete)
        assert incomplete["code"] == "download_incomplete"
