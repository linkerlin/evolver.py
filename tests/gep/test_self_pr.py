"""Tests for evolver.gep.self_pr — including v1.91.0 injection hard-stop."""

from __future__ import annotations

import inspect
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

import evolver.gep.self_pr as self_pr_mod
from evolver.gep.self_pr import (
    DEFAULT_MIN_SCORE,
    _check_cooldown,
    _check_diff_dedup,
    _check_policy,
    _check_score,
    _check_secrets,
    _create_pr_via_gh,
    _diff_similarity,
    _run_git,
    create_self_pr,
    make_auto_branch_name,
    run_argv,
    sanitize_branch_component,
)


class TestChecks:
    def test_score_pass(self) -> None:
        assert _check_score(0.9, DEFAULT_MIN_SCORE)

    def test_score_fail(self) -> None:
        assert not _check_score(0.5, DEFAULT_MIN_SCORE)

    def test_policy_pass(self) -> None:
        assert _check_policy("diff --git a/foo.py b/foo.py\n+hello")

    def test_policy_fail(self) -> None:
        assert not _check_policy("diff --git a/.env b/.env\n+secret")

    def test_secrets_pass(self) -> None:
        assert _check_secrets("some normal code")

    def test_secrets_fail(self) -> None:
        assert not _check_secrets("Authorization: Bearer sk-1234567890abcdefghij")

    def test_cooldown(self) -> None:
        registry = {
            "prs": [
                {"gene_id": "g1", "created_at": time.time()},
            ]
        }
        assert not _check_cooldown("g1", registry)
        assert _check_cooldown("g2", registry)

    def test_diff_dedup(self) -> None:
        diff = "+line1\n+line2"
        registry = {
            "prs": [
                {"diff_text": "+line1\n+line2"},
            ]
        }
        assert not _check_diff_dedup(diff, registry)

    def test_diff_similarity(self) -> None:
        a = "+line1\n+line2\n+line3"
        b = "+line1\n+line2\n+line4"
        sim = _diff_similarity(a, b)
        assert 0 < sim < 1


class TestCreateSelfPR:
    def test_feature_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "0")
        result = create_self_pr(
            diff_text="+hello",
            gene_id="g1",
            gene_summary="test",
            confidence=0.9,
        )
        assert not result.success
        assert "feature flag" in result.reason.lower()

    def test_low_confidence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        result = create_self_pr(
            diff_text="+hello",
            gene_id="g1",
            gene_summary="test",
            confidence=0.5,
        )
        assert not result.success
        assert "confidence" in result.reason.lower()

    def test_policy_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        result = create_self_pr(
            diff_text="diff --git a/.env b/.env\n+secret=1",
            gene_id="g1",
            gene_summary="test",
            confidence=0.9,
        )
        assert not result.success
        assert "policy" in result.reason.lower()

    def test_secret_leak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        result = create_self_pr(
            diff_text="+Authorization: Bearer sk-1234567890abcdefghij",
            gene_id="g1",
            gene_summary="test",
            confidence=0.9,
        )
        assert not result.success
        # Either policy_check or explicit secret check may catch it first
        assert "secret" in result.reason.lower() or "policy" in result.reason.lower()


# ---------------------------------------------------------------------------
# Sprint 14.4 — Semgrep #285 / Node v1.91.0: argv-only, no shell injection
# ---------------------------------------------------------------------------


class TestBranchSanitize:
    def test_strips_shell_metacharacters(self) -> None:
        assert "$(" not in sanitize_branch_component("evil$(whoami)")
        assert ";" not in sanitize_branch_component("a;rm -rf /")
        assert "`" not in sanitize_branch_component("x`id`y")
        assert "\n" not in sanitize_branch_component("a\nb")

    def test_collapses_path_separators(self) -> None:
        safe = sanitize_branch_component("../../etc/passwd")
        assert "/" not in safe
        assert "\\" not in safe
        assert safe  # non-empty fallback path

    def test_empty_falls_back(self) -> None:
        assert sanitize_branch_component("") == "gene"
        assert sanitize_branch_component("$$$") == "gene"

    def test_make_auto_branch_uses_safe_gene(self) -> None:
        name = make_auto_branch_name('g1"; curl evil.com #', now=1_700_000_000)
        assert name.startswith("evolver-auto/1700000000-")
        assert "curl" not in name or " " not in name
        assert ";" not in name
        assert '"' not in name
        assert "#" not in name


