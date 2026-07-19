# IDE Hooks Quickstart

> Install evolver **session hooks** into your IDE — auto-inject evolution memory and record outcomes as you code.

## Supported IDEs

| IDE | Adapter Mode | What Gets Installed |
|-----|-------------|-------------------|
| **Cursor** | cursor | `sessionStart` / `sessionEnd` / `signalDetect` hooks in `.cursor/hooks.json` |
| **Claude Code** | claude-code | Claude Code hook config with evolver scripts |
| **OpenCode** | opencode | OpenCode session hooks with `session_id` passthrough |
| **Codex** | codex | Codex hook scripts with full transcript passthrough |
| **Kiro** | kiro | Kiro hook config (includes dedup for per-prompt platforms) |
| **VS Code** | vscode | Static hook configuration (generic) |
| **Generic** | generic | `evolver-hooks.json` at `--project-dir` |

## 1. Install hooks (one command)

```bash
# Install for Cursor (most common)
uv run evolver setup-hooks --platform cursor

# Install for Claude Code
uv run evolver setup-hooks --platform claude-code

# Install for OpenCode (passes session_id for transcript scoping)
uv run evolver setup-hooks --platform opencode

# Install for a specific project directory
uv run evolver setup-hooks --platform cursor --project-dir /path/to/project
```

### What happens when you install hooks

1. **`setup_hooks.py`** detects your IDE platform and project root
2. It generates/writes the IDE-specific hook configuration file
3. Three hook scripts are wired:
   - **`session-start`**: Runs when a new session begins — injects recent evolution memory into the IDE context
   - **`signal-detect`**: Runs periodically — detects evolution signals (errors, perf issues, feature gaps) from the conversation
   - **`session-end`**: Runs when the session ends — records the outcome (git diff stats, signals) to the memory graph

## 2. Verify installation

```bash
# Verify hooks are installed correctly
uv run evolver setup-hooks --verify

# Show what's installed
uv run evolver setup-hooks --platform cursor --verify
```

For Cursor, check that `.cursor/hooks.json` contains the evolver hooks.  
For Claude Code, check the Claude Code hook configuration.  
For VS Code/generic, check the output directory for `evolver-hooks.json`.

## 3. How hooks work at runtime

### session-start flow
```
IDE starts new session
  → calls session_start.py with stdin (session metadata/transcript records)
  → reads recent evolution outcomes from memory graph
  → filters outcomes relevant to the current workspace
  → injects "Evolution Memory" context into the IDE
  → sets EVOLVER_SESSION_SCOPE for scoped evolution state
```

### signal-detect flow
```
IDE conversation generates content
  → calls signal_detect.py with stdin (conversation text/payload)
  → detects signal patterns: log_error, perf_bottleneck, capability_gap, etc.
  → returns signal tags to IDE for agent awareness
```

### session-end flow
```
IDE session ends
  → calls session_end.py with stdin (session metadata)
  → runs git diff --stat HEAD~1 (or working-tree diff)
  → extracts signals from diff content
  → records outcome to memory graph
  → emits systemMessage (suppressed on Cursor)
```

## 4. Uninstall hooks

```bash
# Remove evolver hooks from your IDE
uv run evolver setup-hooks --uninstall --platform cursor

# Remove from a specific project
uv run evolver setup-hooks --uninstall --platform claude-code --project-dir /path/to/project
```

## 5. Dry-run (preview without installing)

```bash
# See what would be installed without changing anything
uv run evolver setup-hooks --platform cursor --dry-run
```

## 6. Force reinstall

```bash
# Overwrite existing hooks (even if already installed)
uv run evolver setup-hooks --platform cursor --force
```

## 7. Configuration

```bash
# Hook-specific env vars (set in IDE or .env)
EVOLVER_HOOK_VERBOSE=1           # Show verbose output (disables Cursor suppression)
EVOLVER_HOOK_HOST=cursor          # Override auto-detected host
MEMORY_GRAPH_PATH=/path/to/graph  # Custom memory graph location
EVOLVER_SESSION_START_DEDUP=1     # Enable dedup for per-prompt platforms (Kiro)
EVOLVER_SESSION_START_DEDUP_TTL_S=1800  # Dedup TTL in seconds
```

## 8. Inspect hook output

```bash
# Manual session-start (simulates IDE calling the hook)
echo '{"type":"session_meta","payload":{"cwd":"/path/to/project"}}' | \
  uv run python src/evolver/adapters/scripts/session_start.py

# Manual signal-detect
echo '{"text":"error: connection timeout"}' | \
  uv run python src/evolver/adapters/scripts/signal_detect.py

# Manual session-end
echo '{"type":"session_meta","payload":{"cwd":"/path/to/project"}}' | \
  uv run python src/evolver/adapters/scripts/session_end.py
```

## 9. Troubleshooting

| Symptom | Solution |
|---------|----------|
| Hooks don't fire | Check IDE logs; verify hooks.json is valid JSON; run with `EVOLVER_HOOK_VERBOSE=1` |
| "not a git repository" | Hooks need git for diff-based outcomes; `git init` your project |
| Cursor shows systemMessage | Set `EVOLVER_HOOK_VERBOSE=0` or unset `CURSOR_TRACE_ID` |
| Memory graph not found | Set `MEMORY_GRAPH_PATH` or ensure `.evolver/` workspace-id exists |
| Kiro hooks fire too often | Set `EVOLVER_SESSION_START_DEDUP=1` to enable dedup |
| "session scope" not working | Check that `EVOLVER_SESSION_SCOPE` is set by session_start (requires transcript cwd) |
