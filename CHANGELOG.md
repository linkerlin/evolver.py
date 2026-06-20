# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Sprint 9: v1.89.14 parity (7 gaps closed)

### Gap 1: Inert Gene Ban (#562)
- `gep/memory_graph.py`: `stable_no_error`/`heuristic_delta`/`predictive` outcomes
  now classified as **inert** — they build no Bayesian confidence and no longer
  count as successes for `preferredGeneId`.
- New `_count_trailing_inert()`: after `GENE_INERT_BAN_STREAK` (=8) consecutive
  trailing inert outcomes with no real success, the gene is added to
  `bannedGeneIds` so the selector yields null and the pipeline mutates.
- A single real success (e.g. `error_cleared`) resets the inert streak.
- 5 regression tests ported from `test/issue562InertGeneBan.test.js`.

### Gap 2: Node Secret Versioning
- `proxy/lifecycle/manager.py`: `parse_node_secret_version()`, `node_secret_version`
  property (store > env precedence), stale-secret detection (store version < env
  version → Hub rotated → clear store secret).
- `hello()`/`heartbeat()` persist the Hub-returned `node_secret_version`.

### Gap 3: Hub-Unreachable Exponential Backoff
- `proxy/lifecycle/manager.py`: `_record_hub_unreachable()` / `_record_hub_reachable()`
  / `_hub_unreachable_wait_ms()` / `hub_unreachable_backoff_ms()` — exponential
  backoff (5s→15min cap) on network errors (ConnectError/TimeoutException).
- `hello()`/`heartbeat()` check backoff before sending and record
  reachable/unreachable on success/failure.

### Gap 4: Anti-Abuse Telemetry Heartbeat
- `gep/anti_abuse_telemetry.py`: `build_heartbeat_anti_abuse()` — privacy-preserving
  envelope with HMAC-pseudonymized device/workspace hashes, source-confidence
  labels (hub_required/hub_service/hub_observed), integrity hashes, task timing.
- `config.py`: `ANTI_ABUSE_TELEMETRY_MODE` (default `heartbeat`, explicit opt-out).
- `proxy/lifecycle/manager.py`: heartbeat `meta.anti_abuse` injection when mode=heartbeat.

### Gap 5: Outcome Report Mode (P4-a Slice B)
- `config.py`: `OUTCOME_REPORT_MODE` (default `off`) + `outcome_report_mode()`
  resolver (on/enforce/true → `on`).

### Gap 6: Force-Update from Heartbeat
- `proxy/lifecycle/manager.py`: `_maybe_trigger_force_update_from_heartbeat()` with
  `EVOLVER_FORCE_UPDATE_RETRY_COOLDOWN_MS` (default 5min) — prevents Hub from
  hot-spinning force-updates on every heartbeat.

### Gap 7: Last-Update Ack
- `proxy/lifecycle/manager.py`: `read_pending_last_update()` / `set_pending_last_update()`;
  heartbeat carries `last_update_ack` + `node_secret_version` in payload.

### Stats
- **Tests**: 1573 → **1609** (+36 new tests, 0 regressions)
- **Baseline**: tracking v1.89.11 → **v1.89.14** parity on lifecycle + GEP selection

## [Unreleased] — Sprint 0-8 catch-up against evolver v1.89.11

