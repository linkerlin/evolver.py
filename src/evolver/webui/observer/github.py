"""Read-only GitHub PR status for the WebUI (Sprint 16.2).

Ports ``evolver/src/webui/observer/github.js``:

1. ``gh pr view N --json ...`` (argv form, no shell) — preferred.
2. GitHub REST ``/repos/{slug}/pulls/{n}`` — fallback when ``gh`` is missing
   or cannot answer.
3. Negative + positive cache with TTL; never throws on lookup failure.
4. ``EVOLVER_WEBUI_GITHUB=0`` short-circuits the feature.
"""

# Module-level caches mirror Node (Map + slug latch); intentional globals.
# ruff: noqa: PLW0603

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections import OrderedDict
from typing import Any

import httpx

from evolver.gep.paths import get_repo_root

logger = logging.getLogger(__name__)

MAX_EXEC_BUFFER = 10 * 1024 * 1024
GH_TIMEOUT_MS = 5000
API_TIMEOUT_MS = 10.0
NEG_CACHE_TTL_MS = 10_000
MAX_CACHE_ENTRIES = 200
GH_PR_FIELDS = (
    "number,title,state,isDraft,author,additions,deletions,"
    "changedFiles,createdAt,updatedAt,mergedAt,closedAt,url"
)

# number -> {data, at}
_pr_cache: OrderedDict[int, dict[str, Any]] = OrderedDict()
_slug_cache: str | None | object = ...  # Ellipsis = unresolved
_gh_missing_warned = False


def _now_ms() -> float:
    return time.time() * 1000


def is_feature_enabled() -> bool:
    return str(os.environ.get("EVOLVER_WEBUI_GITHUB") or "1").strip() != "0"


def _get_ttl_ms() -> int:
    raw = os.environ.get("EVOLVER_WEBUI_GITHUB_TTL_MS", "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return 60_000


def _get_github_token() -> str:
    return (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_PAT")
        or ""
    )


def normalize_number(input_value: Any) -> int | None:  # noqa: PLR0911
    """Accept only a positive *safe* integer (mirrors Node ``_normalizeNumber``)."""
    max_safe = (1 << 53) - 1  # Number.MAX_SAFE_INTEGER
    if isinstance(input_value, bool):
        return None
    if isinstance(input_value, int):
        return input_value if 0 < input_value <= max_safe else None
    if isinstance(input_value, float):
        if input_value.is_integer():
            n = int(input_value)
            return n if 0 < n <= max_safe else None
        return None
    s = str("" if input_value is None else input_value).strip()
    if not re.fullmatch(r"\d+", s):
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return n if 0 < n <= max_safe else None


def parse_slug_from_remote(url: Any) -> str | None:
    m = re.search(
        r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$",
        str(url or "").strip(),
        re.I,
    )
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _resolve_repo_slug() -> str | None:
    global _slug_cache
    if _slug_cache is not ...:
        return _slug_cache  # type: ignore[return-value]
    env_slug = str(os.environ.get("EVOLVER_GITHUB_REPO") or "").strip()
    if env_slug:
        _slug_cache = env_slug
        return env_slug
    try:
        root = get_repo_root()
        cwd = str(root) if root else None
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_MS / 1000,
            check=False,
        )
        if out.returncode == 0:
            parsed = parse_slug_from_remote(out.stdout)
            if parsed:
                _slug_cache = parsed
                return parsed
    except (OSError, subprocess.SubprocessError):
        pass
    # Optional SELF_PR_REPO-style env used by some ports.
    fallback = str(os.environ.get("EVOLVER_SELF_PR_REPO") or "").strip() or None
    _slug_cache = fallback
    return fallback


def normalize_state(raw_state: Any, is_draft: Any, merged_at: Any) -> str:
    if merged_at:
        return "merged"
    s = str(raw_state or "").lower()
    if s == "merged":
        return "merged"
    if s == "closed":
        return "closed"
    if is_draft:
        return "draft"
    return "open" if s == "open" else (s or "open")


def _normalize_gh(raw: dict[str, Any]) -> dict[str, Any]:
    author_obj = raw.get("author")
    if isinstance(author_obj, dict):
        author = str(author_obj.get("login") or author_obj.get("name") or "")
    else:
        author = ""
    return {
        "number": raw.get("number"),
        "title": str(raw.get("title") or ""),
        "state": normalize_state(raw.get("state"), raw.get("isDraft"), raw.get("mergedAt")),
        "author": author,
        "additions": int(raw.get("additions") or 0),
        "deletions": int(raw.get("deletions") or 0),
        "changedFiles": int(raw.get("changedFiles") or 0),
        "createdAt": raw.get("createdAt") or None,
        "updatedAt": raw.get("updatedAt") or None,
        "mergedAt": raw.get("mergedAt") or None,
        "closedAt": raw.get("closedAt") or None,
        "url": str(raw.get("url") or ""),
        "source": "gh",
        "available": True,
    }


def _normalize_api(raw: dict[str, Any]) -> dict[str, Any]:
    user = raw.get("user")
    author = str(user.get("login") or "") if isinstance(user, dict) else ""
    return {
        "number": raw.get("number"),
        "title": str(raw.get("title") or ""),
        "state": normalize_state(raw.get("state"), raw.get("draft"), raw.get("merged_at")),
        "author": author,
        "additions": int(raw.get("additions") or 0),
        "deletions": int(raw.get("deletions") or 0),
        "changedFiles": int(raw.get("changed_files") or 0),
        "createdAt": raw.get("created_at") or None,
        "updatedAt": raw.get("updated_at") or None,
        "mergedAt": raw.get("merged_at") or None,
        "closedAt": raw.get("closed_at") or None,
        "url": str(raw.get("html_url") or ""),
        "source": "api",
        "available": True,
    }


