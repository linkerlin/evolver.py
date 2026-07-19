# Self-Report Quickstart

> Inspect evolver's **autopoiesis** (self-maintenance) system — read self-reports, lessons learned, and autopoiesis rules.

## Prerequisites

- Python 3.12+ and `uv` installed
- At least one evolution cycle completed

## 1. Generate a self-report

```bash
# Generate and print a self-report (no write to disk)
uv run evolver self-report --no-write

# Generate with full capture (includes session capture data)
uv run evolver self-report --capture --no-write

# JSON output for programmatic consumption
uv run evolver self-report --json

# Generate and persist (writes to memory/evolution/)
uv run evolver self-report
```

### What a self-report contains

```json
{
  "timestamp": "2025-07-19T12:00:00Z",
  "friction_summary": {
    "total": 3,
    "categories": ["preflight_abort", "repair_loop", "gene_inert"],
    "points": [
      {
        "id": "f-1",
        "category": "repair_loop",
        "severity": "warning",
        "description": "3 次连续修复失败"
      }
    ]
  },
  "evolution": {
    "evolution_count": 12,
    "rules_applied": 5,
    "rules_pending": 2
  },
  "viability": {
    "score": 0.72,
    "status": "stable"
  },
  "homeostasis": {
    "actions": ["adjust_repair_threshold", "ban_inert_gene_g-12"]
  },
  "living_memory": {
    "total_friction_points": 8,
    "last_synced": "2025-07-19T11:55:00Z"
  }
}
```

## 2. Read the lessons learned

```bash
# The living memory organ — YAML frontmatter + markdown
cat memory/evolution/LESSONS_LEARNED.md
```

Example content:
```markdown
---
friction_points:
  - id: f-1
    category: repair_loop
    severity: warning
    created: 2025-07-19
    description: Gene g-12 caused 3 consecutive repair failures
    resolution: Banned gene g-12 for 8 cycles
  - id: f-2
    category: preflight_abort
    severity: info
    created: 2025-07-18
    description: System load exceeded threshold during peak hours
    resolution: Auto-adjusted cycle interval
---

# Lessons Learned

## Repair Loop (2025-07-19)
Gene g-12 produced 3 consecutive failed repair cycles. The repair-loop
circuit breaker triggered degraded mode — g-12 was banned for 8 cycles.
Investigate whether the root cause is in g-12's mutation strategy or
external state changes.

## Preflight Abort (2025-07-18)
...
```

## 3. Inspect autopoiesis rules

```bash
# Autopoiesis guard rules (friction auto-encoded as rules)
cat memory/evolution/autopoiesis_rules.json
```

Example:
```json
[
  {
    "id": "rule-1",
    "type": "gene_ban",
    "gene_id": "g-12",
    "reason": "3 consecutive repair failures",
    "duration_cycles": 8,
    "created_at": "2025-07-19T11:55:00Z"
  },
  {
    "id": "rule-2",
    "type": "risk_adjust",
    "category": "repair",
    "adjustment": "degrade",
    "reason": "repair_loop_detected",
    "created_at": "2025-07-19T11:50:00Z"
  }
]
```

## 4. Read the autopoiesis log

```bash
# Append-only log of every autopoiesis tick
cat memory/evolution/autopoiesis.jsonl
```

Each line is a JSON object with `id`, `timestamp`, `self_report`, `viability`, `homeostasis`.

## 5. Check the WebUI for autopoiesis data

```bash
uv run evolver webui --port 8080
```

The "Autopoiesis" panel shows:
- Viability score and status (stable/stressed/critical)
- Friction point count and categories
- Evolution rules count
- Homeostasis actions taken

## 6. Control autopoiesis behavior

```bash
# Disable autopoiesis self-check
EVOLVER_AUTOPOIESIS=0 uv run evolver --loop

# Enable but don't write (dry-run mode)
EVOLVER_AUTOPOIESIS=1 EVOLVER_AUTOPOIESIS_WRITE=0 uv run evolver run

# Full autopoiesis (default)
EVOLVER_AUTOPOIESIS=1 EVOLVER_AUTOPOIESIS_WRITE=1 uv run evolver --loop
```

## 7. Troubleshooting

| Symptom | Solution |
|---------|----------|
| No self-report data | Run at least one cycle first; reports are generated per-cycle |
| `LESSONS_LEARNED.md` is empty | Set `EVOLVER_AUTOPOIESIS_WRITE=1` to persist |
| No autopoiesis rules | Friction must be detected first; run `--loop` for several cycles |
| WebUI shows "暂无 Autopoiesis 数据" | Wait for next cycle or check `--no-write` mode |
