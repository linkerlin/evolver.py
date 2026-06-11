"""Tests for evolver.proxy.extensions.trace_control."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from evolver.proxy.extensions.trace_control import TraceControl, create_trace_control


class TestCreateTraceControl:
    def test_returns_instance(self):
        ctrl = create_trace_control()
        assert isinstance(ctrl, TraceControl)


class TestEnableDisableModule:
    def test_enable_module(self):
        ctrl = create_trace_control()
        result = ctrl.enable_module("proxy", "debug")
        assert result["ok"] is True
        assert "proxy" in ctrl._enabled_modules

    def test_disable_module(self):
        ctrl = create_trace_control()
        ctrl.enable_module("proxy")
        result = ctrl.disable_module("proxy")
        assert result["ok"] is True
        assert "proxy" not in ctrl._enabled_modules


class TestGlobalLevel:
    def test_set_global_level(self):
        ctrl = create_trace_control()
        result = ctrl.set_global_level("debug")
        assert result["ok"] is True
        assert ctrl._global_level == "debug"


class TestGetStatus:
    def test_empty_status(self):
        ctrl = create_trace_control()
        status = ctrl.get_status()
        assert status["global_level"] == "info"
        assert status["enabled_modules"] == []

    def test_with_modules(self):
        ctrl = create_trace_control()
        ctrl.enable_module("proxy")
        ctrl.enable_module("router")
        status = ctrl.get_status()
        assert status["enabled_modules"] == ["proxy", "router"]


class TestGenerateReport:
    def test_generates_file(self, tmp_path: Path):
        ctrl = create_trace_control(trace_dir=tmp_path)
        result = ctrl.generate_report()
        assert result["ok"] is True
        assert "report_id" in result
        report_path = Path(result["path"])
        assert report_path.exists()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert "modules" in data
        assert data["global_level"] == "info"

    def test_report_contains_modules(self, tmp_path: Path):
        ctrl = create_trace_control(trace_dir=tmp_path)
        ctrl.enable_module("proxy")
        result = ctrl.generate_report()
        report_path = Path(result["path"])
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert "proxy" in data["modules"]


class TestUploadReport:
    def test_upload_not_found(self, tmp_path: Path):
        ctrl = create_trace_control(trace_dir=tmp_path)
        result = ctrl.upload_report("missing")
        assert result["ok"] is False
        assert result["error"] == "report_not_found"

    def test_upload_feature_disabled(self, tmp_path: Path):
        ctrl = create_trace_control(trace_dir=tmp_path)
        gen = ctrl.generate_report()
        result = ctrl.upload_report(gen["report_id"])
        assert result["ok"] is False
        assert result["error"] == "feature_disabled"

    def test_upload_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_TRACE_UPLOAD", "true")
        monkeypatch.setenv("A2A_HUB_URL", "https://hub.test")
        ctrl = create_trace_control(trace_dir=tmp_path)
        gen = ctrl.generate_report()
        with respx.mock:
            respx.post("https://hub.test/v1/a2a/trace/report").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            result = ctrl.upload_report(gen["report_id"])
        assert result["ok"] is True
        assert result["uploaded"] is True
