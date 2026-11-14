"""P0-1 (支柱零, v1.114.0): one-touch ``evolver init`` bootstrap.

Machine criteria pinned here: git auto-init in empty dirs, idempotent MCP
config writing for detected hosts, legacy-state migration, and the clean
subprocess baseline (first-write-only pack + anchor + parent library +
project native baseline) with secrets stripped.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from evolver.ops.init_bootstrap import (
    BOOTSTRAP_MARKER,
    _child_env,
    bootstrap,
    bootstrap_baseline_now,
    detect_hosts,
    write_mcp_configs,
)


@pytest.fixture
def iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the user home so host detection sees only what we plant."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture
def iso_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """External state root inside the test sandbox."""
    root = tmp_path / "state-root"
    root.mkdir()
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(root))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return root


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


def test_empty_dir_with_yes_initializes_git(
    tmp_path: Path, iso_home: Path, iso_state: Path
) -> None:
    project = tmp_path / "fresh"
    project.mkdir()
    (project / ".keep").write_text("", encoding="utf-8")  # dotfile: still empty enough

    started = time.monotonic()
    report = bootstrap(project=project, yes=True, spawn=False)
    elapsed = time.monotonic() - started

    assert report["ok"] is True
    assert report["loop_ready"] is True
    assert report["git"]["action"] == "initialized"
    assert elapsed < 3.0, f"init must stay under 3s, took {elapsed:.2f}s"
    assert (project / ".git").is_dir()
    gitignore = (project / ".gitignore").read_text(encoding="utf-8")
    assert ".evolver/" in gitignore and "memory/" in gitignore


def test_nonempty_non_git_dir_requires_yes(tmp_path: Path, iso_home: Path, iso_state: Path) -> None:
    project = tmp_path / "busy"
    project.mkdir()
    (project / "main.py").write_text("print('hi')\n", encoding="utf-8")
    report = bootstrap(project=project, yes=False, spawn=False)
    assert report["ok"] is False
    assert report["git"]["error"] == "not_a_git_repo"
    assert "--yes" in (report["git"].get("hint") or "")
    # The MCP layer still did its job — init never blocks host wiring.
    assert isinstance(report["mcp_configs"], list)


def test_mcp_configs_written_and_idempotent(
    tmp_path: Path, iso_home: Path, iso_state: Path
) -> None:
    (iso_home / ".claude").mkdir()
    (iso_home / ".cursor").mkdir()
    (iso_home / ".codex").mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    hosts = detect_hosts(project)
    assert "claude-code" in hosts and "cursor" in hosts and "codex" in hosts

    first = write_mcp_configs(project, hosts)
    assert all(row["status"] == "written" for row in first), first

    mcp_json = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    entry = mcp_json["mcpServers"]["evolver"]
    # v1.114.0 round-121: entry is built via uv_runtime.build_evolver_command
    # (launcher-resolved argv, never a bare interpreter path).
    assert entry["command"]
    assert entry["args"][-2:] == ["evolver", "mcp"]

    toml = (iso_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.evolver]" in toml

    second = write_mcp_configs(project, hosts)
    assert all(row["status"] == "unchanged" for row in second), second


def test_mcp_merge_preserves_foreign_entries(
    tmp_path: Path, iso_home: Path, iso_state: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    existing = {"mcpServers": {"other": {"command": "uvx", "args": ["something"]}}}
    (project / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")
    (iso_home / ".claude").mkdir()

    write_mcp_configs(project, ["claude-code"])
    merged = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert merged["mcpServers"]["other"]["command"] == "uvx"
    assert "evolver" in merged["mcpServers"]


def test_existing_git_repo_legacy_state_migrates(
    tmp_path: Path, iso_home: Path, iso_state: Path
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.email", "t@t")
    _git(project, "config", "user.name", "T")
    legacy = project / "memory" / "evolution"
    legacy.mkdir(parents=True)
    (legacy / "LESSONS_LEARNED.md").write_text("# lessons\n", encoding="utf-8")

    report = bootstrap(project=project, yes=False, spawn=False)
    assert report["ok"] is True
    assert report["git"]["action"] == "existing"
    assert report["migration"] is not None and report["migration"]["ok"] is True


def test_child_env_strips_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    monkeypatch.setenv("SOME_VENDOR_API_KEY", "sk-other")
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    env = _child_env(tmp_path)
    assert "DEEPSEEK_API_KEY" not in env
    assert "SOME_VENDOR_API_KEY" not in env
    assert env["EVOLVER_REPO_ROOT"] == str(tmp_path)


def test_baseline_child_first_write_only(
    tmp_path: Path, iso_home: Path, iso_state: Path, temp_workspace: Path
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    _git(project, "init")

    first = bootstrap_baseline_now(project=project)
    assert first["ok"] is True, first
    steps = {s["step"]: s for s in first["steps"]}
    assert steps["freeze_pack"].get("error") is None and steps["freeze_pack"]["frozen"] is True
    assert steps["anchor"].get("ok") is True
    assert steps["parent_library"].get("ok") is True
    assert steps["native_baseline"].get("reason") == "written"

    matches = list(iso_state.rglob("project_native_baseline.json"))
    assert matches, "native baseline must land under the state root"
    body = json.loads(matches[0].read_text(encoding="utf-8"))
    assert body["format"] == "evolver.project_native_baseline.v1"
    assert body["repo_root"] == str(project)

    done_markers = list(iso_state.rglob(BOOTSTRAP_MARKER))
    assert done_markers
    assert json.loads(done_markers[0].read_text(encoding="utf-8"))["status"] == "done"

    second = bootstrap_baseline_now(project=project)
    steps2 = {s["step"]: s for s in second["steps"]}
    assert steps2["parent_library"]["reason"] == "already_established"
    assert steps2["native_baseline"]["reason"] == "already_written"


def test_unparseable_config_is_never_clobbered(
    tmp_path: Path, iso_home: Path, iso_state: Path
) -> None:
    """Round-121 review pin: JSONC comments / syntax errors in an existing
    host config must ABORT the write — never silently replace the human's
    config with a fresh object."""
    from evolver.ops.init_bootstrap import write_mcp_configs

    project = tmp_path / "proj"
    project.mkdir()
    cfg = project / ".mcp.json"
    cfg.write_text(
        '{\n  // human comment\n  "mcpServers": { "other": {"command": "x"} },\n}',
        encoding="utf-8",
    )
    rows = write_mcp_configs(project, ["claude-code"])
    # The write is refused as an error row — and the raw text is untouched.
    assert rows[0]["status"] == "error" and rows[0]["ok"] is False
    assert "unparseable" in str(rows[0]["error"])
    text = cfg.read_text(encoding="utf-8")
    assert "// human comment" in text
    assert "evolver" not in text


def test_evolve_begin_lazy_bootstraps_uninitialized_workspace(
    tmp_path: Path, iso_home: Path, iso_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """支柱 0.2: a first ``evolve_begin`` on an initialized
    but never-bootstrapped workspace dispatches the background baseline
    child silently — no manual ``evolver init`` detour."""
    import asyncio
    import subprocess

    from evolver.gep.paths import get_workspace_state_dir
    from evolver.swarm import evolve_begin

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # walk the product path

    result = asyncio.run(evolve_begin(agent_name="lazy-agent"))
    assert result["ok"] is True
    assert result["discovery_only"] is True
    marker = get_workspace_state_dir(tmp_path) / "bootstrap_baseline.json"
    assert marker.is_file(), "lazy bootstrap must dispatch the baseline job"
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "dispatched"


def test_evolve_begin_skips_lazy_bootstrap_when_marker_exists(
    tmp_path: Path, iso_home: Path, iso_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from evolver.gep.paths import get_workspace_state_dir
    from evolver.swarm import evolve_begin

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    marker = get_workspace_state_dir(tmp_path) / "bootstrap_baseline.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"status": "done", "ok": true}\n', encoding="utf-8")

    calls: list[str] = []
    monkeypatch.setattr(
        "evolver.ops.init_bootstrap.bootstrap",
        lambda **kw: calls.append("bootstrapped") or {"ok": True},
    )
    result = asyncio.run(evolve_begin(agent_name="warm-agent"))
    assert result["ok"] is True
    assert calls == []  # already bootstrapped: no second dispatch


def test_doctor_reads_the_native_baseline(
    tmp_path: Path, iso_home: Path, iso_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-121 review: the baseline artifact the init child wrote must have
    a reader — diagnose surfaces it as ``state["native_baseline"]`` (absent
    = ``None``, never a roadblock)."""
    import subprocess as _subprocess

    from evolver.gep.paths import get_workspace_state_dir
    from evolver.ops.init_bootstrap import load_native_baseline
    from evolver.ops.open_box import diagnose

    _subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))

    assert load_native_baseline(tmp_path) is None
    report = diagnose(project=tmp_path)
    assert report["native_baseline"] is None

    base = get_workspace_state_dir(tmp_path)
    base.mkdir(parents=True, exist_ok=True)
    (base / "project_native_baseline.json").write_text(
        json.dumps(
            {
                "format": "evolver.project_native_baseline.v1",
                "head": "abc123def456",
                "written_at": "2026-11-13T00:00:00Z",
                "pytest_collect": {"ok": True, "tests_collected": 7},
                "ast_health": {"py_files": 3},
            }
        ),
        encoding="utf-8",
    )
    row = load_native_baseline(tmp_path)
    assert row is not None and row["pytest_collect"]["tests_collected"] == 7
    report = diagnose(project=tmp_path)
    assert report["native_baseline"]["head"] == "abc123def456"


