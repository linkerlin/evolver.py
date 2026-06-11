# Skill: evolver.py — Self-Evolving Agent Runtime

## Description

A Python port of the EvoMap evolver engine — a self-evolving agent runtime that uses Genetic Evolution Protocol (GEP) to mutate its own codebase based on signals extracted from IDE sessions, test results, and Hub interactions.

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Using pip
pip install -e .
```

## Quick Reference

### CLI Commands

| Command | Description |
|---|---|
| `evolver` | Run a single evolution cycle |
| `evolver --loop` | Daemon mode: continuous cycles |
| `evolver --review` | Review pending solidify state |
| `evolver webui` | Start the observability dashboard |
| `evolver proxy` | Start the local A2A Proxy |
| `evolver start` | Start the daemon (cross-platform) |
| `evolver stop` | Stop the daemon |
| `evolver status` | Show daemon status |
| `evolver atp status` | Show ATP marketplace status |

### Proxy API

The local proxy exposes REST endpoints at `http://127.0.0.1:19820`:

- `POST /v1/a2a/proxy/{path}` — Forward to Hub
- `POST /mailbox/send` — Send message to Hub
- `POST /mailbox/poll` — Poll inbound messages
- `POST /mailbox/ack` — Acknowledge messages
- `GET /proxy/status` — Proxy health

### WebUI API

The dashboard API runs at `http://127.0.0.1:8080`:

- `GET /api/status` — System health
- `GET /api/assets` — Gene / capsule list
- `GET /api/assets/{id}` — Asset detail
- `GET /api/candidates` — Candidate genes
- `GET /api/runs` — Evolution run history
- `GET /api/safety` — Safety events
- `GET /api/logs` — SSE log stream

### ATP Marketplace

- **Auto-buyer**: Discovers capability gaps and purchases services automatically.
- **Auto-deliver**: Claims tasks from the Hub, executes them, and submits proof.
- **Consumer agent**: Manages order lifecycle (order → confirm → settle/dispute).
- **Merchant agent**: Registers local skills as ATP services.

## Files

- `README.md` — Project overview
- `CONTRIBUTING.md` — Development guide
- `TODO.md` — Roadmap and gap analysis
- `设计方案.md` — Chinese design document

## Dependencies

- Python 3.12+
- `uv` (package manager)
- `httpx`, `fastapi`, `pydantic`, `psutil`

## Author

EvoMap Contributors
