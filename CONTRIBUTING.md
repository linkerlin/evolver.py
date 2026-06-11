# Contributing to evolver.py

Thank you for your interest in improving evolver.py! This document covers setup, coding standards, and submission guidelines.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/EvoMap/evolver.py.git
cd evolver.py

# Install dependencies (requires uv)
uv sync

# Run tests
uv run pytest tests/ -q
```

## Code Style

- **Formatter**: `ruff format`
- **Linter**: `ruff check --fix`
- **Type checker**: `mypy src/evolver` (optional but recommended)

All code must pass `ruff` before submission.

## Testing

- Write tests for every new module or bug fix.
- Place tests in `tests/` with the naming convention `test_<module>.py`.
- Use `pytest` fixtures and `monkeypatch` for isolation.
- Mock external HTTP calls with `respx` or `responses`.
- Aim for >80% coverage on new code.

## Commit Guidelines

- Use conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`
- Keep commits atomic and focused.
- Reference related issues when applicable.

## Pull Request Process

1. Fork the repository and create a feature branch.
2. Ensure all tests pass: `uv run pytest tests/ -q`
3. Update documentation if your change affects user-facing behavior.
4. Open a PR with a clear description of the change and motivation.

## Architecture Decisions

When making significant architectural changes, please open a discussion issue first. Key design principles:

- **Pythonic**: Prefer `pathlib`, `dataclasses`, `asyncio`, stdlib.
- **Atomic writes**: Use `tmp.write_text(...); tmp.replace(path)`.
- **Cross-platform**: Avoid shell commands; handle Windows/macOS/Linux differences explicitly.
- **Minimal changes**: Make the smallest change that achieves the goal.

## Security

- Never commit secrets, tokens, or private keys.
- Use `evolver.gep.sanitize` to redact sensitive data before logging or publishing.
- Report security vulnerabilities privately to the maintainers.
