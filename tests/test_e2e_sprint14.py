"""End-to-end tests for Sprint 14 surfaces (timeout, force_update, reuse, self_pr, TLS).

These cross multiple modules with realistic fixtures (isolated workspace, respx Hub
mocks, injectable git/gh runners) rather than pure unit stubs.
"""

from __future__ import annotations

import asyncio
import errno
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

import evolver.force_update as fu
import evolver.gep.self_pr as self_pr_mod
from evolver.atp import client as atp_client
from evolver.atp import hub_client
from evolver.cli import main
from evolver.config import enforce_hub_scheme
from evolver.evolve import runner
from evolver.evolve.pipeline.dispatch import _write_solidify_state
from evolver.gep import a2a_protocol, hub_fetch
from evolver.gep import asset_call_log as acl
from evolver.gep import memory_graph as mg
from evolver.gep.paths import get_cycle_progress_path, get_solidify_state_path
from evolver.gep.reuse_attribution import REUSE_ATTR_SCHEMA
from evolver.gep.self_pr import create_self_pr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fully isolated evolver workspace for E2E flows."""
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "memory" / "evolution"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / ".evolver" / "gep"))
    monkeypatch.setenv("EVOLVER_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("EVOLVER_SETTINGS_DIR", str(tmp_path / ".evolver_settings"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_PROGRESS_UPDATE_MS", "500")
    monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
    monkeypatch.delenv("EVOLVER_REUSE_ATTRIBUTION", raising=False)
    monkeypatch.delenv("EVOLVER_OUTCOME_REPORT", raising=False)
    monkeypatch.setenv("A2A_HUB_URL", "https://hub.e2e.test")
    (tmp_path / "memory" / "evolution").mkdir(parents=True)
    (tmp_path / ".evolver" / "gep").mkdir(parents=True)
    yield tmp_path


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "e2e@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "E2E"],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# 1. Full CLI run → solidify state attribution surface
# ---------------------------------------------------------------------------


class TestE2ERunDispatchAttribution:
    def test_cli_run_writes_source_type_and_created_at(self, e2e_env: Path) -> None:
        code = main(["run"])
        assert code == 0
        state = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
        last_run = state["last_run"]
        assert last_run.get("run_id")
        assert last_run.get("source_type") in ("generated", "reused", "reference")
        assert last_run.get("created_at")
        # ISO-ish timestamp with Z or offset
        assert re.search(r"\d{4}-\d{2}-\d{2}T", str(last_run["created_at"]))

    def test_dispatch_reused_hub_hit_propagates_to_solidify_state(self, e2e_env: Path) -> None:
        ctx: dict[str, Any] = {
            "run_id": "run_e2e_reuse",
            "signals": ["log_error"],
            "selected_gene": {"id": "gene_repair"},
            "hub_hit": {
                "id": "sha256:e2easset",
                "chain_id": "chain_e2e",
            },
            "source_type": "reused",
            "reused_asset_id": "sha256:e2easset",
            "reused_chain_id": "chain_e2e",
        }
        _write_solidify_state(ctx)
        last_run = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))["last_run"]
        assert last_run["source_type"] == "reused"
        assert last_run["reused_asset_id"] == "sha256:e2easset"
        assert last_run["reused_chain_id"] == "chain_e2e"
        assert last_run["created_at"]


# ---------------------------------------------------------------------------
# 2. Run attempt → outcome with shadow attribution + Hub report
# ---------------------------------------------------------------------------


class TestE2EReuseAttributionPipeline:
    def test_shadow_outcome_attaches_block_without_source_node_id(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        # Simulate same-cycle attempt + dispatch last_run.
        mg.record_attempt(
            signals=["log_error"],
            selected_gene={"id": "g_e2e"},
            run_id="run_attr",
        )
        # Write solidify last_run after attempt (pipeline order: attempt → dispatch → outcome)
        action_state_path = e2e_env / "memory" / "evolution" / "memory_graph_state.json"
        action = json.loads(action_state_path.read_text(encoding="utf-8"))["last_action"]
        act_ts = action.get("created_at") or action.get("ts")
        solidify = {
            "last_run": {
                "run_id": "run_attr",
                "source_type": "reused",
                "reused_asset_id": "sha256:attr",
                "reused_chain_id": "c1",
                "reused_source_node": "node_PAYEE_DO_NOT_TRUST",
                "created_at": act_ts,  # same cycle (not stale)
            }
        }
        # Use a slightly later timestamp so created_at >= last_action
        later = (
            (datetime.fromisoformat(str(act_ts).replace("Z", "+00:00")) + timedelta(seconds=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        solidify["last_run"]["created_at"] = later
        get_solidify_state_path().write_text(json.dumps(solidify), encoding="utf-8")

        event = mg.record_outcome_from_state(signals=[], observations=None)
        assert event is not None
        attr = event.get("reuse_attribution")
        assert isinstance(attr, dict)
        assert attr["schema"] == REUSE_ATTR_SCHEMA
        assert attr["reused_asset_id"] == "sha256:attr"
        assert attr["source_type"] == "reused"
        assert "source_node_id" not in attr
        assert "node_PAYEE_DO_NOT_TRUST" not in json.dumps(event)

        # Event persisted in memory graph
        events = mg.try_read_memory_graph_events(limit=50)
        outcomes = [e for e in events if e.get("kind") == "outcome"]
        assert outcomes
        assert any(e.get("reuse_attribution") for e in outcomes)

    @respx.mock
    def test_outcome_report_posts_on_full_pipeline(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", "on")
        monkeypatch.setenv("A2A_HUB_URL", "https://hub.e2e.test")
        monkeypatch.setenv("A2A_NODE_SECRET", "secret_e2e_token")
        monkeypatch.setattr(
            "evolver.gep.node_identity.get_or_create_node_id",
            lambda: "node_deadbeefcafe",
        )
        route = respx.post("https://hub.e2e.test/a2a/memory/record").mock(
            return_value=httpx.Response(200, json={"recorded": True})
        )

        mg.record_attempt(signals=["log_error"], selected_gene={"id": "g1"})
        action = json.loads(
            (e2e_env / "memory" / "evolution" / "memory_graph_state.json").read_text(
                encoding="utf-8"
            )
        )["last_action"]
        act_ts = action.get("created_at") or action.get("ts")
        later = (
            (datetime.fromisoformat(str(act_ts).replace("Z", "+00:00")) + timedelta(seconds=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        get_solidify_state_path().write_text(
            json.dumps(
                {
                    "last_run": {
                        "source_type": "reused",
                        "reused_asset_id": "sha256:post",
                        "created_at": later,
                    }
                }
            ),
            encoding="utf-8",
        )
        mg.record_outcome_from_state(signals=[], observations=None)
        assert route.called
        body = json.loads(route.calls.last.request.content.decode())
        assert body["used_asset_ids"] == ["sha256:post"]
        assert body["sender_id"] == "node_deadbeefcafe"
        assert "event" not in body
        assert route.calls.last.request.headers["Authorization"] == "Bearer secret_e2e_token"

    def test_local_rollup_after_pipeline_logs(self, e2e_env: Path) -> None:
        acl.log_asset_call(
            {
                "run_id": "r1",
                "action": "asset_reuse",
                "asset_id": "sha256:A",
                "tokens_saved": 100,
            }
        )
        acl.log_asset_call(
            {
                "run_id": "r2",
                "action": "asset_reference",
                "asset_id": "sha256:B",
                "tokens_saved": 50,
            }
        )
        summary = acl.reuse_attribution_summary()
        assert summary["total_reuse"] == 1
        assert summary["total_reference"] == 1
        assert summary["total_tokens_saved"] == 150

    def test_stale_last_run_does_not_attach_attribution(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        mg.record_attempt(signals=["log_error"], selected_gene={"id": "g_stale"})
        action = json.loads(
            (e2e_env / "memory" / "evolution" / "memory_graph_state.json").read_text(
                encoding="utf-8"
            )
        )["last_action"]
        act_ts = action.get("created_at") or action.get("ts")
        earlier = (
            (datetime.fromisoformat(str(act_ts).replace("Z", "+00:00")) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        get_solidify_state_path().write_text(
            json.dumps(
                {
                    "last_run": {
                        "source_type": "reused",
                        "reused_asset_id": "sha256:STALE",
                        "created_at": earlier,
                    }
                }
            ),
            encoding="utf-8",
        )
        event = mg.record_outcome_from_state(signals=[], observations=None)
        assert event is not None
        assert "reuse_attribution" not in event
        assert "STALE" not in json.dumps(event)

    def test_off_mode_skips_attribution_even_on_reuse(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOLVER_REUSE_ATTRIBUTION", raising=False)
        mg.record_attempt(signals=["log_error"], selected_gene={"id": "g_off"})
        action = json.loads(
            (e2e_env / "memory" / "evolution" / "memory_graph_state.json").read_text(
                encoding="utf-8"
            )
        )["last_action"]
        act_ts = action.get("created_at") or action.get("ts")
        later = (
            (datetime.fromisoformat(str(act_ts).replace("Z", "+00:00")) + timedelta(seconds=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        get_solidify_state_path().write_text(
            json.dumps(
                {
                    "last_run": {
                        "source_type": "reused",
                        "reused_asset_id": "sha256:off",
                        "created_at": later,
                    }
                }
            ),
            encoding="utf-8",
        )
        event = mg.record_outcome_from_state(signals=[], observations=None)
        assert event is not None
        assert "reuse_attribution" not in event


# ---------------------------------------------------------------------------
# 3. TLS consistency across clients (E2E)
# ---------------------------------------------------------------------------


class TestE2ETlsConsistency:
    def test_cli_clients_refuse_http_hub(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        monkeypatch.setenv("A2A_HUB_URL", "http://insecure.e2e")
        with pytest.raises(ValueError, match=r"(?i)must use https|tls_refused"):
            enforce_hub_scheme("http://insecure.e2e/v1/a2a/hello")
        with pytest.raises(ValueError, match=r"(?i)must use https"):
            hub_fetch.hub_fetch("http://insecure.e2e/v1/a2a/hello")

    @pytest.mark.asyncio
    async def test_atp_and_hub_client_refuse_http(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        buy = await atp_client.buy("skill", hub_url="http://hub.e2e")
        assert buy["ok"] is False
        assert buy.get("stage") == "tls"

        monkeypatch.setenv("A2A_HUB_URL", "http://hub.e2e")
        order = await hub_client.place_order("svc", budget=1.0)
        assert order["ok"] is False
        assert order.get("stage") == "tls" or "https" in str(order.get("error", "")).lower()

    def test_a2a_envelope_refuses_http_override(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        res = a2a_protocol.post_hub_envelope(
            "/v1/a2a/hello",
            {"type": "hello"},
            hub_url="http://hub.e2e",
        )
        assert res["ok"] is False
        assert (res.get("body") or {}).get("error") == "tls_refused"

    @respx.mock
    def test_https_hub_fetch_reaches_network(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOMAP_HUB_ALLOW_INSECURE", raising=False)
        hub_fetch.reset_circuit_breaker()
        hub_fetch.clear_cache()
        route = respx.get("https://hub.e2e.test/v1/a2a/hello").mock(
            return_value=httpx.Response(200, json={"ok": True, "node": "n1"})
        )
        data = hub_fetch.hub_fetch(
            "https://hub.e2e.test/v1/a2a/hello",
            method="GET",
            use_cache=False,
            max_retries=0,
        )
        assert route.called
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# 4. Force-update keep-list + mid-copy self-heal (E2E install path)
# ---------------------------------------------------------------------------


class TestE2EForceUpdateInstall:
    def test_install_preserves_local_state_and_replaces_code(self, e2e_env: Path) -> None:
        install = e2e_env / "install"
        download = e2e_env / "download"
        install.mkdir()
        download.mkdir()
        # Old install with keep-list + code
        (install / "package.json").write_text(
            json.dumps({"name": "@evomap/evolver", "version": "1.0.0"}), encoding="utf-8"
        )
        (install / "index.js").write_text("// old", encoding="utf-8")
        (install / "src").mkdir()
        (install / "src" / "evolve.js").write_text("// old", encoding="utf-8")
        (install / ".env").write_text("SECRET=local\n", encoding="utf-8")
        (install / "USER.md").write_text("mine", encoding="utf-8")
        (install / "memory").mkdir()
        (install / "memory" / "state.json").write_text('{"keep":true}', encoding="utf-8")
        (install / "logs").mkdir()
        (install / "logs" / "evolver.log").write_text("local\n", encoding="utf-8")

        (download / "package.json").write_text(
            json.dumps({"name": "@evomap/evolver", "version": "2.0.0"}), encoding="utf-8"
        )
        (download / "index.js").write_text("// v2.0.0", encoding="utf-8")
        (download / "src").mkdir()
        (download / "src" / "evolve.js").write_text("// src v2.0.0", encoding="utf-8")
        (download / ".env").write_text("SECRET=from-release\n", encoding="utf-8")

        result = fu.install_downloaded_tree(install, download, required_version="2.0.0")
        assert result.get("ok") is True or result.get("success") is True
        assert (install / ".env").read_text(encoding="utf-8") == "SECRET=local\n"
        assert (install / "USER.md").read_text(encoding="utf-8") == "mine"
        assert (install / "memory" / "state.json").read_text(encoding="utf-8") == '{"keep":true}'
        assert (install / "logs" / "evolver.log").read_text(encoding="utf-8") == "local\n"
        assert (install / "index.js").read_text(encoding="utf-8") == "// v2.0.0"
        assert (
            json.loads((install / "package.json").read_text(encoding="utf-8"))["version"] == "2.0.0"
        )

    def test_mid_copy_failure_then_retry_self_heals(self, e2e_env: Path) -> None:
        install = e2e_env / "install"
        download = e2e_env / "download"
        install.mkdir()
        download.mkdir()
        (install / "package.json").write_text(
            json.dumps({"name": "@evomap/evolver", "version": "1.0.0"}), encoding="utf-8"
        )
        (install / "index.js").write_text("// old", encoding="utf-8")
        (install / "src").mkdir()
        (install / "src" / "evolve.js").write_text("// old", encoding="utf-8")
        (download / "package.json").write_text(
            json.dumps({"name": "@evomap/evolver", "version": "2.0.0"}), encoding="utf-8"
        )
        (download / "index.js").write_text("// v2", encoding="utf-8")
        (download / "src").mkdir()
        (download / "src" / "evolve.js").write_text("// src v2", encoding="utf-8")

        real_copy = shutil.copytree
        fail_once = {"n": 0}

        def boom_once(src: Path, dst: Path) -> None:
            if Path(src).name == "src" and fail_once["n"] == 0:
                fail_once["n"] += 1
                raise OSError(errno.ENOSPC, "no space")
            if Path(dst).exists():
                shutil.rmtree(dst)
            real_copy(src, dst)

        fu._copy_tree_fn = boom_once  # type: ignore[assignment]
        try:
            first = fu.install_downloaded_tree(install, download, required_version="2.0.0")
            assert fu.is_force_update_failure(first)
            assert (
                json.loads((install / "package.json").read_text(encoding="utf-8"))["version"]
                == "1.0.0"
            )
            # Rebuild download if consumed
            if not download.exists():
                download.mkdir()
                (download / "package.json").write_text(
                    json.dumps({"name": "@evomap/evolver", "version": "2.0.0"}),
                    encoding="utf-8",
                )
                (download / "index.js").write_text("// v2", encoding="utf-8")
                (download / "src").mkdir()
                (download / "src" / "evolve.js").write_text("// src v2", encoding="utf-8")
            fu._copy_tree_fn = None
            second = fu.install_downloaded_tree(install, download, required_version="2.0.0")
        finally:
            fu._copy_tree_fn = None

        assert second.get("ok") is True or second.get("success") is True
        assert (
            json.loads((install / "package.json").read_text(encoding="utf-8"))["version"] == "2.0.0"
        )


# ---------------------------------------------------------------------------
# 5. Self-PR injection-safe full path (E2E)
# ---------------------------------------------------------------------------


class TestE2ESelfPrInjection:
    def test_create_self_pr_sanitizes_branch_and_uses_argv(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SELF_PR", "1")
        monkeypatch.setattr(self_pr_mod, "is_enabled", lambda *_a, **_k: True)
        monkeypatch.setattr(self_pr_mod, "_check_score", lambda *_a, **_k: True)
        monkeypatch.setattr(self_pr_mod, "_check_policy", lambda *_a, **_k: True)
        monkeypatch.setattr(self_pr_mod, "_check_secrets", lambda *_a, **_k: True)
        monkeypatch.setattr(self_pr_mod, "_check_cooldown", lambda *_a, **_k: True)
        monkeypatch.setattr(self_pr_mod, "_check_diff_dedup", lambda *_a, **_k: True)
        monkeypatch.setattr(self_pr_mod, "load_registry", lambda: {"prs": []})
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        git_calls: list[list[str]] = []
        gh_calls: list[list[str]] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            assert kwargs.get("shell") is False
            assert isinstance(argv, list)
            if argv and argv[0] == "gh":
                gh_calls.append(list(argv))
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout='{"url":"https://github.com/o/r/pull/1","number":1}',
                    stderr="",
                )
            git_calls.append(list(argv))
            if argv[:3] == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(argv, 0, stdout="main\n", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(self_pr_mod, "_run_cmd_impl", fake_run)
        monkeypatch.setattr(
            self_pr_mod,
            "register_pr",
            lambda **_k: None,
        )

        evil_gene = "g1$(curl evil);rm -rf /"
        evil_summary = 'fix"; touch /tmp/pwned #'
        result = create_self_pr(
            diff_text="diff --git a/foo.py b/foo.py\n+safe",
            gene_id=evil_gene,
            gene_summary=evil_summary,
            confidence=0.99,
        )
        assert result.success is True
        # Branch sanitized
        checkout = [c for c in git_calls if c[:3] == ["git", "checkout", "-b"]]
        assert checkout
        branch = checkout[0][3]
        assert "$(" not in branch
        assert ";" not in branch
        assert " " not in branch
        # Commit message is single -m element (may contain metacharacters intact)
        commits = [c for c in git_calls if c[:2] == ["git", "commit"]]
        assert commits
        m_idx = commits[0].index("-m") + 1
        assert commits[0][m_idx] == evil_summary
        # gh pr create got title as single argv
        assert gh_calls
        title_idx = gh_calls[0].index("--title") + 1
        assert "$(curl" not in " ".join(gh_calls[0]) or evil_summary[:20] in gh_calls[0][title_idx]
        assert gh_calls[0][title_idx].startswith("[evolver-auto]")


# ---------------------------------------------------------------------------
# 6. Cycle hard-timeout + progress file via runner
# ---------------------------------------------------------------------------


class TestE2ECycleTimeoutAndProgress:
    @pytest.mark.asyncio
    async def test_run_writes_solidify_state(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_PROGRESS_UPDATE_MS", "200")
        await runner.run()
        assert get_solidify_state_path().exists()

    @pytest.mark.asyncio
    async def test_loop_hard_timeout_continue_path(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_CYCLE_TIMEOUT_MS", "80")
        monkeypatch.setenv("EVOLVER_SUICIDE", "0")  # continue, don't respawn
        monkeypatch.setenv("EVOLVER_PROGRESS_UPDATE_MS", "50")
        # Final is import-time — patch the runner binding, not only the env var.
        monkeypatch.setattr(runner, "MAX_CYCLES_PER_PROCESS", 1)

        calls = {"n": 0}

        async def slow_cycle(*, is_loop: bool = False) -> dict[str, Any]:
            calls["n"] += 1
            await asyncio.sleep(0.2)
            return {"bridge_enabled": False}

        monkeypatch.setattr(runner, "_run_single_cycle", slow_cycle)
        runner._shutdown_requested = False
        runner._shutdown_event = None

        # Timeout → continue → await timed-out task → max cycles breaks loop.
        await asyncio.wait_for(runner.run_loop(interval_ms=10), timeout=5.0)

        progress = get_cycle_progress_path()
        assert progress.exists()
        data = json.loads(progress.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "phase" in data or "outer_cycle" in data or "pid" in data
        assert calls["n"] >= 1


# ---------------------------------------------------------------------------
# 7. Full run + solidify + memory graph outcome chain
# ---------------------------------------------------------------------------


class TestE2ERunSolidifyMemoryChain:
    def test_run_solidify_then_record_outcome(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_git(e2e_env)
        monkeypatch.setenv("EVOLVER_REUSE_ATTRIBUTION", "shadow")
        assert main(["run"]) == 0
        assert main(["solidify"]) == 0

        solidify = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
        assert solidify.get("last_solidify") or solidify.get("last_run")

        # Seed last_action for outcome correlation
        gene_id = (solidify.get("last_run") or {}).get("selected_gene_id") or "g_seed"
        mg.record_attempt(
            signals=["log_error"],
            selected_gene={"id": gene_id},
            run_id=(solidify.get("last_run") or {}).get("run_id"),
        )
        # Align last_run created_at with attempt for attribution window
        action = json.loads(
            (e2e_env / "memory" / "evolution" / "memory_graph_state.json").read_text(
                encoding="utf-8"
            )
        )["last_action"]
        act_ts = action.get("created_at") or action.get("ts")
        later = (
            (datetime.fromisoformat(str(act_ts).replace("Z", "+00:00")) + timedelta(seconds=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        lr = dict(solidify.get("last_run") or {})
        lr.update(
            {
                "source_type": "generated",
                "created_at": later,
            }
        )
        solidify["last_run"] = lr
        get_solidify_state_path().write_text(json.dumps(solidify), encoding="utf-8")

        event = mg.record_outcome_from_state(signals=[], observations=None)
        assert event is not None
        assert event.get("kind") == "outcome"
        # generated → no attribution block
        assert "reuse_attribution" not in event or event.get("reuse_attribution") is None

        events = mg.try_read_memory_graph_events(limit=100)
        kinds = {e.get("kind") for e in events}
        assert "attempt" in kinds
        assert "outcome" in kinds


# ---------------------------------------------------------------------------
# 8. CLI check / health after run (smoke E2E)
# ---------------------------------------------------------------------------


class TestE2ECliSmoke:
    def test_check_after_run(self, e2e_env: Path) -> None:
        assert main(["run"]) == 0
        # check may return non-zero on some platforms; ensure it does not crash
        code = main(["check"])
        assert code in (0, 1)

    def test_self_report_after_run(self, e2e_env: Path) -> None:
        assert main(["run"]) == 0
        code = main(["self-report", "--no-write"])
        assert code == 0

    def test_run_twice_updates_solidify_run_id(self, e2e_env: Path) -> None:
        assert main(["run"]) == 0
        first = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))["last_run"][
            "run_id"
        ]
        assert main(["run"]) == 0
        second = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))["last_run"][
            "run_id"
        ]
        assert first != second
        assert str(first).startswith("run_")
        assert str(second).startswith("run_")


class TestE2EApplyUpdateKeepList:
    def test_apply_update_staging_respects_keep_list(self, e2e_env: Path) -> None:
        target = e2e_env / "tgt"
        source = e2e_env / "src"
        target.mkdir()
        source.mkdir()
        (target / ".env").write_text("LOCAL=1\n", encoding="utf-8")
        (target / "USER.md").write_text("notes", encoding="utf-8")
        (target / "code.py").write_text("old", encoding="utf-8")
        (source / ".env").write_text("RELEASE=1\n", encoding="utf-8")
        (source / "code.py").write_text("new", encoding="utf-8")
        (source / "extra.py").write_text("x", encoding="utf-8")
        result = fu.apply_update(source, target)
        assert result["success"] is True
        assert (target / ".env").read_text(encoding="utf-8") == "LOCAL=1\n"
        assert (target / "USER.md").read_text(encoding="utf-8") == "notes"
        assert (target / "code.py").read_text(encoding="utf-8") == "new"
        assert (target / "extra.py").read_text(encoding="utf-8") == "x"


class TestE2EInsecureBypass:
    @respx.mock
    def test_allow_insecure_permits_http_hub_fetch(
        self, e2e_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
        hub_fetch.reset_circuit_breaker()
        hub_fetch.clear_cache()
        route = respx.get("http://localhost:19998/v1/a2a/hello").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        data = hub_fetch.hub_fetch(
            "http://localhost:19998/v1/a2a/hello",
            use_cache=False,
            max_retries=0,
        )
        assert route.called
        assert data["ok"] is True
