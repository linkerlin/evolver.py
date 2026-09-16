"""Anchor probe: T0 population parity (DEBUG #25/#26).

Discovery must apply the cascade's ``-m "not slow"`` filter: slow tests in
the frozen set blew per-chunk timeouts (phantom failures) and ran unisolated
e2e state-writers against the live repo from inside the gate.
Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _isolate(ws: Path) -> None:
    (ws / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (ws / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "OPENCLAW_WORKSPACE": str(ws),
            "EVOLVER_REPO_ROOT": str(ws),
            "EVOLVER_NO_PARENT_GIT": "1",
            "MEMORY_DIR": str(ws / "memory"),
            "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
            "GEP_ASSETS_DIR": str(ws / ".evolver" / "gep"),
            "EVOLVER_HOME": str(ws / ".evomap"),
            "EVOLVER_SETTINGS_DIR": str(ws / ".evolver_settings"),
            "EVOLVER_LOGS_DIR": str(ws / "logs"),
        }
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        _isolate(ws)
        tests = ws / "tests"
        tests.mkdir()
        (ws / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\nmarkers = ["slow: anchor probe"]\n',
            encoding="utf-8",
        )
        (tests / "test_fast.py").write_text(
            "def test_quick():\n    assert True\n", encoding="utf-8"
        )
        (tests / "test_slowpoke.py").write_text(
            "import pytest\n\n@pytest.mark.slow\ndef test_drag():\n    assert True\n",
            encoding="utf-8",
        )
        from evolver.gep.acceptance.t0_frozen import discover_test_ids

        ids = discover_test_ids(ws)
        if any("test_drag" in i for i in ids):
            print(f"FAIL: slow-marked test leaked into frozen set: {ids}")
            return 1
        if not any("test_quick" in i for i in ids):
            print(f"FAIL: fast test missing from discovery: {ids}")
            return 1
        print("PASS: T0 discovery population matches the cascade filter")
        return 0


if __name__ == "__main__":
    sys.exit(main())
