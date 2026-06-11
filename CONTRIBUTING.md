# Contributing to evolver.py

Thank you for your interest in improving evolver.py! This document covers setup, coding standards, and submission guidelines.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/EvoMap/evolver.py.git
cd evolver.py

# Install dependencies (requires uv >= 0.5)
uv sync

# Verify installation
uv run evolver --version

# Run tests (CI default: exclude slow)
uv run pytest -m "not slow" -q

# Run all tests including slow
uv run pytest tests/ -q

# Run tests with coverage
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# Run linting
uv run ruff check src tests

# Run type checking (strict, 177 source files)
uv run mypy src
```

### Using pip instead of uv

If you prefer not to use `uv`:

```bash
pip install -e ".[dev,test]"
pytest tests/ -q
```

## Code Style

- **Formatter**: `ruff format` (line width 100)
- **Linter**: `ruff check --fix`
  - Enabled rules: `E, F, W, I, N, UP, B, C4, SIM, ARG, PL, RUF`
  - Intentionally suppressed: `PLR2004` (magic values), `PLR0913` (many arguments inherited from Node API)
- **Type checker**: `mypy src` with `strict = true`
- **Python version**: 3.12+ syntax required (`from __future__ import annotations`, `X | None`, `list[str]`)

All new code must pass `uv run mypy src` (strict) before submission. The full `ruff check` suite may report pre-existing style warnings; fix any issues in files you touch.

Current baseline (2026-06-11): **1218 tests** (`pytest`), **mypy 0 errors**.

## Testing

- Write tests for every new module or bug fix.
- Place tests in `tests/` with the naming convention `test_<module>.py`.
- Use `pytest` fixtures and `monkeypatch` for isolation.
- Mock external HTTP calls with `respx` or `responses`.
- Use `freezegun` for time-related tests.
- Aim for >80% coverage on new code.
- Test files should mirror source structure: `tests/gep/test_asset_store.py` tests `evolver.gep.asset_store`.

### Test Isolation Rules

- Always use `monkeypatch.setenv` to modify environment variables, never `os.environ` directly.
- Use the `temp_workspace` fixture from `conftest.py` to isolate path-related tests.
- Git-related tests should initialize a fresh git repo: `subprocess.run(["git", "init", "-q"])`.
- Do not modify `src/evolver/assets/gep/genes.seed.json` in tests; use `GEP_ASSETS_DIR` override.

## Commit Guidelines

- Use conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`
- Keep commits atomic and focused.
- Reference related issues when applicable.
- Format: `[<subsystem>] <description>` for clarity, e.g. `[gep] add file locking to asset_store`

## Pull Request Process

1. Fork the repository and create a feature branch.
2. Ensure all tests pass: `uv run pytest tests/ -q`
3. Ensure lint passes: `uv run ruff check src tests`
4. Ensure type check passes: `uv run mypy src`
5. Update documentation if your change affects user-facing behavior (`README.md`, `AGENTS.md`, `SKILL.md`).
6. If modifying architecture or adding new modules, update `设计方案.md` and `TODO.md` accordingly.
7. Open a PR with a clear description of the change and motivation.

## Architecture Decisions

When making significant architectural changes, please open a discussion issue first. Key design principles:

- **Pythonic**: Prefer `pathlib`, `dataclasses`, `asyncio`, stdlib.
- **Atomic writes**: Use `tmp.write_text(...); tmp.replace(path)`.
- **Cross-platform**: Avoid shell commands; handle Windows/macOS/Linux differences explicitly.
- **Minimal changes**: Make the smallest change that achieves the goal.
- **Behavior equivalence**: When in doubt, check the Node.js reference implementation's tests for the expected behavior.

### Module-Level Guidelines

- Every source file must have a top-level docstring referencing its Node.js equivalent (e.g., "Equivalent to `evolver/src/gep/assetStore.js`").
- All public functions must have type annotations.
- Pydantic models should use `ConfigDict(extra="forbid")` to reject unknown fields.
- Use lazy imports in `cli.py` and `guards.py` to avoid loading heavy modules before `.env` is loaded.

## Documentation Updates

When adding or modifying features, update the relevant documentation:

- User-facing changes → `README.md` and `README.zh.md`
- Agent integration changes → `AGENTS.md`
- Skill/capability changes → `SKILL.md`
- Architecture changes → `设计方案.md`
- Gap analysis changes → `TODO.md`

## Security

- Never commit secrets, tokens, or private keys.
- Use `evolver.gep.sanitize` to redact sensitive data before logging or publishing.
- All shell commands must use `subprocess.run([...], shell=False)`.
- Report security vulnerabilities privately to the maintainers.

## Implementation Status Transparency

When contributing to partially implemented subsystems, please be transparent about the scope:

- If implementing a previously missing module, remove it from the "missing" lists in `TODO.md` and update its status in `设计方案.md`.
- If adding a stub or placeholder, mark it clearly with `pass` and a `# TODO:` comment referencing the relevant issue or roadmap item.
- Do not mark features as "complete" in documentation unless they have corresponding tests.
