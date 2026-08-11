"""Static guard: .env must load before env-sensitive internal imports (#460).

Port of ``evolver/test/dotenvLoadOrder.test.js``.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / "src" / "evolver" / "cli.py"
_MAIN = _REPO / "src" / "evolver" / "__main__.py"


def _cli_source() -> str:
    return _CLI.read_text(encoding="utf-8")


def _cli_lines() -> list[str]:
    return _cli_source().splitlines()


def _first_match(lines: list[str], pattern: str) -> int:
    regex = re.compile(pattern)
    for i, line in enumerate(lines):
        if regex.search(line):
            return i
    return -1


def test_cli_defines_load_dotenv_helper() -> None:
    src = _cli_source()
    assert "def _load_dotenv" in src
    assert "dotenv" in src
    assert "load_dotenv" in src


def test_main_calls_load_dotenv_first() -> None:
    lines = _cli_lines()
    main_idx = _first_match(lines, r"^def main\(")
    assert main_idx >= 0, "expected def main() in cli.py"

    first_stmt = None
    for i in range(main_idx + 1, min(main_idx + 20, len(lines))):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(('"""', "'''")):
            continue
        first_stmt = stripped
        break

    assert first_stmt is not None, "main() appears empty"
    assert first_stmt.startswith("_load_dotenv("), (
        f"main() must call _load_dotenv() first (cf #460). First statement was: {first_stmt!r}"
    )


def test_cli_top_level_imports_are_stdlib_only() -> None:
    lines = _cli_lines()
    top_imports = [
        (i + 1, line.rstrip())
        for i, line in enumerate(lines)
        if line.startswith(("import ", "from "))
    ]
    forbidden = [
        (n, ln)
        for n, ln in top_imports
        if re.search(r"\bevolver\b", ln) and "evolver.cli" not in ln
    ]
    assert forbidden == [], (
        f"cli.py must not import evolver.* at module top-level. Offenders: {forbidden}"
    )


def test_load_dotenv_only_pulls_paths_from_evolver() -> None:
    src = _cli_source()
    m = re.search(r"def _load_dotenv\(\)[^:]*:(.*?)(?=\ndef |\Z)", src, re.S)
    assert m is not None
    body = m.group(1)
    imports = re.findall(r"from\s+(evolver[\w.]*)\s+import|import\s+(evolver[\w.]*)", body)
    names = [a or b for a, b in imports]
    for name in names:
        assert name in {"evolver.gep.paths", "dotenv"}, (
            f"_load_dotenv may only import evolver.gep.paths, got {name}"
        )


def test_main_module_delegates_to_cli() -> None:
    text = _MAIN.read_text(encoding="utf-8")
    assert "evolver.cli" in text
    assert "main()" in text
