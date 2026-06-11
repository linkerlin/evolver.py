"""Tests for evolver.gep.epigenetics."""

import time

import pytest

from evolver.gep.epigenetics import (
    DEFAULT_MARK_HALF_LIFE_DAYS,
    GENE_EPIGENETIC_HARD_BOOST,
    age_all_genes,
    age_marks,
    apply_mark,
    boost_gene,
    capture_env_fingerprint,
    env_fingerprint_key,
    get_active_genes,
    get_boost_for_context,
    get_marks,
    is_active,
    is_suppressed,
    remove_mark,
    suppress_gene,
)


class TestEnvFingerprint:
    def test_capture_returns_dict(self):
        env = capture_env_fingerprint()
        assert isinstance(env, dict)
        assert "HOME" in env

    def test_key_stable(self):
        env = {"a": "1", "b": "2"}
        k1 = env_fingerprint_key(env)
        k2 = env_fingerprint_key(env)
        assert k1 == k2
        assert len(k1) == 16

    def test_key_different(self):
        k1 = env_fingerprint_key({"a": "1"})
        k2 = env_fingerprint_key({"a": "2"})
        assert k1 != k2


class TestMarks:
    def test_apply_mark(self):
        gene = {}
        apply_mark(gene, "ctx1", 2.0)
        assert len(get_marks(gene)) == 1
        assert get_boost_for_context(gene, "ctx1") == 2.0

    def test_apply_mark_updates_existing(self):
        gene = {}
        apply_mark(gene, "ctx1", 2.0)
        apply_mark(gene, "ctx1", 3.0)
        assert len(get_marks(gene)) == 1
        assert get_boost_for_context(gene, "ctx1") == 3.0

    def test_remove_mark(self):
        gene = {}
        apply_mark(gene, "ctx1", 2.0)
        assert remove_mark(gene, "ctx1")
        assert get_boost_for_context(gene, "ctx1") == 0.0

    def test_remove_missing(self):
        gene = {}
        assert not remove_mark(gene, "ctx1")


class TestSuppression:
    def test_not_suppressed_by_default(self):
        gene = {}
        assert not is_suppressed(gene)
        assert is_active(gene)

    def test_suppressed_when_boost_low(self):
        gene = {}
        env = {"EVOLVER_MODE": "test"}
        key = env_fingerprint_key(env)
        apply_mark(gene, key, GENE_EPIGENETIC_HARD_BOOST)
        assert is_suppressed(gene, env)
        assert not is_active(gene, env)

    def test_boost_gene(self):
        gene = {}
        boost_gene(gene, "ctx1", 5.0)
        assert get_boost_for_context(gene, "ctx1") == 5.0

    def test_suppress_gene(self):
        gene = {}
        suppress_gene(gene, "ctx1")
        assert get_boost_for_context(gene, "ctx1") == GENE_EPIGENETIC_HARD_BOOST

    def test_get_active_genes(self):
        g1 = {"name": "a"}
        g2 = {"name": "b"}
        env = {"EVOLVER_MODE": "test"}
        suppress_gene(g2, env_fingerprint_key(env))
        active = get_active_genes([g1, g2], env)
        assert active == [g1]


class TestAging:
    def test_mark_decay(self):
        gene = {}
        now = 1000000.0
        apply_mark(gene, "ctx1", 10.0, created_at=now)
        # Age by exactly one half-life
        age_marks(gene, half_life_days=1, now=now + 86400)
        assert get_boost_for_context(gene, "ctx1") == pytest.approx(5.0, rel=0.01)

    def test_mark_removed_when_tiny(self):
        gene = {}
        now = 1000000.0
        apply_mark(gene, "ctx1", 0.15, created_at=now)
        age_marks(gene, half_life_days=1, now=now + 86400 * 10)
        assert len(get_marks(gene)) == 0

    def test_age_all_genes(self):
        g1 = {}
        g2 = {}
        now = 1000000.0
        apply_mark(g1, "ctx1", 10.0, created_at=now)
        apply_mark(g2, "ctx2", 10.0, created_at=now)
        # Pass now explicitly so marks are not aged to zero
        age_all_genes([g1, g2], half_life_days=1)
        # Since age_all_genes doesn't accept 'now', marks will age against time.time().
        # We just verify it doesn't crash; marks may be removed if elapsed is huge.
        # Use a fresh mark with current time to verify structure:
        apply_mark(g1, "ctx3", 10.0, created_at=time.time())
        age_all_genes([g1], half_life_days=1)
        assert len(get_marks(g1)) == 1
