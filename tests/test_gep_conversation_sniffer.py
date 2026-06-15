"""Tests for evolver.gep.conversation_sniffer.

Equivalent to test/conversationSniffer.test.js — covers scanCorpus,
convertToSignals, and trySniff mode/cooldown behaviour.
"""

from __future__ import annotations

import pytest

from evolver.gep import conversation_sniffer as cs

# ---------------------------------------------------------------------------
# scan_corpus
# ---------------------------------------------------------------------------


class TestScanCorpus:
    def test_surfaces_capability_with_success(self) -> None:
        r = cs.scan_corpus("Ran lark-cli docs +create; document published successfully.")
        assert len(r) == 1
        assert r[0]["capability"] == "publish-feishu-doc"

    def test_no_surface_on_failure(self) -> None:
        r = cs.scan_corpus("Tried lark-cli docs +create but it errored and failed to publish.")
        caps = [c["capability"] for c in r]
        assert "publish-feishu-doc" not in caps or len(r) == 0

    def test_no_surface_plain_success(self) -> None:
        r = cs.scan_corpus("The build passed and all tests are working.")
        assert r == []

    def test_chinese_success_markers(self) -> None:
        r = cs.scan_corpus("lark-cli docs +create published the doc successfully")
        assert len(r) == 1
        assert r[0]["capability"] == "publish-feishu-doc"

    def test_dedups_multiple_hits(self) -> None:
        r = cs.scan_corpus(
            "lark-cli published OK. Later lark-cli docs +create published again successfully."
        )
        caps = [c["capability"] for c in r]
        assert caps.count("publish-feishu-doc") == 1

    def test_empty_corpus(self) -> None:
        assert cs.scan_corpus("") == []
        assert cs.scan_corpus(None) == []

    def test_distant_success_no_pairing(self) -> None:
        filler = " " * 400
        corpus = (
            "All unit tests passed successfully."
            + filler
            + "Then I tried lark-cli docs +create but it errored out and nothing was produced."
        )
        assert cs.scan_corpus(corpus) == []

    def test_later_successful_use(self) -> None:
        filler = " " * 400
        corpus = (
            "Attempted lark-cli docs +create (no result here)."
            + filler
            + "Re-ran lark-cli docs +create and it published successfully."
        )
        r = cs.scan_corpus(corpus)
        assert len(r) == 1
        assert r[0]["capability"] == "publish-feishu-doc"

    def test_negated_success_not_counted(self) -> None:
        assert cs.scan_corpus("lark-cli docs +create ran but the doc was not verified") == []

    def test_array_segments_independent(self) -> None:
        seg_a = "ran the suite, all tests passed successfully"
        seg_b = "then lark-cli docs +create errored and produced nothing"
        assert cs.scan_corpus([seg_a, seg_b]) == []

    def test_array_in_segment_success(self) -> None:
        r = cs.scan_corpus(["idle chatter", "lark-cli docs +create published successfully"])
        assert len(r) == 1
        assert r[0]["capability"] == "publish-feishu-doc"


# ---------------------------------------------------------------------------
# convert_to_signals
# ---------------------------------------------------------------------------


class TestConvertToSignals:
    def test_prepends_umbrella_and_per_cap(self) -> None:
        sigs = cs.convert_to_signals(
            [{"capability": "publish-feishu-doc"}, {"capability": "api-call"}]
        )
        assert sigs[0] == "conv_capability_candidate"
        assert "conv_capability:publish-feishu-doc" in sigs
        assert "conv_capability:api-call" in sigs

    def test_empty_for_no_candidates(self) -> None:
        assert cs.convert_to_signals([]) == []


# ---------------------------------------------------------------------------
# try_sniff modes
# ---------------------------------------------------------------------------


class TestTrySniffModes:
    def test_off_mode_no_signals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_CONV_SNIFF_ENABLED", "off")
        r = cs.try_sniff("lark-cli published successfully", {"seen": {}, "last_sniff_ts": 0})
        assert r["mode"] == "off"
        assert r["signals"] == []

    def test_shadow_mode_surfaces_but_no_signals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_CONV_SNIFF_ENABLED", "shadow")
        r = cs.try_sniff(
            "lark-cli docs +create published the doc successfully",
            {"seen": {}, "last_sniff_ts": 0},
        )
        assert r["mode"] == "shadow"
        assert len(r["candidates"]) >= 1
        assert r["signals"] == []

    def test_enforce_mode_injects_signals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_CONV_SNIFF_ENABLED", "enforce")
        r = cs.try_sniff(
            "lark-cli docs +create published the doc successfully",
            {"seen": {}, "last_sniff_ts": 0},
        )
        assert r["mode"] == "enforce"
        assert "conv_capability_candidate" in r["signals"]
        assert "conv_capability:publish-feishu-doc" in r["signals"]

    def test_cooldown_gates_second_sniff(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EVOLVER_CONV_SNIFF_ENABLED", "enforce")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
        # Force the state path into isolation.
        import evolver.gep.conversation_sniffer as cs_mod  # noqa: PLC0415

        monkeypatch.setattr(cs_mod, "_state_path", lambda: tmp_path / "state.json")
        state = {"seen": {}, "last_sniff_ts": 0}
        first = cs.try_sniff("lark-cli published successfully", state)
        assert len(first["signals"]) > 0
        # State now has a fresh last_sniff_ts; re-read and try again immediately.
        st2 = cs.read_state()
        second = cs.try_sniff("lark-cli published successfully again", st2)
        assert second["signals"] == []

    def test_empty_sniff_no_cooldown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EVOLVER_CONV_SNIFF_ENABLED", "enforce")
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
        import evolver.gep.conversation_sniffer as cs_mod  # noqa: PLC0415

        monkeypatch.setattr(cs_mod, "_state_path", lambda: tmp_path / "state.json")
        state = {"seen": {}, "last_sniff_ts": 0}
        # first sniff finds nothing (no capability/success) -> must not set cooldown
        empty = cs.try_sniff("just some idle chatter, nothing actionable here", state)
        assert empty["signals"] == []
        after_empty = cs.read_state()
        assert not after_empty.get("last_sniff_ts"), "empty sniff must NOT persist cooldown"
        # a subsequent sniff with real evidence should still fire (not gated)
        real = cs.try_sniff("lark-cli published successfully", cs.read_state())
        assert len(real["signals"]) > 0
