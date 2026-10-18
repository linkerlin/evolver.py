"""Line numbers and temp paths collapse into one evidence-pack row."""

from __future__ import annotations

from evolver.gep.evidence_pack import (
    build_evidence_pack,
    collapse_quantized_attempts,
    render_evidence_pack,
)
from evolver.gep.sanitize import quantize_diagnostic_signature


def test_quantize_collapses_noise() -> None:
    left = quantize_diagnostic_signature(
        "KeyError at src/a.py:12: addr 0x7f8a9c pytest-of-user1 /tmp/pytest-of-user1/t"
    )
    right = quantize_diagnostic_signature(
        "KeyError at src/a.py:99: addr 0x111111 pytest-of-user2 /tmp/pytest-of-user2/t"
    )
    assert left == right
    assert ":L*:" in left
    assert "0xADDR" in left
    assert "pytest-of-TMP" in left


def test_same_signature_renders_once_with_count() -> None:
    def event(i: int, line: int) -> dict[str, object]:
        return {
            "id": f"evt_{i}",
            "gene_id": "gene_f",
            "outcome": {"status": "failed", "error": f"KeyError src/a.py:{line}:"},
            "mutation": {"category": "repair"},
            "signals": ["log_error"],
            "novelty_added": "+same edit\n",
        }

    pack = build_evidence_pack([event(1, 12), event(2, 40)], ["log_error"])
    assert len(pack["attempts"]) == 2
    collapsed = collapse_quantized_attempts(pack["attempts"])
    assert len(collapsed) == 1
    assert collapsed[0]["count"] == 2
    rendered = render_evidence_pack(pack)
    assert "count=2" in rendered
    assert rendered.count("evt_") == 1