### Sprint 0: Engineering baseline
- Fixed `gep/sanitize.py` `import json` position bug (was at file bottom, caused NameError).
- `gep/sanitize.py`: reverse leak scan now skips path/URL-shaped env values (#568).
- Added 6 credential redaction patterns (jwt, aws, github, slack, connection_string, high_entropy).
- `CHANGELOG.md` upgraded from stub to Keep-a-Changelog format.
- `CONTRIBUTING.md`: conventional commits with scope; baseline updated to 1331→1534 tests.

### Sprint 1: IDE runtime hooks
- Rewrote `adapters/scripts/runtime_paths.py` (24→315 lines): host-env project dir resolution,
  workspace-id atomic create with symlink guards, FS-only fallback.
- Rewrote `session_start.py` (41→211): workspace-scoped memory recall, non-git notice (throttled),
  dedup, lazy memory read from newest end.
- Rewrote `session_end.py` (48→214): HEAD~1 diff, workspace-id stamping, Cursor systemMessage suppression.
- Rewrote `signal_detect.py` (39→160): context-aware stratification, Claude Code payload parsing,
  multilingual (CJK) fallback.
- New `lock_paths.py` (52 lines): daemon singleton-lock location + lease staleness tunables.
- New `task_recall.py` (103 lines): `@evolver recall` triggered capsule recall.
- Updated `memory_filtering.py`: added `filter_relevant_outcomes` (Node contract).

### Sprint 3: Execution bridge + conversation sniffer
- New `gep/exec_bridge.py` (93 lines): Windows npm .cmd shim resolver (CVE-2024-27980).
- New `gep/conversation_sniffer.py` (240 lines): scan_corpus with local co-occurrence,
  off/shadow/enforce modes, cooldown, CJK support.
- Extended `gep/bridge.py`: added `determine_bridge_enabled()`.
- `evolve/runner.py`: Ralph-loop stale bridge-mode break (#559).

### Sprint 4: Security + seed library + deepening
- Expanded `genes.seed.json` (3→11 genes): full alignment with Node v1.87.0 seed library.
- Rewrote `gep/skill2gep.py` (187→400+): `parse_skill_md` with frontmatter + CJK sections,
  `infer_category` with word-boundary matching, `skill_to_gene_dict` with asset_id + quality heuristics.
- Deepened `gep/idle_scheduler.py` (220→300+): `EVOLVER_IDLE_OVERRIDE`, build-activity detection,
  FS-only idle fallback.
- `gep/schemas/gene.py`: added `avoid` and `_source` (alias) fields.

### Sprint 5: Multi-provider proxy routes
- New `proxy/router/gemini_route.py` (160 lines): Google Gemini API proxy with SSE.
- New `proxy/router/vertex_route.py` (145 lines): Vertex AI proxy with ADC auth.
- New `proxy/router/ollama_route.py` (140 lines): local Ollama proxy.
- New `proxy/router/responses_route.py` (150 lines): OpenAI-compatible API proxy.
- New `proxy/router/models_route.py` (85 lines): `/v1/models` aggregator.
- New `proxy/server/settings.py` (62 lines): proxy settings persistence.
- New `proxy/trace/extractor.py` (65 lines): multi-format token usage extraction.
- New `proxy/trace/usage.py` (60 lines): usage aggregator singleton.
- New `proxy/envelope.py` (45 lines): structured message envelope.
- New `proxy/inject.py` (50 lines): context injection + internal field stripping.
- Updated `model_router.py`: 5-provider upstream detection.

### Sprint 6: ATP CLI + mailbox transport
- Rewrote `atp/cli.py` (86→270): 15 subcommands (buy/orders/tasks/claim/deliver/settle/dispute/publish/policy/proofs/tier/order/status/enable/disable).
- Deepened `atp/atp_execute.py` (87→230): sandbox validation, structured proof building.
- Deepened `atp/atp_task_pickup.py` (99→200): ROI scoring, capability matching, concurrent limit.
- New `gep/mailbox_transport.py` (115 lines): proxy mailbox client with auto-start.

### Sprint 7: Missing modules
- New `gep/token_savings.py` (120 lines): token/USD cost savings tracker with monthly reports.
- New `gep/narrative_memory.py` (85 lines): evolution history narrative compressor.
- New `gep/memory_graph_adapter.py` (120 lines): advanced queries (success trajectory, failure clustering, fuzzy match).
- New `gep/directory_client.py` (75 lines): EvoMap directory service client.
- New `gep/oauth_login.py` (115 lines): OAuth 2.0 device-code flow with keychain integration.
- New `gep/claim_nudge.py` (75 lines): throttled task-claim suggestion generator.
- New `gep/device_id.py` (85 lines): cross-platform anonymous hardware fingerprint.
- New `gep/anti_abuse_telemetry.py` (120 lines): abuse pattern detector (flood/bypass/exhaustion).

### Sprint 8: Experiment framework + i18n + docs
- New `experiment/` module (4 files): agent_runner, metrics, comparison, cli — controlled A/B evaluation.
- New `README.ja-JP.md`: Japanese README.
- New `README.ko-KR.md`: Korean README.

### Stats
- **Tests**: 1331 → 1546+ (215+ new tests, 0 regressions)
- **Source files**: 192 → 217+ (25+ new modules)
- **Seed genes**: 3 → 11
- **Proxy routes**: 4 → 9
- **ATP subcommands**: 5 → 15
- **mypy strict**: 0 errors across all files
- **Baseline comparison**: v1.89.2 → tracking v1.89.11

## [1.89.2] - 2026-06-09

- Initial Python port release tracking Node.js v1.89.2.
- GEP data layer, evolution pipeline, Proxy infrastructure, ATP marketplace (partial),
  IDE adapters (partial), WebUI (partial).