def test_init_keeps_git_status_clean_and_preserves_tracked_agents_md(
    tmp_path: Path, iso_home: Path, iso_state: Path
) -> None:
    """Usability guard: running ``evolver init`` in a clean git repo when multiple
    IDEs exist in $HOME must NOT dirty tracked AGENTS.md / CLAUDE.md and must
    register newly created local host configs in ``.git/info/exclude`` so
    ``git status --porcelain`` stays completely empty."""
    (iso_home / ".claude").mkdir()
    (iso_home / ".cursor").mkdir()
    (iso_home / ".codex").mkdir()
    (iso_home / ".opencode").mkdir()

    project = tmp_path / "clean_repo"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.email", "t@t")
    _git(project, "config", "user.name", "T")
    original_agents = "# Project Rules\nKeep clean.\n"
    (project / "AGENTS.md").write_text(original_agents, encoding="utf-8")
    _git(project, "add", "AGENTS.md")
    _git(project, "-c", "commit.gpgsign=false", "commit", "-m", "initial")

    report = bootstrap(project=project, yes=False, spawn=False)
    assert report["ok"] is True
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == original_agents
    assert not (project / "CLAUDE.md").exists()
    assert report["git_excluded"], "newly created local host configs must be git-excluded"

    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "", f"git status dirtied after init:\n{proc.stdout}"


