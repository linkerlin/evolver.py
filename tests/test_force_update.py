"""Tests for evolver.force_update."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

import evolver.force_update as fu
from evolver.force_update import (
    FORCE_UPDATE_BUSY,
    FORCE_UPDATE_FAIL_CODES,
    FORCE_UPDATE_NOOP,
    _backup_dir,
    _normalize_version_floor,
    _parse_version,
    _prune_backups,
    _safe_extract,
    _satisfies_floor,
    _verify_checksum,
    apply_update,
    execute_force_update,
    force_update,
    is_force_update_failure,
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