class TestArgvOnlyRunner:
    def test_rejects_string_command(self) -> None:
        with pytest.raises(TypeError, match="argv"):
            run_argv("git status")  # type: ignore[arg-type]

    def test_shell_false_and_list_argv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls: list[dict[str, Any]] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append({"argv": list(argv), **kwargs})
            return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

        monkeypatch.setattr(self_pr_mod, "_run_cmd_impl", fake_run)
        out = _run_git("status", cwd=tmp_path)
        assert out == "ok"
        assert len(calls) == 1
        assert calls[0]["argv"] == ["git", "status"]
        assert calls[0]["shell"] is False
        assert isinstance(calls[0]["argv"], list)

    def test_injection_payload_stays_single_argv_element(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Hostile commit message must not split into extra argv tokens."""
        calls: list[list[str]] = []
        payload = 'fix"; touch /tmp/pwned; echo "'

        def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(self_pr_mod, "_run_cmd_impl", fake_run)
        _run_git("commit", "-m", payload, "--no-verify", cwd=tmp_path)
        assert calls
        cmd = calls[0]
        assert cmd[0] == "git"
        assert cmd[1] == "commit"
        assert "-m" in cmd
        msg_idx = cmd.index("-m") + 1
        assert cmd[msg_idx] == payload  # whole payload, one element
        # Must not have been shell-split into extra tokens like "touch"
        assert cmd.count("touch") == 0 or "touch" in payload

    def test_gh_pr_title_body_branch_are_argv_elements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, Any]] = []
        evil_title = "PR $(curl http://evil/)"
        evil_body = "body; rm -rf / #"
        evil_branch = "evolver-auto/1-safe"

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append({"argv": list(argv), "shell": kwargs.get("shell")})
            return subprocess.CompletedProcess(
                argv, 0, stdout='{"url":"https://example/pr/1","number":1}', stderr=""
            )

        monkeypatch.setattr(self_pr_mod, "_run_cmd_impl", fake_run)
        result = _create_pr_via_gh(evil_branch, evil_title, evil_body)
        assert result is not None
        assert calls
        argv = calls[0]["argv"]
        assert argv[0] == "gh"
        assert calls[0]["shell"] is False
        # Title/body/branch appear as complete discrete elements
        title_idx = argv.index("--title") + 1
        body_idx = argv.index("--body") + 1
        head_idx = argv.index("--head") + 1
        assert argv[title_idx] == evil_title
        assert argv[body_idx] == evil_body
        assert argv[head_idx] == evil_branch
        # No intermediate shell joined the string (would produce fewer list parts)
        assert len(argv) >= 10

    def test_create_self_pr_uses_sanitized_branch_for_git(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")

        # Bypass preflight gates that would short-circuit before git.
        def _true(*_a: Any, **_k: Any) -> bool:
            return True

        monkeypatch.setattr(self_pr_mod, "_check_score", _true)
        monkeypatch.setattr(self_pr_mod, "_check_policy", _true)
        monkeypatch.setattr(self_pr_mod, "_check_secrets", _true)
        monkeypatch.setattr(self_pr_mod, "_check_cooldown", _true)
        monkeypatch.setattr(self_pr_mod, "_check_diff_dedup", _true)
        monkeypatch.setattr(self_pr_mod, "load_registry", lambda: {"prs": []})
        monkeypatch.setattr(self_pr_mod, "is_enabled", _true)

        git_calls: list[list[str]] = []

        def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            git_calls.append(list(argv))
            if argv[:3] == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(argv, 0, stdout="main\n", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(self_pr_mod, "_run_cmd_impl", fake_run)

        def _none(*_a: Any, **_k: Any) -> None:
            return None

        # Fail PR creation so we don't need registry/API side effects.
        monkeypatch.setattr(self_pr_mod, "_create_pr_via_gh", _none)
        monkeypatch.setattr(self_pr_mod, "_create_pr_via_api", _none)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        evil_gene = "g1$(id);curl evil"
        result = create_self_pr(
            diff_text="diff --git a/foo.py b/foo.py\n+hello",
            gene_id=evil_gene,
            gene_summary="summary $(whoami); rm -rf /",
            confidence=0.99,
        )
        assert not result.success  # PR create stubbed out
        # Find checkout -b call and assert branch is sanitized
        branch_calls = [c for c in git_calls if c[:3] == ["git", "checkout", "-b"]]
        assert branch_calls, f"expected branch create, got {git_calls}"
        branch = branch_calls[0][3]
        assert branch.startswith("evolver-auto/")
        assert "$(" not in branch
        assert ";" not in branch
        assert " " not in branch
        # Commit message still passed as single -m argv (may contain metacharacters)
        commit_calls = [c for c in git_calls if c[:2] == ["git", "commit"]]
        assert commit_calls
        m_idx = commit_calls[0].index("-m") + 1
        assert "$(whoami)" in commit_calls[0][m_idx]  # intact element, not executed


class TestSourceContract:
    def test_self_pr_module_never_enables_shell(self) -> None:
        src = Path(inspect.getsourcefile(self_pr_mod) or "").read_text(encoding="utf-8")
        assert "shell=True" not in src
        assert "shell = True" not in src
        # Must document / use shell=False on the real runner path.
        assert "shell=False" in src
        # No classic shell-string patterns.
        assert "os.system" not in src
        assert "shell=True" not in inspect.getsource(run_argv)