def test_init_hosts_filter_and_no_hosts(tmp_path: Path, iso_home: Path, iso_state: Path) -> None:
    (iso_home / ".claude").mkdir()
    (iso_home / ".cursor").mkdir()

    proj_filtered = tmp_path / "p1"
    proj_filtered.mkdir()
    _git(proj_filtered, "init")
    rep1 = bootstrap(project=proj_filtered, spawn=False, hosts_filter=["cursor"])
    assert rep1["hosts"] == ["cursor"]
    assert (proj_filtered / ".cursor" / "mcp.json").is_file()
    assert not (proj_filtered / ".mcp.json").exists()

    proj_none = tmp_path / "p2"
    proj_none.mkdir()
    _git(proj_none, "init")
    rep2 = bootstrap(project=proj_none, spawn=False, configure_hosts=False)
    assert rep2["hosts"] == []
    assert rep2["mcp_configs"] == []


def test_external_repo_with_foreign_pyproject_spawns_clean_baseline_and_safe_mcp(
    tmp_path: Path, iso_home: Path, iso_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Black-box dogfood pin: running ``evolver init`` inside an external user
    repository that has its OWN ``pyproject.toml`` (without evolver installed in
    that foreign project) must:
    1) Never point MCP ``--project`` at the foreign user repository;
    2) Successfully complete the detached background baseline child and parse
       ``pytest --collect-only -q`` counts (including ``in 0.0Xs`` suffixes).
    """
    (iso_home / ".cursor").mkdir()
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))

    ext_repo = tmp_path / "foreign_app"
    ext_repo.mkdir()
    _git(ext_repo, "init")
    _git(ext_repo, "config", "user.email", "t@t")
    _git(ext_repo, "config", "user.name", "T")
    (ext_repo / "pyproject.toml").write_text(
        '[project]\nname = "foreign-shop"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (ext_repo / "calc.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    (ext_repo / "test_calc.py").write_text(
        "from calc import double\n\n"
        "def test_one() -> None:\n    assert double(2) == 4\n\n"
        "def test_two() -> None:\n    assert double(3) == 6\n",
        encoding="utf-8",
    )
    _git(ext_repo, "add", "-A")
    _git(ext_repo, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    monkeypatch.chdir(ext_repo)

    report = bootstrap(project=ext_repo, yes=False, spawn=True)
    assert report["ok"] is True

    mcp_cfg = json.loads((ext_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    args = mcp_cfg["mcpServers"]["evolver"]["args"]
    # Must NEVER pass the foreign user repo as uv's --project
    assert str(ext_repo) not in args, args

    from evolver.gep.paths import get_workspace_state_dir

    ws_state = get_workspace_state_dir(ext_repo)
    marker = ws_state / BOOTSTRAP_MARKER
    deadline = time.monotonic() + 25.0
    done = False
    while time.monotonic() < deadline:
        if marker.is_file():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            if data.get("status") == "done":
                done = True
                break
        time.sleep(0.2)
    assert done, f"Detached baseline child did not finish in external repo: {ws_state}"

    native = json.loads((ws_state / "project_native_baseline.json").read_text(encoding="utf-8"))
    assert native["pytest_collect"]["ok"] is True
    assert native["pytest_collect"]["tests_collected"] == 2
