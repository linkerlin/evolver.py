"""Sprint 16.2 — WebUI GitHub observer (ports webuiGithubObserver.test.js)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from evolver.webui.observer import github as gh
from evolver.webui.server.routes import router


GH_PR_319 = {
    "number": 319,
    "title": "refactor(proxy): centralize session payload validation",
    "state": "MERGED",
    "isDraft": False,
    "author": {"login": "autogame-17", "name": ""},
    "additions": 457,
    "deletions": 117,
    "changedFiles": 7,
    "createdAt": "2026-07-09T14:44:56Z",
    "updatedAt": "2026-07-09T14:53:44Z",
    "mergedAt": "2026-07-09T14:53:44Z",
    "closedAt": "2026-07-09T14:53:44Z",
    "url": "https://github.com/EvoMap/evolver-private-dev/pull/319",
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_WEBUI_GITHUB", raising=False)
    monkeypatch.setenv("EVOLVER_GITHUB_REPO", "EvoMap/evolver-private-dev")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    gh.reset_for_testing()


class TestNormalizeHelpers:
    def test_normalize_number(self) -> None:
        assert gh.normalize_number("319") == 319
        assert gh.normalize_number(319) == 319
        assert gh.normalize_number("0") is None
        assert gh.normalize_number("-1") is None
        assert gh.normalize_number("3a") is None
        assert gh.normalize_number("3.5") is None
        assert gh.normalize_number("") is None
        assert gh.normalize_number(None) is None
        assert gh.normalize_number(int("9" * 23)) is None
        assert gh.normalize_number("9" * 23) is None
        max_safe = (1 << 53) - 1
        assert gh.normalize_number(max_safe) == max_safe
        assert gh.normalize_number(max_safe + 1) is None

    def test_normalize_state(self) -> None:
        assert gh.normalize_state("MERGED", False, "2026-07-09") == "merged"
        assert gh.normalize_state("open", False, "2026-07-09") == "merged"
        assert gh.normalize_state("OPEN", True, None) == "draft"
        assert gh.normalize_state("CLOSED", False, None) == "closed"
        assert gh.normalize_state("open", False, None) == "open"

    def test_parse_slug_from_remote(self) -> None:
        assert (
            gh.parse_slug_from_remote("https://github.com/EvoMap/evolver-private-dev.git")
            == "EvoMap/evolver-private-dev"
        )
        assert gh.parse_slug_from_remote("git@github.com:EvoMap/evolver.git") == "EvoMap/evolver"
        assert gh.parse_slug_from_remote("https://gitlab.com/x/y.git") is None

    def test_get_repo_info(self) -> None:
        info = gh.get_repo_info()
        assert info["available"] is True
        assert info["slug"] == "EvoMap/evolver-private-dev"
        assert info["prUrlBase"] == "https://github.com/EvoMap/evolver-private-dev/pull"


class TestGhPath:
    def test_normalizes_gh_pr_view_json(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps(GH_PR_319)
        with patch("subprocess.run", return_value=completed) as run:
            pr = gh.get_pr_status(319)
        assert pr["available"] is True
        assert pr["source"] == "gh"
        assert pr["number"] == 319
        assert pr["state"] == "merged"
        assert pr["author"] == "autogame-17"
        assert pr["additions"] == 457
        assert pr["deletions"] == 117
        assert pr["changedFiles"] == 7
        assert pr["url"] == GH_PR_319["url"]
        args = run.call_args[0][0]
        assert args[:3] == ["gh", "pr", "view"]
        assert args[3] == "319"

    def test_caches_within_ttl(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps(GH_PR_319)
        with patch("subprocess.run", return_value=completed) as run:
            gh.get_pr_status(319)
            gh.get_pr_status(319)
        assert run.call_count == 1

    def test_rejects_non_integer(self) -> None:
        with patch("subprocess.run") as run:
            bad = gh.get_pr_status("3; rm -rf /")
        assert bad["available"] is False
        assert bad["reason"] == "invalid_number"
        run.assert_not_called()

    def test_feature_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_WEBUI_GITHUB", "0")
        with patch("subprocess.run") as run:
            res = gh.get_pr_status(319)
        assert res["available"] is False
        assert res["reason"] == "feature_disabled"
        run.assert_not_called()


class TestRestFallback:
    def _gh_missing(self) -> Any:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise FileNotFoundError("spawn gh ENOENT")

        return _raise

    def test_falls_back_to_rest(self) -> None:
        api_body = {
            "number": 596,
            "title": "public sibling PR",
            "state": "open",
            "draft": False,
            "merged_at": None,
            "user": {"login": "octocat"},
            "additions": 10,
            "deletions": 2,
            "changed_files": 3,
            "created_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-02T00:00:00Z",
            "closed_at": None,
            "html_url": "https://github.com/EvoMap/evolver/pull/596",
        }
        mock_resp = httpx.Response(200, json=api_body)
        with (
            patch("subprocess.run", side_effect=self._gh_missing()),
            patch("httpx.Client") as client_cls,
        ):
            client = MagicMock()
            client.__enter__ = MagicMock(return_value=client)
            client.__exit__ = MagicMock(return_value=False)
            client.get.return_value = mock_resp
            client_cls.return_value = client
            pr = gh.get_pr_status(596)
        assert pr["available"] is True
        assert pr["source"] == "api"
        assert pr["state"] == "open"
        assert pr["author"] == "octocat"
        assert pr["changedFiles"] == 3
        assert pr["url"] == "https://github.com/EvoMap/evolver/pull/596"
        called_url = client.get.call_args[0][0]
        assert "/repos/EvoMap/evolver-private-dev/pulls/596" in called_url

    def test_not_found(self) -> None:
        mock_resp = httpx.Response(404, json={"message": "Not Found"})
        with (
            patch("subprocess.run", side_effect=self._gh_missing()),
            patch("httpx.Client") as client_cls,
        ):
            client = MagicMock()
            client.__enter__ = MagicMock(return_value=client)
            client.__exit__ = MagicMock(return_value=False)
            client.get.return_value = mock_resp
            client_cls.return_value = client
            pr = gh.get_pr_status(999999)
        assert pr["available"] is False
        assert pr["reason"] == "not_found"

    def test_rate_limited(self) -> None:
        mock_resp = httpx.Response(403, json={"message": "rate limit"})
        with (
            patch("subprocess.run", side_effect=self._gh_missing()),
            patch("httpx.Client") as client_cls,
        ):
            client = MagicMock()
            client.__enter__ = MagicMock(return_value=client)
            client.__exit__ = MagicMock(return_value=False)
            client.get.return_value = mock_resp
            client_cls.return_value = client
            pr = gh.get_pr_status(5)
        assert pr["available"] is False
        assert pr["reason"] == "rate_limited"

    def test_network_error(self) -> None:
        with (
            patch("subprocess.run", side_effect=self._gh_missing()),
            patch("httpx.Client") as client_cls,
        ):
            client = MagicMock()
            client.__enter__ = MagicMock(return_value=client)
            client.__exit__ = MagicMock(return_value=False)
            client.get.side_effect = httpx.ConnectError("ECONNRESET")
            client_cls.return_value = client
            pr = gh.get_pr_status(5)
        assert pr["available"] is False
        assert pr["reason"] == "network_error"

    def test_gh_nonzero_falls_through_to_rest(self) -> None:
        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "no pull requests found"
        mock_resp = httpx.Response(404, json={"message": "Not Found"})
        with (
            patch("subprocess.run", return_value=completed) as run,
            patch("httpx.Client") as client_cls,
        ):
            client = MagicMock()
            client.__enter__ = MagicMock(return_value=client)
            client.__exit__ = MagicMock(return_value=False)
            client.get.return_value = mock_resp
            client_cls.return_value = client
            pr = gh.get_pr_status(42)
        assert pr["available"] is False
        assert pr["reason"] == "not_found"
        assert run.call_count == 1
        assert client.get.call_count == 1


class TestApiRoutes:
    def test_github_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_GITHUB_REPO", "EvoMap/evolver-private-dev")
        gh.reset_for_testing()
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        res = client.get("/api/github/repo")
        assert res.status_code == 200
        assert res.json()["slug"] == "EvoMap/evolver-private-dev"

        res = client.get("/api/github/pr/not-a-number")
        assert res.status_code == 400
        assert res.json()["code"] == "INVALID_PR_NUMBER"

        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps(GH_PR_319)
        with patch("subprocess.run", return_value=completed):
            res = client.get("/api/github/pr/319")
        assert res.status_code == 200
        body = res.json()
        assert body["available"] is True
        assert body["number"] == 319
