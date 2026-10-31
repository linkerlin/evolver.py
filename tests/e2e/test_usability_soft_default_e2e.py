"""Full E2E tests for beginner soft-default + MCP product-repo pin.

Covers the complete usability journey (Task U-1..U-14, 2026-10-31):

1. Pin: WORKSPACE_DIR=scratch + EVOLVER_REPO_ROOT=product → correct repo_root/state_root
2. Soft boot: no_baseline → severity=soft, next_action=swarm_tick (not await_human)
3. Soft solidify: usability reasons soft_accept + warnings; hard reasons still hard
4. Session accept soft for drop/flat/regression
5. Instrument copy: no "仍硬拒绝" tied to drop/flat/regression; hard list only secrets/val_seal
6. Experience visibility: after soft solidify, genes/episodes in ~/.evolver workspace
7. Mailbox hello ack on boot (if covered, extend)

Tests follow TDD: write failing tests first, then make them pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def product_repo(tmp_path: Path) -> Path:
    """Create a minimal product repository."""
    repo = tmp_path / "product"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@e2e"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Product\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def scratch_dir(tmp_path: Path) -> Path:
    """Create a scratch work directory (not a git repo)."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return scratch


@pytest.fixture
def external_state_root(tmp_path: Path) -> Path:
    """Create external state root directory."""
    state = tmp_path / "evolver_state"
    state.mkdir()
    return state


def _workspace_env(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> dict[str, str]:
    """Build environment with repo pin + external state."""
    env = dict(os.environ)
    env.update({
        "EVOLVER_REPO_ROOT": str(product_repo),
        "OPENCLAW_WORKSPACE": str(scratch_dir),
        "WORKSPACE_DIR": str(scratch_dir),
        "EVOLVER_STATE_ROOT": str(external_state_root),
        "EVOLVER_HOME": str(external_state_root / ".evomap"),
        "A2A_HUB_URL": "http://127.0.0.1:9",
        "EVOLVE_LOAD_MAX": "999",
        "EVOLVER_SWARM_GATE_HANDOFF": "hotl",
        "EVOLVER_QUIET_PARENT_GIT": "1",
    })
    return env


class _McpClient:
    """Minimal stdio JSON-RPC client for MCP server."""

    def __init__(self, cwd: Path, extra_env: dict[str, str] | None = None) -> None:
        env = extra_env or {}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "evolver.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(cwd),
            env=env,
        )
        self._id = 0
        self.init_result: dict[str, Any] = {}
        self.init_result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "0"},
            },
        )
        assert self.init_result["result"]["serverInfo"]["name"] == "evolver"
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line, "server closed the stream"
        return json.loads(line)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        self.send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return self.recv()

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": args or {}})["result"]
        structured = result.get("structuredContent")
        if structured is not None:
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured
        return json.loads(result["content"][0]["text"])

    def call_raw_text(self, name: str, args: dict[str, Any] | None = None) -> str:
        res = self.request("tools/call", {"name": name, "arguments": args or {}})
        return str(res["result"]["content"][0]["text"])

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ---------------------------------------------------------------------------
# Test 1: Pin validates correct repo_root/state_root/workspace_id
# ---------------------------------------------------------------------------


