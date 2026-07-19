"""Tests for evolver.ops.commentary."""

from __future__ import annotations

from evolver.ops.commentary import (
    _explorer_short,
    _critic_short,
    _pragmatist_short,
    _pragmatist_verbose,
    _explorer_verbose,
    _critic_verbose,
    generate_all_commentaries,
    generate_commentary,
    commentary_timeline,
)


def make_event(
    gene_id: str = "gene-r7",
    signals: list[str] | None = None,
    mutation: dict | None = None,
    blast_radius: dict | None = None,
    outcome: dict | None = None,
) -> dict:
    return {
        "id": "evt-1",
        "gene_id": gene_id,
        "timestamp": "2025-07-19T12:00:00Z",
        "signals": signals or ["log_error", "timeout"],
        "mutation": mutation or {"id": "m1", "category": "repair", "risk_level": "low"},
        "blast_radius": blast_radius or {"files": 2, "lines": 15},
        "outcome": outcome or {"status": "success", "score": 85},
    }


class TestPragmatist:
    def test_short_success(self):
        event = make_event()
        result = _pragmatist_short(event)
        assert "gene-r7" in result
        assert "repair" in result
        assert "success" in result
        assert len(result) < 140

    def test_short_failure(self):
        event = make_event(outcome={"status": "failed", "score": 20})
        result = _pragmatist_short(event)
        assert "failed" in result

    def test_verbose(self):
        event = make_event()
        result = _pragmatist_verbose(event)
        assert "Pragmatist" in result
        assert "gene-r7" in result
        assert "log_error" in result
        assert len(result.splitlines()) >= 3


class TestExplorer:
    def test_short_success(self):
        event = make_event()
        result = _explorer_short(event)
        assert "gene-r7" in result
        assert len(result) < 140

    def test_short_innovate(self):
        event = make_event(mutation={"id": "m1", "category": "innovate", "risk_level": "high"})
        result = _explorer_short(event)
        assert "创新" in result

    def test_verbose_repair(self):
        event = make_event()
        result = _explorer_verbose(event)
        assert "Explorer" in result
        assert "修复倾向" in result


class TestCritic:
    def test_short_success(self):
        event = make_event()
        result = _critic_short(event)
        assert "gene-r7" in result
        assert len(result) < 140

    def test_short_failure(self):
        event = make_event(outcome={"status": "failed", "score": 0})
        result = _critic_short(event)
        assert "失败" in result or "failed" in result.lower()

    def test_short_zero_files(self):
        event = make_event(blast_radius={"files": 0, "lines": 0})
        result = _critic_short(event)
        assert "空操作" in result or "零" in result

    def test_short_large_blast(self):
        event = make_event(blast_radius={"files": 20, "lines": 500})
        result = _critic_short(event)
        assert "爆炸" in result or "风险" in result

    def test_short_low_score(self):
        event = make_event(outcome={"status": "success", "score": 35})
        result = _critic_short(event)
        assert "得分" in result or "35" in result

    def test_verbose(self):
        event = make_event()
        result = _critic_verbose(event)
        assert "Critic" in result
        assert len(result.splitlines()) >= 3


class TestPublicApi:
    def test_generate_pragmatist(self):
        event = make_event()
        result = generate_commentary(event, persona="pragmatist")
        assert len(result) < 140

    def test_generate_explorer(self):
        event = make_event()
        result = generate_commentary(event, persona="explorer")
        assert len(result) < 140

    def test_generate_critic(self):
        event = make_event()
        result = generate_commentary(event, persona="critic")
        assert len(result) < 140

    def test_verbose_mode(self):
        event = make_event()
        result = generate_commentary(event, persona="pragmatist", verbose=True)
        assert len(result.splitlines()) >= 2

    def test_unknown_persona_fallback(self):
        event = make_event()
        result = generate_commentary(event, persona="nobody")
        assert len(result) < 140

    def test_generate_all(self):
        event = make_event()
        result = generate_all_commentaries(event)
        assert set(result.keys()) == {"pragmatist", "explorer", "critic"}
        for text in result.values():
            assert len(text) < 140

    def test_generate_all_verbose(self):
        event = make_event()
        result = generate_all_commentaries(event, verbose=True)
        for text in result.values():
            assert len(text.splitlines()) >= 2

    def test_timeline(self):
        events = []
        for i in range(3):
            e = make_event(gene_id=f"gene-{i}")
            e["id"] = f"evt-{i}"
            events.append(e)
        result = commentary_timeline(events, persona="explorer")
        assert len(result) == 3
        assert result[0]["persona"] == "explorer"
        assert "gene-0" in result[0]["gene_id"]
