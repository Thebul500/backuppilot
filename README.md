# BackupPilot

[![CI](https://github.com/Thebul500/backuppilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Thebul500/backuppilot/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Coverage: 80%+](https://img.shields.io/badge/coverage-80%25%2B-brightgreen.svg)](BENCHMARKS.md)

Backup lifecycle manager for home infrastructure. Validates Docker volume archives, OPNsense firewall configs, and Google Drive remote backups against configurable health criteria.

## Quick Start

```bash
# Install
pip install -e .

# Interactive setup
backuppilot init

# Run all checks
backuppilot check

# Run a specific check type
backuppilot check --type docker
backuppilot check --type opnsense
backuppilot check --type gdrive
```

## Install

### From Source

```bash
git clone https://github.com/Thebul500/backuppilot.git
cd backuppilot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### With Docker

```bash
docker build -t backuppilot .
docker run --rm -v ~/.backuppilot:/home/backuppilot/.backuppilot backuppilot check
```

## Usage

### Configuration

Run `backuppilot init` for an interactive setup wizard, or create `~/.backuppilot/config.yaml` manually:

```yaml
docker:
  backup_dir: /path/to/docker/backups
  max_age_hours: 170
  min_size_mb: 500
  max_size_mb: 3000
  expected_volumes:
    - pihole
    - grafana
    - prometheus
    - n8n
    - vaultwarden
    - nginx-proxy-manager

opnsense:
  backup_dir: /path/to/opnsense/backups
  max_age_hours: 170
  expected_sections:
    - system
    - interfaces
    - filter

gdrive:
  remote: "gdrive:Infrastructure-Backups/"
  max_age_hours: 170
  expected_files: 2
```

### Commands

| Command | Description |
|---------|-------------|
| `backuppilot init` | Interactive configuration wizard |
| `backuppilot check` | Run all validation checks |
| `backuppilot check --type docker` | Validate Docker backups only |
| `backuppilot check --json-output` | Output results as JSON |
| `backuppilot check --notify` | Send Signal alert on failure |
| `backuppilot check --always-notify` | Send Signal alert on every run |
| `backuppilot history` | Show recent validation runs |
| `backuppilot history --failures` | Show failed checks only |
| `backuppilot history --run 5` | Show details for run #5 |
| `backuppilot history --json-output` | Output history as JSON |
| `backuppilot restore-test` | Extract newest Docker backup and verify |
| `backuppilot prune --keep 50` | Delete old history, keep last 50 runs |
| `backuppilot serve` | Start the REST API server on port 8392 |
| `backuppilot serve --port 9000` | Start API on custom port |

### REST API

Install server dependencies and start the API:

```bash
pip install -e ".[server]"
export BACKUPPILOT_API_KEY="your-secret-key"
backuppilot serve --host 127.0.0.1 --port 8392
```

All endpoints except `/health` require Bearer token authentication via the `BACKUPPILOT_API_KEY` environment variable.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/health` | No | Health check (version, config status) |
| POST | `/api/check` | Yes | Run backup validation |
| GET | `/api/history` | Yes | List validation history |
| GET | `/api/history/{run_id}` | Yes | Get run details |
| GET | `/api/status` | Yes | Current backup status |
| DELETE | `/api/history/prune` | Yes | Prune old history |

**Examples:**

```bash
# Health check (no auth)
curl http://localhost:8392/health

# Run Docker check
curl -X POST http://localhost:8392/api/check \
  -H "Authorization: Bearer $BACKUPPILOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"types": ["docker"]}'

# Get current status
curl http://localhost:8392/api/status \
  -H "Authorization: Bearer $BACKUPPILOT_API_KEY"

# List recent history (limit to 5, failures only)
curl "http://localhost:8392/api/history?limit=5&failures_only=true" \
  -H "Authorization: Bearer $BACKUPPILOT_API_KEY"

# Prune old runs
curl -X DELETE http://localhost:8392/api/history/prune \
  -H "Authorization: Bearer $BACKUPPILOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"keep_days": 50}'
```

### Signal Notifications

Set environment variables to enable Signal alerts:

```bash
export SIGNAL_API_URL="http://127.0.0.1:8082/v2/send"
export SIGNAL_SENDER="+16304926987"
export SIGNAL_RECIPIENT="+17028858681"
```

### Cron Integration

```bash
# Daily backup validation at 5:30 AM
30 5 * * * cd ~ && .venv/bin/backuppilot check --notify 2>&1 | logger -t backuppilot
```

## Architecture

```
backuppilot check
    |
    +---> Docker: freshness, size, tar.gz integrity, volume contents
    +---> OPNsense: freshness, XML parsing (defusedxml), config sections
    +---> GDrive: rclone remote listing, file count, timestamp freshness
    |
    v
CheckResult[] --> Table/JSON report --> SQLite history
                                    --> Signal notification (optional)
```

### Modules

| Module | Purpose |
|--------|---------|
| `api.py` | FastAPI REST API with Bearer token auth |
| `checks.py` | Core validation functions returning `CheckResult` dataclasses |
| `cli.py` | Click command group with 6 commands (including `serve`) |
| `config.py` | YAML config management with secure permissions |
| `db.py` | SQLite WAL-mode persistence for check history |
| `notify.py` | Signal REST API notifications via stdlib urllib |

### Validation Checks

**Docker Backups** (`*.tar.gz`):
- Freshness: file modification time within configured hours
- Size range: between min and max MB thresholds
- Integrity: `tar tzf` verifies archive is not corrupted
- Contents: expected Docker volume directories exist inside archive

**OPNsense Configs** (`*.xml`, `*.xml.gz`):
- Freshness: file modification time within configured hours
- Config parsing: XML parsed with defusedxml (XXE-safe)
- Section verification: expected config sections (system, interfaces, filter) present

**Google Drive** (via rclone):
- File count: minimum expected files on remote
- Freshness: parses rclone timestamps to detect stale uploads

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"
pip install pytest-cov bandit types-defusedxml

# Run tests
pytest tests/ -v

# Coverage (must be >= 100%)
pytest tests/ --cov=backuppilot --cov-report=term-missing

# Lint
ruff check src/

# Type check
mypy src/backuppilot/

# Security scan
bandit -r src/backuppilot/ -ll
```

## License

[MIT](LICENSE)
