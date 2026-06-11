"""Skill updater: poll Hub for skill updates and auto-apply them.

Equivalent to evolver/src/proxy/extensions/skillUpdater.js.
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from evolver.config import resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers, get_node_id
from evolver.proxy.router.features import is_route_enabled


class SkillUpdater:
    """Poll Hub for skill updates and auto-download / rollback."""

    def __init__(
        self,
        skills_dir: Path | None = None,
        *,
        mailbox_store: Any | None = None,
        state_path: Path | None = None,
    ) -> None:
        from evolver.gep.paths import get_repo_root

        repo = get_repo_root()
        self.skills_dir = skills_dir or (repo / "skills" if repo else Path("skills"))
        self._mailbox_store = mailbox_store
        self._state_path_override = state_path
        self._disabled = False
        self._last_check: float = 0.0

    def disable(self) -> None:
        self._disabled = True

    def enable(self) -> None:
        self._disabled = False

    @property
    def disabled(self) -> bool:
        return self._disabled

    def _state_path(self) -> Path:
        if self._state_path_override is not None:
            return self._state_path_override
        from evolver.gep.paths import get_repo_root

        repo = get_repo_root() or Path.cwd()
        return repo / ".evolver" / "skill-updater-state.json"

    def _load_state(self) -> dict[str, Any]:
        path = self._state_path()
        if not path.exists():
            return {"last_check": 0.0, "applied_ids": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"last_check": 0.0, "applied_ids": []}

    def _save_state(self, state: dict[str, Any]) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _local_skill_ids(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        return [p.name for p in self.skills_dir.iterdir() if p.is_dir()]

    def _poll_hub(self, since: float) -> tuple[list[dict[str, Any]], str | None]:
        try:
            hub = resolve_hub_url()
        except ValueError:
            return [], "no_hub_url"

        url = f"{hub}/v1/a2a/skills/updates"
        payload: dict[str, Any] = {
            "since": int(since * 1000),
            "skills": self._local_skill_ids(),
        }
        node_id = get_node_id()
        if node_id:
            payload["node_id"] = node_id

        try:
            with httpx.Client(timeout=30.0, http2=True) as client:
                response = client.post(url, json=payload, headers=build_hub_headers())
                if response.status_code >= 400:
                    return [], f"hub_http_{response.status_code}"
                body = response.json()
                if not isinstance(body, dict):
                    return [], "invalid_response"
                raw = body.get("updates", [])
                if not isinstance(raw, list):
                    return [], None
                return [item for item in raw if isinstance(item, dict)], None
        except Exception as exc:
            return [], str(exc)

    def _poll_mailbox(self) -> list[dict[str, Any]]:
        if self._mailbox_store is None:
            return []
        messages = self._mailbox_store.list(type="skill_update", direction="inbound", limit=50)
        updates: list[dict[str, Any]] = []
        for msg in messages:
            payload = msg.payload if isinstance(msg.payload, dict) else {}
            skill_id = payload.get("skill_id") or payload.get("id")
            if not skill_id:
                continue
            updates.append(
                {
                    "skill_id": skill_id,
                    "version": payload.get("version"),
                    "download_url": payload.get("download_url"),
                    "source": "mailbox",
                    "message_id": msg.id,
                }
            )
        return updates

    def _normalize_updates(
        self,
        raw_updates: list[dict[str, Any]],
        applied: set[str],
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in raw_updates:
            skill_id = item.get("skill_id") or item.get("id")
            if not skill_id:
                continue
            update_id = str(item.get("update_id") or f"{skill_id}:{item.get('version', '')}")
            if update_id in applied:
                continue
            filtered.append({**item, "skill_id": skill_id, "update_id": update_id})
        return filtered

    def check_for_updates(self) -> dict[str, Any]:
        """Check Hub (or mailbox fallback) for skill updates."""
        if self._disabled:
            return {"ok": True, "updates": [], "disabled": True}

        if not is_route_enabled("skill_update"):
            self._last_check = time.time()
            return {
                "ok": True,
                "updates": [],
                "feature_disabled": True,
                "checked_at": self._last_check,
            }

        state = self._load_state()
        since = float(state.get("last_check", 0.0))
        applied = {str(x) for x in state.get("applied_ids", [])}

        hub_updates, hub_error = self._poll_hub(since)
        source = "hub"
        updates = hub_updates
        if not hub_updates:
            mailbox_updates = self._poll_mailbox()
            if mailbox_updates:
                updates = mailbox_updates
                source = "mailbox"
            elif hub_error:
                source = "none"

        filtered = self._normalize_updates(updates, applied)
        self._last_check = time.time()
        state["last_check"] = self._last_check
        self._save_state(state)

        result: dict[str, Any] = {
            "ok": True,
            "updates": filtered,
            "checked_at": self._last_check,
            "source": source,
        }
        if hub_error and not filtered:
            result["hub_error"] = hub_error
        return result

    def mark_applied(self, update_id: str) -> None:
        """Record that an update was applied so it is not offered again."""
        state = self._load_state()
        applied = state.setdefault("applied_ids", [])
        if update_id not in applied:
            applied.append(update_id)
        self._save_state(state)

    async def install_from_hub(self, update: dict[str, Any]) -> dict[str, Any]:
        """Install a single Hub update (equivalent to ``evolver fetch <query>``)."""
        skill_id = str(update.get("skill_id") or update.get("id") or "")
        if not skill_id:
            return {"ok": False, "error": "missing_skill_id"}

        update_id = str(update.get("update_id") or f"{skill_id}:{update.get('version', '')}")
        download_url = update.get("download_url")
        asset_id = update.get("asset_id")
        target = self.skills_dir / skill_id

        result: dict[str, Any]
        if asset_id:
            from evolver.gep.fetch import download_asset, install_capsule, install_gene

            downloaded = await download_asset(str(asset_id))
            if not downloaded.get("ok"):
                return {
                    "ok": False,
                    "error": downloaded.get("error"),
                    "skill_id": skill_id,
                }
            asset = downloaded["asset"]
            asset_type = asset.get("type")
            if asset_type == "Gene":
                result = install_gene(asset)
            elif asset_type == "Capsule":
                result = install_capsule(asset)
            else:
                result = {"ok": False, "error": f"unsupported_asset_type:{asset_type}"}
        elif download_url:
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                (target / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
            result = self.apply_update(skill_id, str(download_url))
        else:
            from evolver.gep.fetch import fetch_and_install

            fetch_result = await fetch_and_install(query=skill_id, limit=1)
            if not fetch_result.get("ok"):
                return {
                    "ok": False,
                    "error": fetch_result.get("error"),
                    "skill_id": skill_id,
                }
            installed = fetch_result.get("installed", [])
            if not installed:
                return {"ok": False, "error": "no_assets_found", "skill_id": skill_id}
            first = installed[0]
            if first.get("error"):
                return {"ok": False, "error": first["error"], "skill_id": skill_id}
            result = {
                "ok": True,
                "skill_id": skill_id,
                "installed": installed,
                "via": "fetch",
            }

        if result.get("ok"):
            self.mark_applied(update_id)
            result["update_id"] = update_id
        return result

    async def process_updates(self, *, auto_apply: bool = True) -> dict[str, Any]:
        """Poll Hub and auto-install pending skill updates."""
        check = self.check_for_updates()
        updates = list(check.get("updates", []))
        if not check.get("ok") or not auto_apply or not updates:
            return {**check, "applied": []}

        applied: list[dict[str, Any]] = []
        for update in updates:
            applied.append(await self.install_from_hub(update))
        return {
            "ok": True,
            "checked_at": check.get("checked_at"),
            "source": check.get("source"),
            "updates": updates,
            "applied": applied,
        }

    def _download_url(self, url: str, dest: Path) -> None:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            dest.write_bytes(response.content)

    def _extract_zip_into(self, zip_path: Path, target: Path) -> None:
        extract_root = target.parent / f".{target.name}.extract-{int(time.time())}"
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.extractall(extract_root)
            children = [p for p in extract_root.iterdir() if p.name != "__MACOSX"]
            source = children[0] if len(children) == 1 and children[0].is_dir() else extract_root
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target, dirs_exist_ok=True)
        finally:
            shutil.rmtree(extract_root, ignore_errors=True)
            zip_path.unlink(missing_ok=True)

    def apply_update(self, skill_id: str, download_url: str | None = None) -> dict[str, Any]:
        """Download and apply a skill update.

        Creates a backup before updating. Zip archives are extracted into the skill dir.
        """
        target = self.skills_dir / skill_id
        if not target.exists():
            return {"ok": False, "error": "skill_not_found", "skill_id": skill_id}

        backup = self.skills_dir / f"{skill_id}.bak.{int(time.time())}"
        try:
            shutil.copytree(target, backup, dirs_exist_ok=True)
        except Exception as exc:
            return {"ok": False, "error": "backup_failed", "detail": str(exc)}

        if download_url:
            zip_path = target / "update.zip"
            try:
                self._download_url(download_url, zip_path)
                if zipfile.is_zipfile(zip_path):
                    self._extract_zip_into(zip_path, target)
                else:
                    zip_path.unlink(missing_ok=True)
            except Exception as exc:
                try:
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(backup, target, dirs_exist_ok=True)
                except Exception:
                    pass
                return {"ok": False, "error": "download_failed", "detail": str(exc)}

        return {"ok": True, "skill_id": skill_id, "backup": str(backup)}

    def rollback(self, skill_id: str, backup_path: str | None = None) -> dict[str, Any]:
        """Rollback a skill to its previous version."""
        target = self.skills_dir / skill_id
        if backup_path:
            backup = Path(backup_path)
        else:
            # Find most recent backup
            backups = sorted(
                self.skills_dir.glob(f"{skill_id}.bak.*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not backups:
                return {"ok": False, "error": "no_backup_found"}
            backup = backups[0]

        if not backup.exists():
            return {"ok": False, "error": "backup_not_found", "path": str(backup)}

        try:
            import shutil

            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(backup, target, dirs_exist_ok=True)
            return {"ok": True, "skill_id": skill_id, "restored_from": str(backup)}
        except Exception as exc:
            return {"ok": False, "error": "rollback_failed", "detail": str(exc)}


def create_skill_updater(
    skills_dir: Path | None = None,
    *,
    mailbox_store: Any | None = None,
    state_path: Path | None = None,
) -> SkillUpdater:
    return SkillUpdater(
        skills_dir=skills_dir,
        mailbox_store=mailbox_store,
        state_path=state_path,
    )


__all__ = ["SkillUpdater", "create_skill_updater"]
