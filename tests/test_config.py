"""Tests for evolver.config — equivalent to evolver/test/config.test.js."""

from __future__ import annotations

import pytest

from evolver import config


def test_env_int_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_INT", raising=False)
    assert config.env_int("TEST_INT", 42) == 42


def test_env_int_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT", "7")
    assert config.env_int("TEST_INT", 42) == 7


def test_env_int_invalid_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT", "abc")
    assert config.env_int("TEST_INT", 42) == 42


def test_env_positive_int_rejects_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_POS", "0")
    monkeypatch.setattr(config, "_ENV_WARNED", set())
    with pytest.warns(UserWarning, match="is not a positive integer"):
        assert config.env_positive_int("TEST_POS", 100) == 100


def test_env_positive_int_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_POS", "-5")
    monkeypatch.setattr(config, "_ENV_WARNED", set())
    with pytest.warns(UserWarning, match="is not a positive integer"):
        assert config.env_positive_int("TEST_POS", 100) == 100


def test_resolve_hub_url_default() -> None:
    assert config.resolve_hub_url() == config.PUBLIC_DEFAULT_HUB_URL


def test_resolve_hub_url_allows_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://private.example.com")
    assert config.resolve_hub_url() == "https://private.example.com"


def test_resolve_hub_url_rejects_http_without_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "http://insecure.example.com")
    with pytest.raises(ValueError):
        config.resolve_hub_url()


def test_resolve_hub_url_allows_http_with_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "http://insecure.example.com")
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    assert config.resolve_hub_url() == "http://insecure.example.com"


def test_resolve_proxy_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_PROXY_PORT", raising=False)
    monkeypatch.delenv("EVOMAP_PROXY_PORT", raising=False)
    assert config.resolve_proxy_port() == config.DEFAULT_PROXY_PORT == 8081


def test_resolve_proxy_port_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_PROXY_PORT", "9090")
    assert config.resolve_proxy_port() == 9090


def test_resolve_webui_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_WEBUI_PORT", raising=False)
    assert config.resolve_webui_port() == config.DEFAULT_WEBUI_PORT == 8080


def test_resolve_webui_port_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_WEBUI_PORT", "3000")
    assert config.resolve_webui_port() == 3000


def test_proxy_local_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_PROXY_PORT", raising=False)
    monkeypatch.delenv("EVOMAP_PROXY_PORT", raising=False)
    url = config.proxy_local_url("v1/messages")
    assert url.endswith("/v1/a2a/v1/messages")
    assert ":8081" in url


# ---------------------------------------------------------------------------
# Gap 4+5: Anti-abuse telemetry mode + Outcome report mode (via EvolverConfig)
# ---------------------------------------------------------------------------


def test_anti_abuse_telemetry_mode_default_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_CONFIG", '{"quiet_legacy_warning":true}')
    assert config.anti_abuse_telemetry_mode() == "heartbeat"


def test_anti_abuse_telemetry_mode_empty_is_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty value counts as UNSET — default-on behavior preserved."""
    monkeypatch.setenv("EVOLVER_CONFIG", '{"anti_abuse_telemetry":"","quiet_legacy_warning":true}')
    assert config.anti_abuse_telemetry_mode() == "heartbeat"


def test_anti_abuse_telemetry_mode_explicit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    for v in ("0", "false", "no", "off"):
        monkeypatch.setenv(
            "EVOLVER_CONFIG",
            json.dumps({"anti_abuse_telemetry": v, "quiet_legacy_warning": True}),
        )
        assert config.anti_abuse_telemetry_mode() == "off"


def test_outcome_report_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_CONFIG", '{"quiet_legacy_warning":true}')
    assert config.outcome_report_mode() == "off"


def test_outcome_report_mode_on(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    for v in ("on", "enforce", "true"):
        monkeypatch.setenv(
            "EVOLVER_CONFIG",
            json.dumps({"outcome_report": v, "quiet_legacy_warning": True}),
        )
        assert config.outcome_report_mode() == "on"


# ---------------------------------------------------------------------------
# P0-4 Slice D: EvolverConfig file + inline JSON + nested sections + charter pin
# ---------------------------------------------------------------------------


def test_evolver_config_merges_settings_file_env_and_runtime_override(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    state_root = tmp_path / "evolver_state"
    state_root.mkdir(parents=True)
    (state_root / "config.json").write_text(
        json.dumps(
            {
                "cycle_timeout_ms": 12_345,
                "autopoiesis": {"enabled": False, "write": False},
                "memory_graph": {"max_size_mb": 25.0, "retention_count": 3},
                "trigger": {"max_cycles_per_day": 9},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(state_root))
    monkeypatch.setenv(
        "EVOLVER_CONFIG",
        json.dumps({"progress_update_ms": 2_500, "quiet_legacy_warning": True}),
    )

    cfg = config.get_config()
    assert cfg.cycle_timeout_ms == 12_345
    assert cfg.progress_update_ms == 2_500
    assert cfg.autopoiesis is False
    assert cfg.autopoiesis_write is False
    assert cfg.memory_graph_max_size_mb == 25.0
    assert cfg.memory_graph_retention_count == 3
    assert cfg.trigger_max_cycles_per_day == 9

    override_file = tmp_path / "override.json"
    override_file.write_text(
        json.dumps({"runtime": {"cycle_timeout_ms": 9_999, "sqlite_store": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOLVER_CONFIG", str(override_file))
    cfg2 = config.get_config()
    assert cfg2.cycle_timeout_ms == 9_999
    assert cfg2.sqlite_store is True

    config.set_runtime_config_override(cycle_timeout_ms=4_321)
    assert config.get_config().cycle_timeout_ms == 4_321
    config.clear_runtime_config_overrides("cycle_timeout_ms")
    assert config.get_config().cycle_timeout_ms == 9_999


def test_src_evolver_env_var_budget_meets_charter() -> None:
    from pathlib import Path

    from evolver.ops.charter_check import count_unique_evolver_envs

    repo_root = Path(__file__).resolve().parents[1]
    count = count_unique_evolver_envs(repo_root)
    assert count <= 35, f"Expected <= 35 unique EVOLVER_* env vars in src/, got {count}"
