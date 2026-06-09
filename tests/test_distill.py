"""Tests for evolver.gep.distill."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import distill


def test_distill_text_fenced_block() -> None:
    text = '''
Some prose before.

```json
{
  "type": "Gene",
  "id": "g_distilled",
  "category": "repair",
  "signals_match": ["error"],
  "strategy": ["fix it"],
  "validation": ["pytest"]
}
```

Some prose after.
'''
    result = distill.distill_text(text)
    assert result["ok"] is True
    assert len(result["genes"]) == 1
    assert result["genes"][0]["id"] == "g_distilled"


def test_distill_text_bare_json() -> None:
    text = 'Here is a gene: {"type": "Gene", "id": "g2", "category": "optimize", "signals_match": ["perf"], "strategy": ["opt"], "validation": ["test"]}'
    result = distill.distill_text(text)
    assert result["ok"] is True
    assert any(g["id"] == "g2" for g in result["genes"])


def test_distill_text_no_asset() -> None:
    result = distill.distill_text("just plain text with no JSON")
    assert result["ok"] is True
    assert result["genes"] == []
    assert result["capsules"] == []


def test_distill_file(tmp_path: Path) -> None:
    path = tmp_path / "response.txt"
    path.write_text('```json\n{"type": "Capsule", "id": "c1", "trigger": ["error"], "gene": "g1"}\n```')
    result = distill.distill_file(path)
    assert result["ok"] is True
    assert len(result["capsules"]) == 1
    assert result["capsules"][0]["id"] == "c1"


def test_install_distilled_dry_run() -> None:
    result = {
        "genes": [{"type": "Gene", "id": "g1", "category": "repair"}],
        "capsules": [],
        "mutations": [],
    }
    install = distill.install_distilled(result, dry_run=True)
    assert install["ok"] is True
    assert install["installed"][0]["action"] == "would_install"


def test_install_distilled_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    result = {
        "genes": [{"type": "Gene", "id": "g_install", "category": "repair", "signals_match": ["error"], "strategy": ["fix"], "validation": ["test"]}],
        "capsules": [],
        "mutations": [],
    }
    install = distill.install_distilled(result, dry_run=False)
    assert install["ok"] is True
    assert any(i["id"] == "g_install" for i in install["installed"])
