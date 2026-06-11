"""Tests for evolver.proxy.extensions.skill_updater."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from evolver.proxy.extensions.skill_updater import SkillUpdater, create_skill_updater
from evolver.proxy.mailbox.store import MailboxStore


class TestCreateSkillUpdater:
    def test_returns_instance(self):
        updater = create_skill_updater()
        assert isinstance(updater, SkillUpdater)


class TestCheckForUpdates:
    def test_disabled(self):
        updater = create_skill_updater()
        updater.disable()
        result = updater.check_for_updates()
        assert result["ok"] is True
        assert result["disabled"] is True
        assert result["updates"] == []

    def test_feature_disabled_by_default(self):
        updater = create_skill_updater()
        updater.enable()
        result = updater.check_for_updates()
        assert result["ok"] is True
        assert result["updates"] == []
        assert result.get("feature_disabled") is True

    def test_hub_poll_returns_updates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE", "true")
        monkeypatch.setenv("A2A_HUB_URL", "https://hub.test")
        with respx.mock:
            respx.post("https://hub.test/v1/a2a/skills/updates").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "updates": [
                            {
                                "skill_id": "my-skill",
                                "version": "2",
                                "download_url": "http://example.com/skill.zip",
                            }
                        ]
                    },
                )
            )
            updater = create_skill_updater(state_path=tmp_path / "skill-state.json")
            result = updater.check_for_updates()
        assert result["ok"] is True
        assert result["source"] == "hub"
        assert len(result["updates"]) == 1
        assert result["updates"][0]["skill_id"] == "my-skill"

    def test_mailbox_fallback_when_hub_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE", "true")
        monkeypatch.setenv("A2A_HUB_URL", "https://hub.test")
        store = MailboxStore(tmp_path / "mailbox")
        store.write_inbound(
            id="msg-1",
            type="skill_update",
            payload={"skill_id": "mailbox-skill", "version": "3"},
        )
        with respx.mock:
            respx.post("https://hub.test/v1/a2a/skills/updates").mock(
                return_value=httpx.Response(503, json={"error": "unavailable"})
            )
            updater = create_skill_updater(mailbox_store=store)
            result = updater.check_for_updates()
        assert result["ok"] is True
        assert result["source"] == "mailbox"
        assert result["updates"][0]["skill_id"] == "mailbox-skill"


class TestApplyUpdate:
    def test_skill_not_found(self):
        updater = create_skill_updater(skills_dir=Path("/nonexistent"))
        result = updater.apply_update("missing-skill")
        assert result["ok"] is False
        assert result["error"] == "skill_not_found"

    def test_apply_creates_backup(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")
        updater = create_skill_updater(skills_dir=tmp_path)
        result = updater.apply_update("my-skill")
        assert result["ok"] is True
        assert "backup" in result
        backup_path = Path(result["backup"])
        assert backup_path.exists()

    def test_download_failure_rollback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")
        updater = create_skill_updater(skills_dir=tmp_path)

        def fail_download(*args: object, **kwargs: object) -> None:
            raise OSError("network error")

        monkeypatch.setattr(updater, "_download_url", fail_download)
        result = updater.apply_update("my-skill", download_url="http://example.com/skill.zip")
        assert result["ok"] is False
        assert result["error"] == "download_failed"

    def test_zip_extract_replaces_skill_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import io
        import zipfile

        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("old", encoding="utf-8")
        updater = create_skill_updater(skills_dir=tmp_path)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "new content")
        zip_bytes = buf.getvalue()

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            content = zip_bytes

        class FakeClient:
            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def get(self, url: str) -> FakeResponse:
                return FakeResponse()

        monkeypatch.setattr("httpx.Client", lambda **kwargs: FakeClient())
        result = updater.apply_update("my-skill", download_url="http://example.com/skill.zip")
        assert result["ok"] is True
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "new content"


class TestInstallFromHub:
    async def test_fetch_and_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE", "true")
        monkeypatch.setenv("A2A_HUB_URL", "https://hub.test")
        updater = create_skill_updater(skills_dir=tmp_path)
        with respx.mock:
            respx.post("https://hub.test/v1/a2a/search").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "assets": [
                            {
                                "type": "Gene",
                                "id": "gene-1",
                                "category": "repair",
                                "signals_match": ["err"],
                                "strategy": ["fix"],
                                "validation": ["test"],
                            }
                        ]
                    },
                )
            )
            result = await updater.install_from_hub(
                {"skill_id": "gene-1", "update_id": "gene-1:v2"}
            )
        assert result["ok"] is True
        assert result["via"] == "fetch"

    async def test_process_updates_applies_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SKILL_AUTO_UPDATE", "true")
        monkeypatch.setenv("A2A_HUB_URL", "https://hub.test")
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")
        updater = create_skill_updater(
            skills_dir=tmp_path,
            state_path=tmp_path / "skill-state.json",
        )
        with respx.mock:
            respx.post("https://hub.test/v1/a2a/skills/updates").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "updates": [
                            {
                                "skill_id": "my-skill",
                                "version": "2",
                                "download_url": "http://example.com/skill.zip",
                            }
                        ]
                    },
                )
            )
            monkeypatch.setattr(
                updater,
                "apply_update",
                lambda skill_id, download_url=None: {
                    "ok": True,
                    "skill_id": skill_id,
                    "backup": str(tmp_path / "bak"),
                },
            )
            result = await updater.process_updates()
        assert result["ok"] is True
        assert len(result["applied"]) == 1
        assert result["applied"][0]["ok"] is True


class TestRollback:
    def test_no_backup(self, tmp_path: Path):
        updater = create_skill_updater(skills_dir=tmp_path)
        result = updater.rollback("my-skill")
        assert result["ok"] is False
        assert result["error"] == "no_backup_found"

    def test_rollback_success(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("v1", encoding="utf-8")
        updater = create_skill_updater(skills_dir=tmp_path)
        # Create backup
        apply_result = updater.apply_update("my-skill")
        assert apply_result["ok"] is True
        # Modify skill
        (skill_dir / "SKILL.md").write_text("v2", encoding="utf-8")
        # Rollback
        result = updater.rollback("my-skill", backup_path=apply_result["backup"])
        assert result["ok"] is True
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "v1"

    def test_rollback_auto_find_backup(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("v1", encoding="utf-8")
        updater = create_skill_updater(skills_dir=tmp_path)
        apply_result = updater.apply_update("my-skill")
        (skill_dir / "SKILL.md").write_text("v2", encoding="utf-8")
        result = updater.rollback("my-skill")
        assert result["ok"] is True
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "v1"
