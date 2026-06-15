"""IDE hook installer for evolver.

Runtime hook adapters (via ``hook_adapter``): cursor, claude-code, codex, kiro, opencode.
Static config writers: VS Code settings, generic markdown fallback.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evolver.adapters.hook_adapter import load_adapter

STATIC_PLATFORMS: frozenset[str] = frozenset({"vscode", "generic"})
ADAPTER_PLATFORMS: frozenset[str] = frozenset(
    {"cursor", "claude-code", "codex", "kiro", "opencode"}
)
SUPPORTED_PLATFORMS: Sequence[str] = (
    "cursor",
    "claude-code",
    "vscode",
    "generic",
    "codex",
    "kiro",
    "opencode",
)

_VSCODE_SETTINGS = {
    "python.analysis.typeCheckingMode": "strict",
    "python.testing.pytestEnabled": True,
    "python.testing.autoTestDiscoverOnSaveEnabled": True,
    "editor.formatOnSave": True,
    "editor.rulers": [88, 120],
    "files.exclude": {
        "**/__pycache__": True,
        "**/.pytest_cache": True,
        "**/.mypy_cache": True,
    },
}

_GENERIC_HOOK = """# Evolver IDE Hook

This project uses `@evomap/evolver` for self-evolution.

## Integration Checklist
- [ ] Install evolver: `pip install evolver` or `uv add --dev evolver`
- [ ] Run initial cycle: `evolver run`
- [ ] Review `evolver review` before committing AI-generated changes
- [ ] Keep `tests/` green — evolver respects test results as fitness signals

## Recommended IDE Configurations

### Cursor / Claude Code / Codex / Kiro / opencode
Install runtime lifecycle hooks (session start, signal detect, session end):
`evolver setup-hooks --platform=cursor|claude-code|codex|kiro|opencode`
Verify opencode plugin: `evolver setup-hooks --platform=opencode --verify`
Remove hooks: `evolver setup-hooks --platform=cursor --uninstall`

### VS Code
Update `.vscode/settings.json` with strict Python settings from:
`evolver setup-hooks --platform=vscode`

## Useful Aliases
```bash
alias evrun='uv run evolver run'
alias evloop='uv run evolver --loop'
alias evsol='uv run evolver solidify'
alias evrev='uv run evolver review'
alias evtest='uv run pytest tests/ -v'
```
"""


def _detect_platform(project_dir: Path) -> str | None:
    """Auto-detect IDE by config dirs present in the project (not ``$HOME``)."""
    for platform_id, dirname in (
        ("cursor", ".cursor"),
        ("claude-code", ".claude"),
        ("codex", ".codex"),
        ("kiro", ".kiro"),
        ("opencode", ".opencode"),
        ("vscode", ".vscode"),
    ):
        if (project_dir / dirname).exists():
            return platform_id
    return None


def _run_adapter_platform(
    platform: str,
    project_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    uninstall: bool = False,
    verify: bool = False,
) -> dict[str, Any]:
    adapter = load_adapter(platform)
    if adapter is None:
        return {"ok": False, "error": f"No adapter for '{platform}'", "messages": []}

    # ``install_hooks`` always targets ``--project-dir`` (no ``$HOME`` fallback).
    config_root = project_dir
    evolver_root = Path(__file__).resolve().parents[2]

    if dry_run:
        action = "uninstall" if uninstall else "verify" if verify else "install"
        return {
            "ok": True,
            "platform": platform,
            "messages": [f"WOULD {action} {platform} hooks at {config_root}"],
        }

    if verify:
        if not hasattr(adapter, "verify"):
            return {
                "ok": False,
                "error": f"Platform '{platform}' does not support --verify",
                "messages": [],
            }
        result = adapter.verify(config_root=config_root)
        if hasattr(adapter, "print_verify_report"):
            adapter.print_verify_report(result)
        messages = [
            f"{'OK' if check.get('ok') else 'FAIL'} {check.get('id')}: {check.get('detail')}"
            for check in result.get("checks", [])
        ]
        if note := result.get("note"):
            messages.append(str(note))
        return {
            "ok": bool(result.get("ok")),
            "platform": platform,
            "messages": messages,
            **({} if result.get("ok") else {"error": "verification_failed"}),
        }

    if uninstall:
        result = adapter.uninstall(config_root=config_root, evolver_root=evolver_root)
    else:
        result = adapter.install(config_root=config_root, evolver_root=evolver_root, force=force)

    return {
        "ok": bool(result.get("ok", True)),
        "platform": platform,
        "messages": result.get("messages", []),
        "skipped": result.get("skipped"),
    }


def _write_vscode_hook(project_dir: Path, force: bool, dry_run: bool) -> list[str]:
    vscode_dir = project_dir / ".vscode"
    target = vscode_dir / "settings.json"
    msgs: list[str] = []
    existing: dict[str, Any] = {}
    if target.exists():
        if not force:
            msgs.append(f"SKIP vscode hook (exists): {target}")
            return msgs
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    merged = {**existing, **_VSCODE_SETTINGS}
    if dry_run:
        msgs.append(f"WOULD write vscode hook: {target}")
        return msgs
    vscode_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, indent=4) + "\n", encoding="utf-8")
    msgs.append(f"OK vscode hook: {target}")
    return msgs


def _write_generic_hook(project_dir: Path, force: bool, dry_run: bool) -> list[str]:
    target = project_dir / "EVOLVER_HOOK.md"
    msgs: list[str] = []
    if target.exists() and not force:
        msgs.append(f"SKIP generic hook (exists): {target}")
        return msgs
    if dry_run:
        msgs.append(f"WOULD write generic hook: {target}")
        return msgs
    target.write_text(_GENERIC_HOOK, encoding="utf-8")
    msgs.append(f"OK generic hook: {target}")
    return msgs


def install_hooks(
    *,
    platform: str = "auto",
    project_dir: str | Path = ".",
    force: bool = False,
    dry_run: bool = False,
    uninstall: bool = False,
    verify: bool = False,
) -> dict[str, Any]:
    """Install IDE hooks for the given platform.

    Returns a result dict with ``ok``, ``messages``, and ``platform`` keys.
    """
    pdir = Path(project_dir).resolve()
    if not pdir.is_dir():
        return {"ok": False, "error": f"Not a directory: {pdir}", "messages": []}

    if uninstall and verify:
        return {
            "ok": False,
            "error": "Cannot use --uninstall and --verify together",
            "messages": [],
        }

    chosen = platform
    if chosen == "auto":
        detected = _detect_platform(pdir)
        chosen = detected if detected else "generic"

    if chosen not in SUPPORTED_PLATFORMS:
        return {
            "ok": False,
            "error": (
                f"Unsupported platform '{chosen}'. Choose from: "
                f"{', '.join(SUPPORTED_PLATFORMS)} or auto."
            ),
            "messages": [],
        }

    if chosen in ADAPTER_PLATFORMS:
        return _run_adapter_platform(
            chosen,
            pdir,
            force=force,
            dry_run=dry_run,
            uninstall=uninstall,
            verify=verify,
        )

    if uninstall or verify:
        return {
            "ok": False,
            "error": (
                f"--uninstall/--verify only supported for: {', '.join(sorted(ADAPTER_PLATFORMS))}"
            ),
            "messages": [],
        }

    msgs: list[str] = []
    if chosen == "vscode":
        msgs.extend(_write_vscode_hook(pdir, force, dry_run))
    elif chosen == "generic":
        msgs.extend(_write_generic_hook(pdir, force, dry_run))

    return {"ok": True, "platform": chosen, "messages": msgs}
