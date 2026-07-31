"""Parser-syntax guard for entry-point scripts shipped to users (#542).

Port of ``evolver/test/adaptersSyntax.test.js``.
"""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO / "src" / "evolver" / "adapters" / "scripts"
_CLI = _REPO / "src" / "evolver" / "cli.py"
_MAIN = _REPO / "src" / "evolver" / "__main__.py"
_ADAPTERS_DIR = _REPO / "src" / "evolver" / "adapters"


def _py_check(path: Path) -> tuple[bool, str]:
    try:
        py_compile.compile(str(path), doraise=True)
        return True, ""
    except py_compile.PyCompileError as exc:
        return False, str(exc)
    except SyntaxError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def test_every_adapter_script_parses() -> None:
    targets = sorted(_SCRIPTS_DIR.glob("*.py"))
    assert targets, "expected at least one adapter runtime script"
    failures: list[str] = []
    for path in targets:
        ok, err = _py_check(path)
        if not ok:
            rel = path.relative_to(_REPO).as_posix()
            failures.append(f"  {rel}: {err.strip()}")
    assert not failures, (
        f"py_compile failed for {len(failures)} adapter script(s):\n" + "\n".join(failures)
    )


def test_adapter_modules_parse() -> None:
    targets = sorted(p for p in _ADAPTERS_DIR.glob("*.py") if p.name != "__init__.py")
    assert targets, "expected adapter modules"
    failures: list[str] = []
    for path in targets:
        ok, err = _py_check(path)
        if not ok:
            failures.append(f"  {path.name}: {err.strip()}")
    assert not failures, (
        f"py_compile failed for {len(failures)} adapter module(s):\n" + "\n".join(failures)
    )


def test_cli_entry_parses() -> None:
    ok, err = _py_check(_CLI)
    assert ok, f"py_compile failed for cli.py:\n{err}"
    ok2, err2 = _py_check(_MAIN)
    assert ok2, f"py_compile failed for __main__.py:\n{err2}"


def test_scripts_compile_exec() -> None:
    for path in sorted(_SCRIPTS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec", dont_inherit=True)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="project requires 3.12+")
def test_python_version_gate() -> None:
    assert sys.version_info >= (3, 12)
