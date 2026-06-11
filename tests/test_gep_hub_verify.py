"""Tests for evolver.gep.hub_verify."""

from __future__ import annotations

import hashlib

from evolver.gep.hub_verify import (
    verify_patch_integrity,
    verify_service_schema,
    verify_skill_bundle,
)


class TestVerifyServiceSchema:
    def test_valid(self):
        data = {
            "service_id": "s1",
            "title": "T",
            "description": "D",
            "capabilities": ["c"],
            "price_per_task": 1.0,
            "execution_mode": "sync",
        }
        r = verify_service_schema(data)
        assert r.valid
        assert len(r.errors) == 0

    def test_missing_field(self):
        r = verify_service_schema({})
        assert not r.valid
        assert len(r.errors) == 6

    def test_bad_price(self):
        r = verify_service_schema(
            {
                "service_id": "s1",
                "title": "T",
                "description": "D",
                "capabilities": ["c"],
                "price_per_task": -1,
                "execution_mode": "sync",
            }
        )
        assert any("price_per_task must be" in e.message for e in r.errors)

    def test_bad_mode(self):
        r = verify_service_schema(
            {
                "service_id": "s1",
                "title": "T",
                "description": "D",
                "capabilities": ["c"],
                "price_per_task": 0,
                "execution_mode": "magic",
            }
        )
        assert any("Invalid execution_mode" in e.message for e in r.errors)


class TestVerifySkillBundle:
    def test_valid(self):
        content = b"hello"
        manifest = {
            "files": [
                {"path": "a.py", "sha256": hashlib.sha256(content).hexdigest()},
            ]
        }
        files = {"a.py": content}
        r = verify_skill_bundle(manifest, files)
        assert r.valid

    def test_missing_file(self):
        manifest = {"files": [{"path": "a.py", "sha256": "x" * 64}]}
        r = verify_skill_bundle(manifest, {})
        assert not r.valid
        assert any("Missing file" in e.message for e in r.errors)

    def test_hash_mismatch(self):
        content = b"hello"
        manifest = {"files": [{"path": "a.py", "sha256": "0" * 64}]}
        files = {"a.py": content}
        r = verify_skill_bundle(manifest, files)
        assert not r.valid
        assert any("Hash mismatch" in e.message for e in r.errors)

    def test_manifest_no_files(self):
        r = verify_skill_bundle({}, {})
        assert r.valid  # no errors, just warning
        assert any("no 'files' list" in w.message for w in r.warnings)


class TestVerifyPatchIntegrity:
    def test_valid(self):
        diff = "diff --git a/foo.py b/foo.py\n+line\n"
        r = verify_patch_integrity(diff, ["foo.py"])
        assert r.valid

    def test_untracked_file(self):
        diff = "diff --git a/foo.py b/foo.py\n+line\n"
        r = verify_patch_integrity(diff, ["bar.py"])
        assert not r.valid
        assert any("untracked file" in e.message for e in r.errors)

    def test_multiple_files(self):
        diff = "diff --git a/a.py b/a.py\n+1\ndiff --git a/b.py b/b.py\n+2\n"
        r = verify_patch_integrity(diff, ["a.py", "b.py"])
        assert r.valid

    def test_empty_diff(self):
        r = verify_patch_integrity("", ["foo.py"])
        assert r.valid  # no referenced files, no errors
