"""Tests for evolver.gep.feature_flags."""

import json
from unittest.mock import patch

from evolver.gep.feature_flags import (
    DEFAULT_FLAGS,
    _load_disk_flags,
    get_all_flags,
    is_enabled,
    reset_to_defaults,
    set_flag,
)


class TestEnvLayer:
    def test_env_override_true(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "1")
        assert is_enabled("enable_auto_buyer") is True

    def test_env_override_false(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "0")
        assert is_enabled("enable_auto_buyer") is False

    def test_env_no_override(self, monkeypatch):
        monkeypatch.delenv("EVOLVER_FF_ENABLE_AUTO_BUYER", raising=False)
        # Falls through to disk/default
        assert is_enabled("enable_auto_buyer") == DEFAULT_FLAGS["enable_auto_buyer"]


class TestDiskLayer:
    def test_disk_flag_persisted(self, tmp_path):
        with patch("evolver.gep.feature_flags._get_config_dir", return_value=tmp_path):
            set_flag("enable_auto_buyer", True)
            assert is_enabled("enable_auto_buyer") is True
            # Verify file exists
            assert (tmp_path / "disk_flags.json").exists()

    def test_disk_flag_disable(self, tmp_path):
        with patch("evolver.gep.feature_flags._get_config_dir", return_value=tmp_path):
            set_flag("enable_auto_buyer", False)
            assert is_enabled("enable_auto_buyer") is False

    def test_hot_reload(self, tmp_path):
        with patch("evolver.gep.feature_flags._get_config_dir", return_value=tmp_path):
            set_flag("enable_auto_buyer", True)
            # Modify file directly
            path = tmp_path / "disk_flags.json"
            data = json.loads(path.read_text())
            data["enable_auto_buyer"] = False
            path.write_text(json.dumps(data))
            # Should pick up new value (within TTL might still cache, but force reload)
            flags = _load_disk_flags(force=True)
            assert flags["enable_auto_buyer"] is False


class TestGetAllFlags:
    def test_merge_order(self, monkeypatch, tmp_path):
        # Default = False, Disk = True, Env = False
        monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "0")
        with patch("evolver.gep.feature_flags._get_config_dir", return_value=tmp_path):
            set_flag("enable_auto_buyer", True)
            all_flags = get_all_flags()
            # Env wins
            assert all_flags["enable_auto_buyer"] is False


class TestReset:
    def test_reset_to_defaults(self, tmp_path):
        with patch("evolver.gep.feature_flags._get_config_dir", return_value=tmp_path):
            set_flag("enable_auto_buyer", True)
            reset_to_defaults()
            assert is_enabled("enable_auto_buyer") == DEFAULT_FLAGS["enable_auto_buyer"]


class TestDefaultFlags:
    def test_known_flags_exist(self):
        for name in DEFAULT_FLAGS:
            assert isinstance(DEFAULT_FLAGS[name], bool)
