# Hub Publish Flow Quickstart

> End-to-end asset lifecycle: **Distill** an LLM response → **Reuse** Hub assets → **Publish** genes and capsules back to the Hub.

## Prerequisites

- Python 3.12+ and `uv` installed
- Hub account (`evolver login`)
- A completed LLM conversation with session logs

## 1. Distill an LLM response into genes/capsules

```bash
# Distill from a response file
uv run evolver distill --response-file /path/to/conversation.jsonl

# Dry-run (preview without persisting)
uv run evolver distill --response-file /path/to/conversation.jsonl --dry-run
```

The distiller extracts:
- **Genes**: mutation strategies, risk levels, expected outcomes
- **Capsules**: concrete code changes, config adjustments, tool invocations
- **Signals**: error patterns, performance issues, capability gaps

Output is written to `.evolver/gep/` as candidate genes and capsules.

## 2. Review distilled output

```bash
# List all genes
cat .evolver/gep/genes.json

# List all capsules
cat .evolver/gep/capsules.json

# Show candidate genes (not yet solidified)
uv run evolver webui --port 8080
# → "Candidates" section or GET /api/candidates
```

## 3. Reuse Hub assets

```bash
# Search for and download a reusable asset from the Hub
uv run evolver fetch "error-handling"

# With a limit on results
uv run evolver fetch "timeout" --limit 5

# Dry-run (preview what would be fetched)
uv run evolver fetch "refactor" --dry-run
```

### How reuse works

1. The CLI queries the Hub for matching genes/capsules
2. Matching assets are downloaded and stored locally
3. The reuse is logged to `asset_call_log.jsonl` for attribution
4. Token savings are tracked per asset

## 4. Publish to the Hub

```bash
# After you've developed a useful gene/capsule, publish it
uv run evolver publish gene-id-here

# Publish with full context
uv run evolver publish g-7 --capsule c-12
```

The publish flow:
1. Validates the asset (schema + content hash)
2. Signs with your node secret
3. Pushes to Hub via A2A protocol
4. Records publication in `asset_call_log.jsonl`

## 5. End-to-end workflow

```bash
# Complete lifecycle:
# 1. Run a cycle with LLM execution
uv run evolver run

# 2. Distill the response
uv run evolver distill --response-file logs/session.jsonl

# 3. Inspect what was generated
cat .evolver/gep/candidates.jsonl

# 4. Apply the best gene (solidify)
uv run evolver solidify

# 5. Fetch related assets from Hub for inspiration
uv run evolver fetch "similar-pattern"

# 6. Publish your gene back to the community
uv run evolver publish g-7
```

## 6. Audit the asset call log

```bash
# Show all Hub interactions
uv run evolver asset-log

# Filter by action type
uv run evolver asset-log --action asset_publish --last 10

# Show call log for a specific run
uv run evolver asset-log --run run-2025-001

# JSON output
uv run evolver asset-log --json --action asset_reuse
```

Each entry records: `action`, `asset_id`, `run_id`, `tokens_saved`/`tokens_spent`, `timestamp`.

## 7. Sync with Hub

```bash
# Pull tasks and assets from Hub
uv run evolver sync

# Sync specific scopes
uv run evolver sync --scope genes,capsules

# Dry-run
uv run evolver sync --dry-run

# Force re-sync (ignore timestamps)
uv run evolver sync --force
```

## 8. WebUI visibility

```bash
uv run evolver webui --port 8080
```

- **Asset Economics** panel: reuse/reference counts, token savings, top assets
- **Hub Quality Gate** panel: service reviews, asset hash validation
- **API**: `GET /api/call-log`, `GET /api/asset-reuse`, `GET /api/asset-costs`

## 9. Troubleshooting

| Symptom | Solution |
|---------|----------|
| `distill` produces empty output | Ensure the response file is valid JSONL with conversation turns |
| `fetch` returns no results | Hub may not have matching assets; try broader queries |
| `publish` fails with "not signed" | Run `evolver login` or check `A2A_NODE_SECRET_VERSION` |
| `asset-log` is empty | Hub interactions are only logged when the proxy is active |
| Token savings show 0 | Reuse attribution only works when `EVOLVER_OUTCOME_REPORT=on` |
