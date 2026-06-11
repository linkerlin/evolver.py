"""Tests for evolver.gep.portable."""

from __future__ import annotations

import json
import tarfile

import pytest

from evolver.gep.portable import (
    ImportError,
    _file_hash,
    _read_jsonl,
    export_gepx,
    import_gepx,
)


class TestReadJsonl:
    def test_basic(self, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text('{"id":"1"}\n{"id":"2"}\n', encoding="utf-8")
        rows = _read_jsonl(p, 10)
        assert len(rows) == 2
        assert rows[0]["id"] == "1"

    def test_limit(self, tmp_path):
        p = tmp_path / "events.jsonl"
        p.write_text("\n".join(f'{{"id":"{i}"}}' for i in range(5)), encoding="utf-8")
        rows = _read_jsonl(p, 2)
        assert len(rows) == 2
        assert rows[0]["id"] == "3"

    def test_missing(self, tmp_path):
        assert _read_jsonl(tmp_path / "no.jsonl", 10) == []


class TestExport:
    def test_creates_archive(self, tmp_path, monkeypatch):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "genes.json").write_text('{"genes":[]}', encoding="utf-8")
        (mem / "genes.jsonl").write_text('{"id":"g1"}\n', encoding="utf-8")
        (mem / "events.jsonl").write_text('{"ts":1}\n{"ts":2}\n', encoding="utf-8")

        import evolver.gep.portable as portable_mod
        monkeypatch.setattr(portable_mod, "get_memory_dir", lambda: mem)

        out = tmp_path / "backup.gepx"
        export_gepx(out)
        assert out.exists()

        with tarfile.open(out, "r:gz") as tf:
            names = set(tf.getnames())
        assert "manifest.json" in names
        assert "genes.json" in names
        assert "events.jsonl" in names

    def test_manifest_checksums(self, tmp_path, monkeypatch):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "genes.json").write_text('{"genes":[]}', encoding="utf-8")

        import evolver.gep.portable as portable_mod
        monkeypatch.setattr(portable_mod, "get_memory_dir", lambda: mem)

        out = tmp_path / "backup.gepx"
        export_gepx(out)

        with tarfile.open(out, "r:gz") as tf:
            manifest = json.loads(tf.extractfile("manifest.json").read())
        assert "genes.json" in manifest["files"]
        assert len(manifest["files"]["genes.json"]) == 64  # sha256 hex


class TestImport:
    def test_roundtrip(self, tmp_path, monkeypatch):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "genes.json").write_text('{"genes":[]}', encoding="utf-8")
        (mem / "events.jsonl").write_text('{"ts":1}\n', encoding="utf-8")

        import evolver.gep.portable as portable_mod
        monkeypatch.setattr(portable_mod, "get_memory_dir", lambda: mem)

        out = tmp_path / "backup.gepx"
        export_gepx(out)

        # Modify local events
        (mem / "events.jsonl").write_text('{"ts":9}\n', encoding="utf-8")

        imported = import_gepx(out, merge=False)
        assert "events.jsonl" in imported["files"]
        # Overwrite mode restores archive content
        rows = _read_jsonl(mem / "events.jsonl", 10)
        assert rows[0]["ts"] == 1

    def test_merge_jsonl(self, tmp_path, monkeypatch):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "events.jsonl").write_text('{"id":"a","timestamp":1}\n', encoding="utf-8")

        import evolver.gep.portable as portable_mod
        monkeypatch.setattr(portable_mod, "get_memory_dir", lambda: mem)

        out = tmp_path / "backup.gepx"
        export_gepx(out)

        # Local gets newer event
        (mem / "events.jsonl").write_text('{"id":"b","timestamp":5}\n', encoding="utf-8")

        imported = import_gepx(out, merge=True)
        rows = _read_jsonl(mem / "events.jsonl", 10)
        ids = {r["id"] for r in rows}
        assert ids == {"a", "b"}

    def test_checksum_mismatch(self, tmp_path):
        out = tmp_path / "bad.gepx"
        buf = bytes()
        import io

        with tarfile.open(fileobj=io.BytesIO(buf), mode="w:gz") as tf:
            manifest = {"version": "1.0", "files": {"x.txt": "0" * 64}}
            data = json.dumps(manifest).encode()
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            bad = b"not matching hash"
            info2 = tarfile.TarInfo(name="x.txt")
            info2.size = len(bad)
            tf.addfile(info2, io.BytesIO(bad))
        out.write_bytes(io.BytesIO().getvalue())
        # Rebuild properly
        import io as bio

        b = bio.BytesIO()
        with tarfile.open(fileobj=b, mode="w:gz") as tf:
            manifest = {"version": "1.0", "files": {"x.txt": "0" * 64}}
            data = json.dumps(manifest).encode()
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(data)
            tf.addfile(info, bio.BytesIO(data))
            bad = b"not matching hash"
            info2 = tarfile.TarInfo(name="x.txt")
            info2.size = len(bad)
            tf.addfile(info2, bio.BytesIO(bad))
        out.write_bytes(b.getvalue())

        with pytest.raises(ImportError, match="Checksum mismatch"):
            import_gepx(out)

    def test_missing_manifest(self, tmp_path):
        out = tmp_path / "bad.gepx"
        import io

        b = io.BytesIO()
        with tarfile.open(fileobj=b, mode="w:gz") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="hello.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        out.write_bytes(b.getvalue())

        with pytest.raises(ImportError, match="Missing manifest"):
            import_gepx(out)
