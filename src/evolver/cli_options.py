"""Proxy CLI path options — home/store/settings/env-file parsing.

Behavioral port of ``evolver/cli-options.js`` (v1.93.0).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

PROXY_PATH_FLAGS: dict[str, str] = {
    "--home": "home",
    "--store": "store",
    "--settings": "settings",
    "--env-file": "env_file",
}


def expand_home_path(value: Any, env: Mapping[str, str] | None = None) -> str:
    """Expand leading ``~`` using HOME/USERPROFILE (or the provided env map)."""
    environ: Mapping[str, str] = env if env is not None else os.environ
    text = str(value)
    if text == "~":
        return str(environ.get("HOME") or environ.get("USERPROFILE") or Path.home())
    if text.startswith("~/") or text.startswith("~\\"):
        home = str(environ.get("HOME") or environ.get("USERPROFILE") or Path.home())
        return str(Path(home) / text[2:])
    return text


def parse_proxy_cli_path_options(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Parse ``--home/--store/--settings/--env-file`` (``=`` form supported)."""
    options: dict[str, str] = {}
    index = 0
    while index < len(argv):
        arg = str(argv[index])
        equals_index = arg.find("=")
        flag = arg[:equals_index] if equals_index >= 0 else arg
        key = PROXY_PATH_FLAGS.get(flag)
        if key is None:
            index += 1
            continue

        if equals_index >= 0:
            value: str | None = arg[equals_index + 1 :]
        else:
            index += 1
            value = str(argv[index]) if index < len(argv) else None

        if (
            not value
            or not str(value).strip()
            or (equals_index < 0 and str(value).startswith("-"))
        ):
            raise ValueError(f"{flag} requires a path")

        options[key] = str(Path(expand_home_path(str(value).strip(), env)).resolve())
        index += 1
    return options


def apply_proxy_cli_path_options(
    options: Mapping[str, str],
    env: MutableMapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Write path options into ``env`` (defaults to ``os.environ``).

    Fine-grained ``store`` / ``settings`` always win over paths derived from
    ``--home``, regardless of argument order (apply home first, then overrides).
    """
    target: MutableMapping[str, str] = env if env is not None else os.environ

    if options.get("env_file"):
        target["EVOLVER_ENV_FILE"] = options["env_file"]

    home = options.get("home")
    if home:
        target["EVOMAP_DIR"] = home
        target["EVOLVER_HOME"] = home
        target["EVOMAP_HOME"] = home
        target["EVOLVER_SETTINGS_DIR"] = home
        target["EVOLVER_PROXY_STORE"] = str(Path(home) / "mailbox")
        target["EVOLVER_PROXY_SETTINGS_FILE"] = str(Path(home) / "settings.json")
        target["EVOMAP_PROXY_TRACE_FILE"] = str(
            Path(home) / "proxy" / "traces" / "proxy-traces.jsonl"
        )

    if options.get("store"):
        target["EVOLVER_PROXY_STORE"] = options["store"]
    if options.get("settings"):
        target["EVOLVER_PROXY_SETTINGS_FILE"] = options["settings"]
    return options


def _load_dotenv_into(path: str, env: MutableMapping[str, str]) -> dict[str, Any]:
    """Load KEY=VALUE pairs from *path* into *env* (no override of existing keys)."""
    resolved = str(Path(path).resolve())
    if env is os.environ:
        try:
            from dotenv import load_dotenv  # noqa: PLC0415
        except ImportError:
            return {"loaded": False, "error": "python-dotenv not installed"}
        result = load_dotenv(dotenv_path=resolved, override=False)
        if result is False and not Path(resolved).is_file():
            return {"loaded": False, "error": FileNotFoundError(resolved)}
        loaded = bool(result) or Path(resolved).is_file()
        return {"loaded": loaded, "error": None}

    try:
        text = Path(resolved).read_text(encoding="utf-8")
    except OSError as exc:
        return {"loaded": False, "error": exc}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key or key in env:
            continue
        env[key] = value
    return {"loaded": True, "error": None}


def prepare_proxy_cli_environment(
    argv: Sequence[str],
    env: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """Parse path flags, load env-file, then re-apply CLI path priority."""
    target: MutableMapping[str, str] = env if env is not None else os.environ
    options = parse_proxy_cli_path_options(argv, target)

    env_file_info: dict[str, Any] = {"loaded": False, "error": None}
    selected = options.get("env_file") or target.get("EVOLVER_ENV_FILE")
    if selected:
        resolved = str(Path(expand_home_path(str(selected).strip(), target)).resolve())
        target["EVOLVER_ENV_FILE"] = resolved
        env_file_info = _load_dotenv_into(resolved, target)

    apply_proxy_cli_path_options(options, target)
    return {"options": options, "env_file": env_file_info}
