# Hello World — Single Evolution Cycle

Run one GEP evolution cycle in an isolated workspace (no Hub, no Proxy, no side effects).

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) installed
- An LLM API key (Anthropic or compatible) in `.env`:

```bash
# .env (repo root or cwd)
ANTHROPIC_API_KEY=sk-ant-...
# or for OpenRouter:
ANTHROPIC_API_URL=https://openrouter.ai/api/v1/messages
```

## Step 1: Install dependencies

```bash
cd /path/to/evolver.py
uv sync
```

## Step 2: Run one evolution cycle

### Linux / macOS

```bash
export OPENCLAW_WORKSPACE="$(pwd)/examples/hello-world/workspace"
export EVOLVER_NO_PARENT_GIT=1
mkdir -p "$OPENCLAW_WORKSPACE/memory"

uv run evolver
```

### Windows PowerShell

```powershell
$env:OPENCLAW_WORKSPACE = "$PWD\examples\hello-world\workspace"
$env:EVOLVER_NO_PARENT_GIT = "1"
New-Item -ItemType Directory -Force -Path "$env:OPENCLAW_WORKSPACE\memory"

uv run evolver
```

## Expected Output

The terminal prints a **GENOME EVOLUTION PROTOCOL** prompt — this is the mutation plan the LLM should execute. Behind the scenes:

1. **Preflight checks**: system load, repair loop detection, git lock auto-repair
2. **Collect**: scans `memory/` for runtime logs and error patterns
3. **Signals**: classifies signals (log_error, perf_bottleneck, capability_gap, etc.)
4. **Enrich**: adds cognitive recall, living memory, Hub query (if connected)
5. **Autopoiesis**: self-check — viability, homeostasis, friction detection
6. **Select**: picks the best gene/capsule for the current signals
7. **Dispatch**: generates the GEP prompt for LLM execution

Files generated in the workspace:
- `memory/evolution/evolution_solidify_state.json` — pending solidify state
- `.evolver/gep/genes.json` — gene store (seed genes if first run)
- `.evolver/gep/capsules.json` — capsule store
- `.evolver/gep/events.jsonl` — evolution event log

## Next Steps

| What | Command |
|------|---------|
| Review the generated prompt | `uv run evolver --review` |
| Apply a gene (solidify) | `uv run evolver solidify` |
| Run continuously (daemon) | `uv run evolver --loop` |
| Monitor via WebUI | `uv run evolver webui --port 8080` |
| Generate a self-report | `uv run evolver self-report --no-write --json` |
| Distill an LLM response | `uv run evolver distill --response-file path.jsonl` |
| Show asset call log | `uv run evolver asset-log` |

## Customizing the Cycle

```bash
# Run with a specific strategy
EVOLVE_STRATEGY=repair uv run evolver

# Enable verbose output
EVOLVER_LOG_LEVEL=DEBUG uv run evolver

# Run with Autopoiesis disabled
EVOLVER_AUTOPOIESIS=0 uv run evolver

# Run with review (pause after prompt for approval)
uv run evolver --review
```

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "No API key found" | Set `ANTHROPIC_API_KEY` in `.env` or environment |
| "not a git repository" | Set `EVOLVER_NO_PARENT_GIT=1` or `git init` your workspace |
| No output / empty prompt | Check `logs/evolution.log`; may need seed genes (`uv run evolver sync`) |
| "system load exceeds threshold" | Wait for CPU load to drop; increase `EVOLVE_LOAD_MAX` |
| Windows: no `os.getloadavg()` | Load check returns 0 on Windows — cycles always proceed |
