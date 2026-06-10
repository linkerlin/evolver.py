# 🧬 evolver.py
[【中文】](README.zh.md)

Python 3.12+ port of [`@evomap/evolver`](https://github.com/EvoMap/evolver), a GEP-powered self-evolution engine for AI agents.

This port aims for **full behavioral equivalence** with the Node.js reference implementation while using modern Python tooling:

- **Python 3.12+** — `asyncio`, type parameter syntax, `tomllib`
- **uv** — fast Python package management
- **Pydantic v2** — schema validation and settings
- **httpx** — async HTTP client (equivalent to Node `undici`)
- **FastAPI + uvicorn** — local Proxy and WebUI

## Quick Start

```bash
# Install dependencies
uv sync

# Run a single evolution cycle
uv run evolver

# Daemon loop
uv run evolver --loop

# Review mode
uv run evolver --review
```

## Project Structure

See `设计方案.md` for the comprehensive design document (in Chinese, matching the source repo's documentation language).

## License

GPL-3.0-or-later
