"""Self-PR — automatically create GitHub Pull Requests for high-confidence mutations.

Equivalent to Node's ``evolver/src/gep/selfPR.js``.

When a solidify scores above the threshold (default 0.85), passes all
policy checks, and contains no secret leaks, this module can
automatically create a PR.

Flow
----
1. Score check: solidify confidence >= threshold
2. Safety checks: policy_check passes, no secret leaks
3. Cool-down: no PR from same branch in 24h
4. Diff dedup: similarity to open PRs < 0.9
5. Create branch: ``evolver-auto/{timestamp}-{gene-id}``
6. Commit + push
7. Open PR via ``gh`` CLI or GitHub API
8. Register in :mod:`open_pr_registry`

Rollback
--------
If any step after branch creation fails, the remote branch is deleted
to avoid pollution.

Design notes
------------
* Requires ``gh`` CLI or ``GITHUB_TOKEN`` env var.
* All git operations use atomic patterns.
* Respects ``enable_self_pr`` feature flag.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from evolver.gep.epigenetics import capture_env_fingerprint, env_fingerprint_key
from evolver.gep.feature_flags import is_enabled
from evolver.gep.open_pr_registry import load_registry, register_pr
from evolver.gep.paths import get_workspace_root
from evolver.gep.policy_check import check_policy
from evolver.gep.sanitize import full_leak_check

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_MIN_SCORE = 0.85
DEFAULT_COOLDOWN_SECONDS = 86400  # 24 h
MAX_DIFF_SIMILARITY = 0.9
BRANCH_PREFIX = "evolver-auto"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SelfPRResult:
    success: bool
    pr_url: str = ""
    branch: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _check_score(confidence: float, threshold: float = DEFAULT_MIN_SCORE) -> bool:
    return confidence >= threshold


def _check_policy(diff_text: str) -> bool:
    # Extract changed file paths from diff text
    changed: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git a/"):
            parts = line.split()
            if len(parts) >= 4:
                changed.append(parts[2][2:])  # strip "b/" prefix
    report = check_policy(diff_text=diff_text, changed_files=changed, untracked_files=[])
    return report.ok and not report.has_critical


def _check_secrets(diff_text: str) -> bool:
    return bool(full_leak_check(diff_text)["safe"])


def _check_cooldown(gene_id: str, registry: dict[str, Any]) -> bool:
    now = time.time()
    for pr in registry.get("prs", []):
        if pr.get("gene_id") == gene_id:
            created = pr.get("created_at", 0)
            if (now - created) < DEFAULT_COOLDOWN_SECONDS:
                return False
    return True


def _diff_similarity(a: str, b: str) -> float:
    """Simple Jaccard-ish similarity on diff lines."""
    set_a = set(line.strip() for line in a.splitlines() if line.strip())
    set_b = set(line.strip() for line in b.splitlines() if line.strip())
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _check_diff_dedup(diff_text: str, registry: dict[str, Any]) -> bool:
    for pr in registry.get("prs", []):
        old_diff = pr.get("diff_text", "")
        if _diff_similarity(diff_text, old_diff) >= MAX_DIFF_SIMILARITY:
            return False
    return True


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    root = cwd or get_workspace_root()
    cmd = ["git", *args]
    result = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    return result.stdout.strip()


def _get_current_branch() -> str:
    return _run_git("branch", "--show-current")


def _create_branch(branch: str) -> None:
    _run_git("checkout", "-b", branch)


def _commit(message: str) -> None:
    _run_git("add", "-A")
    _run_git("commit", "-m", message, "--no-verify")


def _push_branch(branch: str) -> None:
    _run_git("push", "-u", "origin", branch)


def _delete_remote_branch(branch: str) -> None:
    try:
        _run_git("push", "origin", "--delete", branch, check=False)
    except Exception as exc:
        logger.debug("[SelfPR] Failed to delete remote branch %s: %s", branch, exc)


def _repo_from_git() -> str | None:
    try:
        url = _run_git("remote", "get-url", "origin", check=False)
        m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception as exc:
        logger.debug("[SelfPR] Failed to detect repo from git remote: %s", exc)
    return None


# ---------------------------------------------------------------------------
# PR creation
# ---------------------------------------------------------------------------


def _create_pr_via_gh(branch: str, title: str, body: str) -> dict[str, Any] | None:
    """Try ``gh pr create``. Returns parsed JSON or None."""
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--head",
                branch,
                "--json",
                "url,number",
            ],
            cwd=str(get_workspace_root()),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return cast(dict[str, Any], json.loads(result.stdout.strip()))
        logger.debug("[SelfPR] gh CLI failed: %s", result.stderr)
    except FileNotFoundError:
        logger.debug("[SelfPR] gh CLI not found")
    return None


def _create_pr_via_api(
    repo: str, branch: str, title: str, body: str, token: str
) -> dict[str, Any] | None:
    """Try GitHub API. Returns parsed JSON or None."""
    try:
        import httpx

        resp = httpx.post(
            f"https://api.github.com/repos/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": branch,
                "base": _get_current_branch(),
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )
        if resp.status_code in (200, 201):
            return cast(dict[str, Any], resp.json())
        logger.warning("[SelfPR] GitHub API returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("[SelfPR] API call failed: %s", exc)
    return None


def _build_pr_body(
    *,
    gene_summary: str,
    diff_text: str,
    validation_command: str = "pytest",
    env: dict[str, str] | None = None,
) -> str:
    env_key = env_fingerprint_key(env or capture_env_fingerprint())
    body_lines = [
        "## Auto-Generated PR by evolver",
        "",
        f"**Gene Summary**: {gene_summary}",
        f"**Env Fingerprint**: `{env_key}`",
        "",
        "### Validation",
        "",
        f"```bash\n{validation_command}\n```",
        "",
        "### Diff Summary",
        "",
        f"```diff\n{diff_text[:2000]}\n```"
        if len(diff_text) <= 2000
        else f"```diff\n{diff_text[:2000]}\n... (truncated)\n```",
        "",
        "---",
        "",
        "_This PR was automatically generated. Review before merge._",
    ]
    return "\n".join(body_lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_self_pr(
    *,
    diff_text: str,
    gene_id: str,
    gene_summary: str,
    confidence: float,
    validation_command: str = "pytest",
    min_score: float = DEFAULT_MIN_SCORE,
    env: dict[str, str] | None = None,
) -> SelfPRResult:
    """Attempt to create a self-PR for a solidified mutation.

    Returns :class:`SelfPRResult` with ``success=True`` and ``pr_url`` on
    success, or ``success=False`` and ``reason`` on failure.
    """
    if not is_enabled("enable_self_pr"):
        return SelfPRResult(success=False, reason="feature flag disabled")

    # 1. Score check
    if not _check_score(confidence, min_score):
        return SelfPRResult(success=False, reason=f"confidence {confidence:.2f} < {min_score}")

    # 2. Policy check
    if not _check_policy(diff_text):
        return SelfPRResult(success=False, reason="policy check failed")

    # 3. Secret leak check
    if not _check_secrets(diff_text):
        return SelfPRResult(success=False, reason="potential secret leak detected")

    # 4. Load registry
    registry = load_registry()

    # 5. Cooldown
    if not _check_cooldown(gene_id, registry):
        return SelfPRResult(success=False, reason="cooldown active")

    # 6. Diff dedup
    if not _check_diff_dedup(diff_text, registry):
        return SelfPRResult(success=False, reason="diff too similar to existing PR")

    # 7. Create branch
    now = int(time.time())
    branch = f"{BRANCH_PREFIX}/{now}-{gene_id}"
    original_branch = _get_current_branch()
    try:
        _create_branch(branch)
    except subprocess.CalledProcessError as exc:
        return SelfPRResult(success=False, reason=f"branch creation failed: {exc}")

    # 8. Commit
    try:
        _commit(gene_summary or "evolver auto-commit")
    except subprocess.CalledProcessError as exc:
        _run_git("checkout", original_branch)
        _run_git("branch", "-D", branch, check=False)
        return SelfPRResult(success=False, reason=f"commit failed: {exc}")

    # 9. Push
    try:
        _push_branch(branch)
    except subprocess.CalledProcessError as exc:
        _run_git("checkout", original_branch)
        _run_git("branch", "-D", branch, check=False)
        return SelfPRResult(success=False, reason=f"push failed: {exc}")

    # 10. Open PR
    title = f"[evolver-auto] {gene_summary[:80]}"
    body = _build_pr_body(
        gene_summary=gene_summary,
        diff_text=diff_text,
        validation_command=validation_command,
        env=env,
    )

    pr_data = _create_pr_via_gh(branch, title, body)
    if pr_data is None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        repo = _repo_from_git()
        if token and repo:
            pr_data = _create_pr_via_api(repo, branch, title, body, token)

    if pr_data is None:
        # Rollback
        _delete_remote_branch(branch)
        _run_git("checkout", original_branch)
        _run_git("branch", "-D", branch, check=False)
        return SelfPRResult(success=False, reason="PR creation failed")

    # 11. Register
    pr_url = pr_data.get("html_url") or pr_data.get("url", "")
    register_pr(
        pr_number=pr_data.get("number", 0),
        pr_url=pr_url,
        branch=branch,
        gene_id=gene_id,
        diff_text=diff_text,
        confidence=confidence,
    )
    logger.info("[SelfPR] Created PR %s on branch %s", pr_url, branch)
    return SelfPRResult(success=True, pr_url=pr_url, branch=branch)
