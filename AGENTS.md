# AGENTS.md — evolver.py

> Python 3.12+ port of [`@evomap/evolver`](https://github.com/EvoMap/evolver), a GEP-powered self-evolution engine for AI agents.

## Commands

| Action | Command |
|---|---|
| Install deps | `uv sync` |
| Run one evolution cycle | `uv run evolver` (or `uv run evolver run`) |
| Daemon loop | `uv run evolver --loop` |
| Review mode | `uv run evolver --review` |
| Apply pending mutation | `uv run evolver solidify` |
| Distill LLM response | `uv run evolver distill --response-file=<path>` |
| Fetch skill from Hub | `uv run evolver fetch <query>` |
| Sync assets | `uv run evolver sync [--scope=...]` |
| Launch WebUI | `uv run evolver webui [--port=8080]` |
| Run tests | `uv run pytest` |
| Run tests (no slow) | `uv run pytest -m "not slow"` |
| Lint | `uv run ruff check src tests` |
| Format check | `uv run ruff format --check src tests` |
| Auto-format | `uv run ruff format src tests` |
| Type check | `uv run mypy src` |
| Run via python | `uv run python -m evolver` |

## Architecture

This is a **port from Node.js** — the original source files at `@evomap/evolver` are heavily obfuscated with `javascript-obfuscator`. The Python implementation is a **behavioral-equivalence reimplementation** based on test contracts and public API surfaces, not a line-by-line translation.

### Source Layout (`src/evolver/`)

```
cli.py              CLI entry (argparse), .env loading, command dispatch
config.py           All runtime thresholds/timeouts, env-var overrides
canary.py           Fork-canary: verifies CLI loads without crash
gep/                GEP (Genome Evolution Protocol) core
  schemas/          Pydantic models: Gene, Capsule, Task, Protocol
  asset_store.py    JSON/JSONL persistence with overlay semantics
  paths.py          Central path resolution with env overrides
  a2a_protocol.py   Agent-to-Agent Hub protocol (HTTP)
  bridge.py         Git worktree bridge for mutations
  content_hash.py   SHA-256 content-addressable asset IDs
  crypto.py         Local secret management
  distill.py        Extract Gene/Capsule from LLM text output
  fetch.py          Download & install assets from Hub
  git_ops.py        Git diff/rollback/status helpers
  instance_lock.py  FileLock-based single-instance guard
  memory_graph.py   JSONL memory graph store & signal-key queries
  mutation.py       Mutation engine: category selection, variant generation
  personality.py    Personality profile (rigor, risk tolerance)
  prompt.py         GEP prompt assembly
  sanitize.py       Input sanitization for asset fields
  selector.py       Gene/capsule matching against signals
  signals.py        Signal collection & classification
  solidify.py       Apply gene → validate → persist → publish
  strategy.py       Evolution strategy selection
  sync.py           Hub sync: fetch tasks, download assets
evolve/             Evolution pipeline
  runner.py         Orchestrator: single cycle + daemon loop
  guards.py         Preflight checks (load, RSS, cooldown)
  pipeline/         6-stage pipeline (each is an async fn taking/returning ctx)
    collect.py      Scan memory/ for runtime logs & error patterns
    signals.py      Classify signals from collected data
    hub.py          Query Hub for matching assets & tasks
    enrich.py       Enrich context with Hub data
    select.py       Select best Gene/Capsule
    dispatch.py     Generate GEP prompt, write dispatch output
proxy/              Local HTTP proxy (127.0.0.1:19820)
webui/              FastAPI read-only dashboard
ops/                Health check, cleanup, narrative logging
adapters/           IDE hook generators (Cursor, Claude Code, etc.)
atp/                Agent Transaction Protocol marketplace
```

### Data Flow (Single Cycle)

```
Preflight → Collect → Signals → Hub → Enrich → Select → Dispatch
                                                          ↓
                                                     [GEP Prompt]
                                                          ↓
                                                     Solidify
```

Context is a plain `dict[str, Any]` threaded through each pipeline stage.

### GEP Asset Storage

Located at `<GEP_ASSETS_DIR>` (default `<workspace>/.evolver/gep/`):

- `genes.json` + `genes.jsonl` — base + overlay (JSONL entries override by ID)
- `capsules.json` + `capsules.jsonl` — same pattern
- `events.jsonl` — append-only evolution event log
- `candidates.jsonl`, `external_candidates.jsonl`
- `failed_capsules.json`
- `pending_signals.json`

Asset integrity is verified via `sha256:` content hashes stored in `asset_id`.

## Conventions

### Code Style

- Python 3.12+ syntax throughout: `from __future__ import annotations`, `X | None` unions, `list[str]` generics
- Pydantic v2 models with `ConfigDict(extra="forbid")` — unknown fields cause validation errors
- `from __future__ import annotations` at top of every file
- Double quotes (`ruff format` default)
- 100 char line limit
- 4-space indent
- All `async` functions are `async def`, no `@asyncio.coroutine`
- Type hints on all public functions
- `Final` for module-level constants from config
- No `typing.TypedDict` — use `dict[str, Any]` for pipeline context, Pydantic for schemas

### Naming

- Modules: `snake_case.py`
- Classes: `PascalCase` (Pydantic models, dataclasses)
- Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE` with `Final` type
- Internal helpers: leading underscore `_helper_fn`
- GEP terms preserved as-is: `Gene`, `Capsule`, `solidify`, `dispatch`, `distill`
- Each source file has a docstring referencing its Node.js equivalent

### Import Pattern

- Lazy imports inside functions are used deliberately in `cli.py` and `guards.py` to avoid pulling heavy modules before `.env` is loaded
- `config.py` is imported early — it only reads env vars, no side effects
- Pipeline stages import from `evolver.gep.*` submodules, not from each other

### Testing

- `pytest` with `pytest-asyncio` in `"auto"` mode (no `@pytest.mark.asyncio` needed)
- `respx` for mocking `httpx` calls
- `freezegun` for time-dependent tests
- Test files map 1:1 to source: `test_<module>.py` tests `evolver.<module>`
- `temp_workspace` fixture in `conftest.py` isolates all path env vars
- `isolated_evolver_env` fixture in `test_cli.py` adds `EVOLVER_NO_PARENT_GIT=1`
- `monkeypatch.setenv("GEP_ASSETS_DIR", ...)` for store tests
- `subprocess.run(["git", "init", ...])` for git-dependent tests

### Ruff Rules

Full lint set: `E, F, W, I, N, UP, B, C4, SIM, ARG, PL, RUF`

Intentionally suppressed:
- `PLR2004` — magic value comparisons are useful in a port
- `PLR0913` — many arguments inherited from Node API design

### mypy

`strict = true`, `ignore_missing_imports = true`, `warn_return_any`, `warn_unused_ignores`.

## Key Environment Variables

Tests must isolate these. The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `OPENCLAW_WORKSPACE` | (none) | Workspace root override |
| `EVOLVER_REPO_ROOT` | auto-detect via `.git` | Repo root override |
| `EVOLVER_HOME` | `~/.evomap` | Per-user state dir |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP asset storage |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | Evolution state |
| `MEMORY_DIR` | `<ws>/memory/` | Memory logs |
| `EVOLVER_NO_PARENT_GIT` | (none) | Set to `1` to disable `.git` walk |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub endpoint |
| `EVOLVE_STRATEGY` | `balanced` | Evolution strategy |
| `EVOLVE_BRIDGE` | auto | Git worktree mutation |
| `EVOLVER_ROLLBACK_MODE` | `stash` | Rollback strategy |

## Pitfalls

- **`.env` load order matters**: `cli.py:_load_dotenv()` loads `.env` from cwd first, then from repo root. Internal imports happen after. Adding top-level imports of heavy modules in `cli.py` will break env-var precedence.
- **JSONL overlay semantics**: `genes.jsonl` entries override `genes.json` by ID. Deleting a gene from `.json` but not `.jsonl` will resurrect it. Always test with both files.
- **Content hash verification**: `asset_store.load_genes()` silently skips entries whose `asset_id` hash doesn't match content. A gene that "disappears" on load likely has a corrupted hash.
- **Windows `os.getloadavg()` missing**: `guards.py:get_system_load()` catches `AttributeError` on Windows and returns zeros. Don't rely on load values in tests on Windows.
- **`--mad-dog` is `--loop`**: CLI alias, not a separate mode.
- **`asyncio_mode = "auto"`**: All `async def test_*` are automatically treated as async tests. No marker needed.
- **`from __future__ import annotations`**: All annotations are strings at runtime. Don't use annotations for `isinstance()` checks.
- **Atomic writes**: `asset_store.atomic_write_json` uses temp file + `os.replace`. On Windows, this can fail if the target is open by another process (e.g., daemon loop).
- **`canary.py` is subprocessed**: It's run in a child process before `solidify` commits. Don't import from it directly in tests.
- **Seed data**: `src/evolver/assets/gep/genes.seed.json` is bundled default genes. Tests should not modify it — use `GEP_ASSETS_DIR` override.
- **Test isolation**: Always use `monkeypatch.setenv` for env vars, never `os.environ` directly. The `temp_workspace` fixture handles this for common paths.
