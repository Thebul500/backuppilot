# Contributing to BackupPilot

Thank you for considering contributing to BackupPilot. This document provides guidelines for contributing code, reporting bugs, and suggesting features.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/Thebul500/backuppilot.git
cd backuppilot

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
pip install pytest-cov bandit types-defusedxml
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=backuppilot --cov-report=term-missing

# Integration tests only
pytest tests/ -m integration -v

# Single test file
pytest tests/test_checks.py -v
```

## Quality Gates

All contributions must pass these checks before merging:

```bash
# Lint
ruff check src/

# Type check
mypy src/backuppilot/

# Security scan
bandit -r src/backuppilot/ -ll

# Tests with coverage (minimum 80%)
pytest tests/ --cov=backuppilot --cov-fail-under=80

# Smoke test
backuppilot --help
```

## Code Style

- Python 3.11+ features are welcome (`X | None`, `match` statements)
- Use `from __future__ import annotations` in all modules
- Follow ruff defaults with 100-character line length
- Type-annotate all function signatures
- Docstrings for all public functions (Google style)

## Adding a New Check

1. Add the check function to `src/backuppilot/checks.py`
2. Return a `CheckResult` dataclass
3. Wire it into the appropriate validator in `src/backuppilot/cli.py`
4. Add unit tests in `tests/test_checks.py`
5. Add integration tests in `tests/test_integration.py`
6. Update the config schema in `src/backuppilot/config.py` if needed

## Pull Request Process

1. Fork the repository and create a feature branch
2. Make your changes with tests
3. Ensure all quality gates pass
4. Write a clear PR description explaining what and why
5. Reference any related issues

## Reporting Bugs

Open a GitHub issue with:
- BackupPilot version (`backuppilot --version`)
- Python version (`python3 --version`)
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output

## Feature Requests

Open a GitHub issue with the `enhancement` label. Include:
- Use case description
- Proposed behavior
- Why existing features don't solve the problem
