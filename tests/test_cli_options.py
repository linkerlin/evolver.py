"""Proxy CLI path options tests.

Port of ``evolver/test/proxyCliOptions.test.js`` (v1.93.0).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from evolver.cli_options import (
    expand_home_path,
    parse_proxy_cli_path_options,
    prepare_proxy_cli_environment,
)

ENV_KEYS = [
    "EVOMAP_DIR",
    "EVOLVER_HOME",
    "EVOMAP_HOME",
    "EVOLVER_SETTINGS_DIR",
    "EVOLVER_PROXY_STORE",
    "EVOLVER_PROXY_SETTINGS_FILE",
    "EVOMAP_PROXY_TRACE_FILE",
    "EVOLVER_ENV_FILE",
    "A2A_HUB_URL",
]


@pytest.fixture
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def test_derives_paths_from_home_and_overrides_stale(tmp_path: Path, _isolate_env: None) -> None:
    root = str(tmp_path / "v1-proxy-cli-home")
    env = {
        "EVOLVER_HOME": "/stale/home",
        "EVOLVER_PROXY_STORE": "/stale/store",
        "EVOLVER_PROXY_SETTINGS_FILE": "/stale/settings.json",
        "EVOMAP_PROXY_TRACE_FILE": "/stale/traces.jsonl",
    }
    prepare_proxy_cli_environment(["run", "--home", root], env)
    resolved = str(Path(root).resolve())
    assert env["EVOLVER_HOME"] == resolved
    assert env["EVOMAP_HOME"] == resolved
    assert env["EVOLVER_SETTINGS_DIR"] == resolved
    assert env["EVOLVER_PROXY_STORE"] == str(Path(resolved) / "mailbox")
    assert env["EVOLVER_PROXY_SETTINGS_FILE"] == str(Path(resolved) / "settings.json")
    assert env["EVOMAP_PROXY_TRACE_FILE"] == str(
        Path(resolved) / "proxy" / "traces" / "proxy-traces.jsonl"
    )


def test_fine_grained_paths_after_home_regardless_of_order(
    tmp_path: Path, _isolate_env: None
) -> None:
    root = str(tmp_path / "v1-proxy-cli-home-specific")
    store = str(tmp_path / "v1-proxy-store")
    settings_file = str(tmp_path / "v1-proxy-settings.json")
    env: dict[str, str] = {}
    prepare_proxy_cli_environment(
        ["--store", store, "--settings", settings_file, f"--home={root}"],
        env,
    )
    assert env["EVOLVER_HOME"] == str(Path(root).resolve())
    assert env["EVOLVER_PROXY_STORE"] == str(Path(store).resolve())
    assert env["EVOLVER_PROXY_SETTINGS_FILE"] == str(Path(settings_file).resolve())


def test_loads_env_file_then_reapplies_cli_path_priority(
    tmp_path: Path, _isolate_env: None
) -> None:
    env_file = tmp_path / "proxy.env"
    root = tmp_path / "home"
    env_file.write_text(
        "A2A_HUB_URL=https://selected.example\nEVOLVER_PROXY_STORE=/from/env/store\n",
        encoding="utf-8",
    )
    env: dict[str, str] = {}
    prepared = prepare_proxy_cli_environment(
        ["--env-file", str(env_file), "--home", str(root)], env
    )
    assert prepared["env_file"]["loaded"] is True
    assert env["A2A_HUB_URL"] == "https://selected.example"
    assert env["EVOLVER_ENV_FILE"] == str(env_file.resolve())
    assert env["EVOLVER_PROXY_STORE"] == str(Path(root).resolve() / "mailbox")


def test_loads_environment_selected_evolver_env_file(tmp_path: Path, _isolate_env: None) -> None:
    env_file = tmp_path / "proxy.env"
    env_file.write_text("A2A_HUB_URL=https://env-selected.example\n", encoding="utf-8")
    env: dict[str, str] = {"EVOLVER_ENV_FILE": str(env_file)}
    prepared = prepare_proxy_cli_environment([], env)
    assert prepared["env_file"]["loaded"] is True
    assert env["A2A_HUB_URL"] == "https://env-selected.example"


def test_rejects_missing_path_values() -> None:
    with pytest.raises(ValueError, match="--home requires a path"):
        parse_proxy_cli_path_options(["--home"])
    with pytest.raises(ValueError, match="--store requires a path"):
        parse_proxy_cli_path_options(["--store", "--loop"])


def test_expand_home_path_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/fake-home")
    env = {"HOME": "/tmp/fake-home"}
    expanded = expand_home_path("~", env)
    assert expanded.replace("\\", "/").endswith("fake-home")
    expanded2 = expand_home_path("~/mailbox", env)
    assert expanded2.replace("\\", "/").endswith("fake-home/mailbox")


def test_equals_form_and_resolve(tmp_path: Path) -> None:
    dest = tmp_path / "home-dest"
    opts = parse_proxy_cli_path_options([f"--home={dest}"])
    assert opts["home"] == str(dest.resolve())


def test_proxy_help_lists_path_flags() -> None:
    from evolver.cli import _build_parser

    parser = _build_parser()
    help_text = ""
    for action in parser._subparsers._group_actions:  # type: ignore[attr-defined]
        for name, sub in getattr(action, "choices", {}).items():
            if name == "proxy":
                help_text = sub.format_help()
                break
    assert "--home" in help_text
    assert "--store" in help_text
    assert "--settings" in help_text
    assert "--env-file" in help_text
