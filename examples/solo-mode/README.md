# Solo Mode Quickstart

> Run evolver in **fully isolated** mode — no Hub, no network, no external dependencies.

Solo mode is designed for air-gapped environments, offline development, or when you want complete control over the evolution process without any external communication.

## Prerequisites

- Python 3.12+ and `uv` installed
- A git repository (or use `EVOLVER_NO_PARENT_GIT=1`)
- An LLM API key in `.env` (Anthropic or compatible)

## 1. Run in solo mode

```bash
cd /path/to/your/project
uv run evolver --solo
```

This starts the evolver in constrained-wild mode:
- **No Hub connection** — all Hub features are disabled (task pickup, asset sync, ATP marketplace)
- **No network calls** — only local LLM API calls are made
- **Local-only evolution** — genes and capsules are generated and stored locally
- **Implies `--loop`** — runs continuously

## 2. What solo mode disables

| Feature | Status |
|---------|--------|
| Hub task pickup | ❌ Disabled |
| Hub asset sync | ❌ Disabled |
| ATP marketplace | ❌ Disabled |
| Proxy / A2A communication | ❌ Disabled |
| Hub quality gate | ❌ Skipped |
| Event delivery to Hub | ❌ Disabled |
| Autopoiesis self-report | ✅ Local only |
| Gene selection & mutation | ✅ Normal |
| LLM dispatch | ✅ Normal |
| Local asset store | ✅ Normal |
| Memory graph recording | ✅ Normal |

## 3. Solo mode with custom configuration

```bash
# Run solo with review mode (pause after each cycle)
uv run evolver --solo --review

# Solo mode with custom .env
EVOLVER_LOOP_INTERVAL_MS=60000 \
EVOLVER_AUTOPOIESIS=1 \
EVOLVER_LEARNING_SIGNALS=1 \
uv run evolver --solo

# Solo mode with no parent git (isolated workspace)
EVOLVER_NO_PARENT_GIT=1 \
OPENCLAW_WORKSPACE=/tmp/solo-workspace \
uv run evolver --solo
```

## 4. Combine with WebUI for monitoring

```bash
# Terminal 1: solo daemon
uv run evolver --solo

# Terminal 2: WebUI dashboard
uv run evolver webui --port 8080
```

Open `http://localhost:8080` — you'll see:
- System status, gene/capsule counts
- Pipeline insights (diagnosis, memory sync, asset economics)
- Per-cycle persona commentary
- All panels work locally; only Hub-dependent panels show "no data"

## 5. Inspect local artifacts

```bash
# Genes and capsules
cat .evolver/gep/genes.json

# Evolution events
cat .evolver/gep/events.jsonl

# Memory graph
cat memory/evolution/memory_graph.jsonl

# Autopoiesis rules
cat memory/evolution/autopoiesis_rules.json

# Lessons learned
cat memory/evolution/LESSONS_LEARNED.md

# Session scope state
ls memory/evolution/
```

## 6. Exit and resume

```bash
# Press Ctrl+C to gracefully stop (one cycle completes)
# On restart, evolver picks up from local state:
uv run evolver --solo
```

## 7. Troubleshooting

| Symptom | Solution |
|---------|----------|
| No Hub features available | Expected — solo mode is intentionally offline |
| "no genes found" | Evolver needs a few cycles to generate local genes; be patient |
| WebUI Hub panels empty | Expected — Hub quality gate and Hub-specific data are unavailable |
| LLM timeout | Check your API key in `.env`; adjust `ANTHROPIC_TIMEOUT` |
| Gene inert ban triggering | Normal in solo mode with limited gene pool; increase `EVOLVER_GENE_INERT_BAN_STREAK` |