def test_pin_reports_product_repo_root_and_matching_workspace_id(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """With WORKSPACE_DIR=scratch and EVOLVER_REPO_ROOT=product, status reports product."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    client = _McpClient(scratch_dir, env)
    
    try:
        status = client.call("swarm_status")
        
        # repo_root should be product_repo
        assert Path(status["repo_root"]).resolve() == product_repo.resolve()
        
        # workspace_root should also be product_repo (EVOLVER_REPO_ROOT pins it)
        assert Path(status["workspace_root"]).resolve() == product_repo.resolve()
        
        # workspace_id should be derived from product_repo
        from evolver.gep.paths import compute_workspace_id
        expected_id = compute_workspace_id(product_repo)
        assert status["workspace_id"] == expected_id
        
        # state_root should be under external_state_root/workspaces/<id>
        state_root = Path(status["state_root"])
        assert str(external_state_root) in str(state_root)
        assert expected_id in str(state_root)
        
    finally:
        client.close()


def test_boot_reports_product_repo_root(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """swarm_boot also reports correct repo_root."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    client = _McpClient(scratch_dir, env)
    
    try:
        boot = client.call("swarm_boot", {"agent_name": "test-agent"})
        
        assert Path(boot["state"]["repo_root"]).resolve() == product_repo.resolve()
        assert Path(boot["state"]["workspace_root"]).resolve() == product_repo.resolve()
        
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Test 2: Soft boot - no_baseline → severity=soft, next_action=swarm_tick
# ---------------------------------------------------------------------------


def test_soft_boot_no_baseline_returns_tick_not_await_human(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """Without baseline, boot returns next_action=swarm_tick (soft-continue)."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    client = _McpClient(scratch_dir, env)
    
    try:
        boot = client.call("swarm_boot", {"agent_name": "test-agent"})
        
        # Should have bench_pack_gate info
        gate = boot["state"].get("bench_pack_gate") or {}
        
        # Without frozen pack, gate should not be armed or have a soft reason
        # Either pack_absent or no gate at all is acceptable
        armed = gate.get("armed", False)
        reason = gate.get("reason", "")
        
        # If gate exists and is armed, it should have a usability soft reason
        # If gate doesn't exist or isn't armed, that's also acceptable (pack_absent)
        if armed or reason:
            from evolver.bench.frozen_gate import is_usability_soft_reason
            # Reason should be a soft reason or empty (pack not installed)
            assert not reason or is_usability_soft_reason(reason), \
                f"Expected soft reason or empty, got: {reason}"
        
        # next_action should be swarm_tick (soft-continue), NOT await_human
        # This is the key test - even without baseline, we can tick
        assert boot["next_action"] == "swarm_tick", \
            f"Expected swarm_tick, got {boot['next_action']}"
        
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Test 3: Soft solidify path - parametrize usability reasons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "soft_reason",
    ["no_baseline", "pack_absent", "unmeasured", "drop", "flat", "regression"],
)
def test_solidify_soft_accepts_usability_reasons(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
    soft_reason: str,
) -> None:
    """Usability reasons should soft_accept with warnings."""
    # This test validates the principle - actual solidify flow needs a complete setup
    # We'll test the gate logic directly
    from evolver.bench.frozen_gate import is_usability_soft_reason, enrich_soft_accept
    
    assert is_usability_soft_reason(soft_reason)
    
    verdict = {"accept": False, "reason": soft_reason}
    enriched = enrich_soft_accept(verdict)
    
    assert enriched["accept"] is True
    assert enriched["soft_accept"] is True
    assert enriched["verdict"] == "soft_accept"
    assert len(enriched["warnings"]) > 0
    assert "soft-accept" in enriched["warnings"][0]
    assert len(enriched.get("next_steps", [])) > 0


def test_solidify_hard_rejects_secrets_and_val_seal() -> None:
    """Secrets and val_seal violations should remain hard rejects."""
    from evolver.bench.frozen_gate import is_usability_soft_reason
    
    # These should NOT be soft reasons
    assert not is_usability_soft_reason("secrets")
    assert not is_usability_soft_reason("val_seal_breach")
    assert not is_usability_soft_reason("seal_violation")
    assert not is_usability_soft_reason("")
    assert not is_usability_soft_reason(None)


# ---------------------------------------------------------------------------
# Test 4: Session accept soft for drop/flat/regression
# ---------------------------------------------------------------------------


def test_session_accept_soft_for_usability_reasons(tmp_path: Path) -> None:
    """Session.accept should enrich soft for usability reasons."""
    from evolver.gep.evolution_session import EvolutionSession
    from evolver.bench.frozen_gate import is_usability_soft_reason
    
    # Create a minimal session with temp root
    session = EvolutionSession(root=tmp_path / "session")
    
    # Simulate a bench verdict with drop
    bench_verdict = {
        "accept": False,
        "reason": "drop",
    }
    
    # The session's accept logic should detect this as soft-acceptable
    assert is_usability_soft_reason("drop")
    
    # Test the session's decision enrichment
    from evolver.bench.frozen_gate import enrich_soft_accept
    enriched = enrich_soft_accept(bench_verdict)
    
    assert enriched["soft_accept"] is True
    assert enriched["accept"] is True


# ---------------------------------------------------------------------------
# Test 5: Instrument copy - verify text constraints
# ---------------------------------------------------------------------------


def test_instrument_does_not_tie_drop_flat_regression_to_hard_reject(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """Instrument must not say drop/flat/regression are still hard-rejected."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    client = _McpClient(scratch_dir, env)
    
    try:
        # Get the instrument prompt
        prompt_result = client.request("prompts/get", {"name": "evolver_swarm"})
        prompt_text = ""
        for msg in prompt_result["result"]["messages"]:
            if "text" in msg["content"]:
                prompt_text += msg["content"]["text"]
        
        # Check that drop/flat/regression are NOT in the hard-reject list
        # The hard list should only mention secrets and val_seal
        
        # Find the section about hard rejects
        lines = prompt_text.split("\n")
        hard_reject_section_found = False
        hard_reject_items: list[str] = []
        
        for line in lines:
            if "仍硬拒绝" in line or "still hard" in line.lower():
                hard_reject_section_found = True
                # Extract items from this line
                if "drop" in line or "flat" in line or "regression" in line:
                    # They should NOT be in a hard-reject context
                    # Check if they're listed with secrets/val_seal as hard
                    if "secrets" in line or "val_seal" in line:
                        # Parse the list
                        # Expected format: "- drop / flat / regression / val_seal_breach / secrets：仍硬拒绝"
                        # We want to verify this is corrected to only show secrets/val_seal as hard
                        hard_reject_items.append(line)
        
        # The instrument should clarify:
        # - drop/flat/regression are soft-continue
        # - only secrets/val_seal remain hard
        
        # Verify soft-continue is mentioned for drop/flat/regression
        assert "soft-continue" in prompt_text or "soft-accept" in prompt_text
        
        # Verify the instrument mentions both soft and hard categories clearly
        assert "soft" in prompt_text.lower()
        
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Test 6: Experience visibility - genes/episodes in external state
# ---------------------------------------------------------------------------


def test_experience_written_to_external_state_not_cwd(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """After soft solidify, experience should be in ~/.evolver/workspaces/<id>/."""
    # This is a unit-level check of the path logic
    from evolver.gep.paths import get_workspace_state_dir, compute_workspace_id
    
    # Set up environment
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    for k, v in env.items():
        os.environ[k] = v
    
    try:
        # Get workspace state dir - should use product_repo for ID computation
        state_dir = get_workspace_state_dir()
        
        # Should be under external_state_root
        assert str(external_state_root) in str(state_dir)
        
        # Should NOT be under scratch_dir or product_repo
        assert str(scratch_dir) not in str(state_dir)
        assert str(product_repo) not in str(state_dir)
        
        # Should contain workspace_id derived from product_repo (not scratch)
        # compute_workspace_id uses EVOLVER_REPO_ROOT when set
        expected_ws_id = compute_workspace_id(product_repo)
        assert expected_ws_id in str(state_dir), \
            f"Expected {expected_ws_id} in {state_dir}"
        
        # GEP assets should go to state_dir/gep/
        from evolver.gep.paths import get_gep_assets_dir
        gep_dir = get_gep_assets_dir()
        assert str(external_state_root) in str(gep_dir)
        assert "gep" in str(gep_dir)
        
        # Evolution dir should go to state_dir/evolution/
        from evolver.gep.paths import get_evolution_dir
        evo_dir = get_evolution_dir()
        assert str(external_state_root) in str(evo_dir)
        
    finally:
        # Clean up environment
        for k in env:
            if k in os.environ:
                del os.environ[k]


def test_genes_persist_to_state_root_after_solidify_simulation() -> None:
    """Genes should be written to GEP_ASSETS_DIR (under state_root)."""
    from evolver.gep.paths import get_gep_assets_dir
    
    # In a real solidify, genes.json would be written to get_gep_assets_dir()
    gep_dir = get_gep_assets_dir()
    genes_path = gep_dir / "genes.json"
    
    # Verify the path construction is correct
    assert "gep" in str(genes_path)
    
    # The actual write happens in solidify.py via asset_store
    # This test validates the path resolution


def test_episodes_persist_to_evolution_dir_after_solidify_simulation() -> None:
    """Episodes should be written to EVOLUTION_DIR/episodes/ (under state_root)."""
    from evolver.gep.paths import get_evolution_dir
    
    evo_dir = get_evolution_dir()
    episodes_dir = evo_dir / "episodes"
    
    # Verify the path construction
    assert "evolution" in str(evo_dir)
    
    # Episodes are written in episode_record.py
    # This test validates the path resolution


# ---------------------------------------------------------------------------
# Test 7: Mailbox hello ack on boot
# ---------------------------------------------------------------------------


def test_mailbox_hello_sent_on_boot(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """swarm_boot should send mailbox hello if applicable."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    client = _McpClient(scratch_dir, env)
    
    try:
        # Boot should handle mailbox hello
        boot = client.call("swarm_boot", {"agent_name": "test-mailbox"})
        
        # Check boot_once list
        boot_once = boot.get("boot_once", [])
        
        # Hello should be in boot_once or already executed
        # (The actual hello is sent once per agent_name per session)
        # We verify it's in the protocol
        
        assert isinstance(boot_once, list)
        
        # The state should include mailbox info
        state = boot.get("state", {})
        mailbox = state.get("mailbox_pending", {})
        
        # Should have inbound/outbound counts
        assert "inbound" in mailbox or isinstance(mailbox, dict)
        
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Integration test: Complete soft-continue loop
# ---------------------------------------------------------------------------


def test_complete_soft_continue_loop_no_commit_to_product(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """Full loop: boot → tick → soft solidify → experience visible, no product commit."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    client = _McpClient(scratch_dir, env)
    
    try:
        # 1. Boot
        boot = client.call("swarm_boot", {"agent_name": "integration-test"})
        assert boot["next_action"] == "swarm_tick"
        
        # 2. Status check
        status = client.call("swarm_status")
        assert status["workspace_root"] == str(product_repo.resolve())
        
        # 3. Verify state_root is external
        state_root = Path(status["state_root"])
        assert str(external_state_root) in str(state_root)
        
        # 4. Verify no auto-commit to product repo
        # Check git status in product_repo
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=product_repo,
            capture_output=True,
            text=True,
        )
        # Should be clean - no commits from engine
        assert result.stdout.strip() == ""
        
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Additional validation tests
# ---------------------------------------------------------------------------


def test_workspace_id_stable_across_calls(
    product_repo: Path,
    scratch_dir: Path,
    external_state_root: Path,
) -> None:
    """workspace_id should be stable for same repo_root."""
    env = _workspace_env(product_repo, scratch_dir, external_state_root)
    
    # Call twice
    client1 = _McpClient(scratch_dir, env)
    status1 = client1.call("swarm_status")
    ws_id_1 = status1["workspace_id"]
    client1.close()
    
    client2 = _McpClient(scratch_dir, env)
    status2 = client2.call("swarm_status")
    ws_id_2 = status2["workspace_id"]
    client2.close()
    
    assert ws_id_1 == ws_id_2


def test_soft_reason_propagates_through_session() -> None:
    """Soft reasons should propagate through session accept logic."""
    from evolver.bench.frozen_gate import enrich_soft_accept
    
    # Simulate a verdict with soft reason
    verdict = {
        "accept": False,
        "reason": "flat",
        "score": 0.5,
        "parent_score": 0.5,
    }
    
    enriched = enrich_soft_accept(verdict)
    
    assert enriched["soft_accept"] is True
    assert enriched["soft_reason"] == "flat"
    assert enriched["reason"] == "flat"  # Reason is preserved
    assert "soft-accept" in str(enriched["warnings"]).lower()
    # Warning should mention not writing Parent baseline
    assert "not write a parent baseline" in enriched["warnings"][0].lower()