def _fetch_via_gh(n: int) -> dict[str, Any] | None:
    global _gh_missing_warned
    try:
        root = get_repo_root()
        cwd = str(root) if root else None
        res = subprocess.run(
            ["gh", "pr", "view", str(n), "--json", GH_PR_FIELDS],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_MS / 1000,
            check=False,
        )
    except FileNotFoundError as exc:
        if not _gh_missing_warned:
            _gh_missing_warned = True
            logger.warning(
                "[WebUI/GitHub] gh CLI not available — falling back to REST API. "
                "Install gh or set a GITHUB_TOKEN. (%s)",
                exc,
            )
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        msg = str(exc)
        gh_missing = "ENOENT" in msg or "cannot find" in msg.lower() or "not found" in msg.lower()
        if gh_missing and not _gh_missing_warned:
            _gh_missing_warned = True
            logger.warning("[WebUI/GitHub] gh CLI not available — falling back to REST API.")
        return None

    if res.returncode != 0:
        # Unknown/private PR etc. — fall through to REST, not "gh missing".
        return None
    try:
        parsed = json.loads(res.stdout or "{}")
    except ValueError:
        return None
    if not isinstance(parsed, dict) or parsed.get("number") is None:
        return None
    return _normalize_gh(parsed)


def _fetch_via_api(n: int) -> dict[str, Any]:  # noqa: PLR0911
    slug = _resolve_repo_slug()
    if not slug:
        return {"number": n, "available": False, "reason": "no_repo_slug"}
    token = _get_github_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "evolver-webui",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{slug}/pulls/{n}"
    try:
        with httpx.Client(timeout=API_TIMEOUT_MS) as client:
            res = client.get(url, headers=headers)
    except Exception:
        return {"number": n, "available": False, "reason": "network_error"}

    if res.status_code == 404:
        return {"number": n, "available": False, "reason": "not_found"}
    if res.status_code in (403, 429):
        return {"number": n, "available": False, "reason": "rate_limited"}
    if res.status_code < 200 or res.status_code >= 300:
        return {"number": n, "available": False, "reason": f"http_{res.status_code}"}
    try:
        data = res.json()
    except Exception:
        return {"number": n, "available": False, "reason": "bad_json"}
    if not isinstance(data, dict) or data.get("number") is None:
        return {"number": n, "available": False, "reason": "bad_json"}
    return _normalize_api(data)


def _cache_get(n: int) -> dict[str, Any] | None:
    hit = _pr_cache.get(n)
    if not hit:
        return None
    data = hit["data"]
    ttl = _get_ttl_ms() if data.get("available") else NEG_CACHE_TTL_MS
    if _now_ms() - hit["at"] >= ttl:
        _pr_cache.pop(n, None)
        return None
    # LRU touch
    _pr_cache.move_to_end(n)
    return data  # type: ignore[return-value]


def _cache_set(n: int, data: dict[str, Any]) -> None:
    _pr_cache[n] = {"data": data, "at": _now_ms()}
    _pr_cache.move_to_end(n)
    while len(_pr_cache) > MAX_CACHE_ENTRIES:
        _pr_cache.popitem(last=False)


def get_pr_status(input_value: Any) -> dict[str, Any]:
    """Get one PR's normalized status. Never raises."""
    n = normalize_number(input_value)
    if n is None:
        return {"number": None, "available": False, "reason": "invalid_number"}
    if not is_feature_enabled():
        return {"number": n, "available": False, "reason": "feature_disabled"}

    cached = _cache_get(n)
    if cached is not None:
        return cached

    data = _fetch_via_gh(n)
    if data is None:
        data = _fetch_via_api(n)
    if data is None:
        data = {"number": n, "available": False, "reason": "unavailable"}
    _cache_set(n, data)
    return data


def get_open_prs() -> list[dict[str, Any]]:
    """Open PRs for the dedicated panel (from local open_pr_registry)."""
    if not is_feature_enabled():
        return []
    try:
        from evolver.gep.open_pr_registry import get_open_prs as _registry_open

        prs = _registry_open() or []
        out: list[dict[str, Any]] = []
        for pr in prs:
            if not isinstance(pr, dict):
                continue
            files = pr.get("files")
            out.append(
                {
                    "number": pr.get("number"),
                    "title": str(pr.get("title") or ""),
                    "headRefName": str(pr.get("headRefName") or pr.get("head_ref") or ""),
                    "fileCount": len(files) if isinstance(files, list) else 0,
                }
            )
        return out
    except Exception:
        return []


def get_repo_info() -> dict[str, Any]:
    slug = _resolve_repo_slug() if is_feature_enabled() else None
    return {
        "slug": slug or None,
        "prUrlBase": f"https://github.com/{slug}/pull" if slug else None,
        "available": bool(slug),
    }


def reset_for_testing() -> None:
    """Clear caches (tests)."""
    global _slug_cache, _gh_missing_warned
    _pr_cache.clear()
    _slug_cache = ...
    _gh_missing_warned = False


# Test-facing aliases matching Node exports
_normalize_number = normalize_number
_parse_slug_from_remote = parse_slug_from_remote
_normalize_state = normalize_state
_reset_for_testing = reset_for_testing


__all__ = [
    "get_open_prs",
    "get_pr_status",
    "get_repo_info",
    "is_feature_enabled",
    "normalize_number",
    "normalize_state",
    "parse_slug_from_remote",
    "reset_for_testing",
]
