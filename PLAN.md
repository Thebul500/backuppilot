# BackupPilot - Project Plan

## Architecture

BackupPilot is a Python CLI tool for backup lifecycle management in homelab infrastructure. It validates three backup sources (Docker volume archives, OPNsense firewall configs, and Google Drive remote storage) against configurable health criteria.

### System Design

```
User CLI (Click)
    |
    v
Validation Engine (_run_all)
    |
    +---> Docker Validator: freshness, size range, tar.gz integrity, expected volumes
    +---> OPNsense Validator: freshness, XML/XML.gz parsing, expected config sections
    +---> GDrive Validator: rclone remote listing, file count, timestamp freshness
    |
    v
CheckResult[] --> Report Printer (table/JSON)
    |              |
    v              v
SQLite History   Signal Notification (optional)
```

### Components

1. **checks.py** - Core validation checks. Each check produces a `CheckResult` dataclass with name, passed/failed, message, and optional details dict. Checks are pure functions operating on `Path` inputs. The `_resolve_executable()` helper ensures subprocess calls use absolute binary paths for security.

2. **cli.py** - Click command group with five commands:
   - `init` - Interactive configuration wizard
   - `check` - Runs validation checks (filterable by type, with JSON and notification options)
   - `history` - Browse SQLite history (list runs, view details, filter failures)
   - `restore-test` - Extract newest Docker backup to temp dir and verify contents
   - `prune` - Delete old history entries beyond a retention limit

3. **config.py** - YAML configuration management at `~/.backuppilot/config.yaml`. Secure file permissions (0o700 dir, 0o600 file). Interactive init prompts for all three backup source parameters.

4. **db.py** - SQLite persistence in WAL mode at `~/.backuppilot/history.db`. Two tables: `runs` (summary) and `results` (individual check outcomes with JSON details). Supports history queries, failure filtering, and pruning.

5. **notify.py** - Signal REST API notifications via stdlib `urllib`. Reads credentials from environment variables (`SIGNAL_API_URL`, `SIGNAL_SENDER`, `SIGNAL_RECIPIENT`). Formats multi-line reports with pass/fail icons.

### Data Flow

1. User runs `backuppilot check` (optionally with `--type`, `--notify`, `--json-output`)
2. Config loaded from YAML; section(s) selected based on check type
3. Validators run checks against real filesystem/remote targets
4. Results stored in SQLite history database
5. Report printed (formatted table or JSON)
6. If `--notify` or `--always-notify`, results sent via Signal

## Technology

| Technology | Role | Rationale |
|------------|------|-----------|
| **Python 3.11+** | Runtime | Type hints (`X | None`), `from __future__ import annotations`, widely available on homelab systems |
| **Click** | CLI framework | Declarative command groups, option parsing, colored output, version display |
| **defusedxml** | XML parsing | Prevents XXE attacks when parsing OPNsense configs (security-critical for firewall config files) |
| **PyYAML** | Config format | Human-readable config files, standard for infrastructure tooling |
| **SQLite (stdlib)** | History DB | Zero-dependency persistence, WAL mode for concurrent reads, no server needed |
| **subprocess** | tar/rclone | Calls system `tar` for archive validation and `rclone` for GDrive listing |
| **urllib (stdlib)** | Signal API | No external HTTP dependency needed for simple POST requests |

## Milestones

### v1.0.0 (Current)
- [x] Docker backup validation (freshness, size, integrity, contents)
- [x] OPNsense config validation (XML/XML.gz parsing, section verification)
- [x] GDrive remote validation via rclone (file count, timestamp freshness)
- [x] SQLite history with query, filter, and prune
- [x] Signal notifications on failure or always
- [x] Interactive configuration wizard
- [x] Restore-test command (extract to temp, verify, cleanup)
- [x] JSON output mode for all commands
- [x] 139 tests, 100% coverage

### v1.1.0 (Planned)
- [ ] Scheduled cron integration with lockfile
- [ ] Prometheus metrics endpoint for Grafana dashboards
- [ ] Backup size trending and anomaly detection
- [ ] Multi-host backup validation (SSH remote checks)

### v1.2.0 (Future)
- [ ] Web dashboard for history visualization
- [ ] Webhook notifications (Slack, Discord, email)
- [ ] Retention policy enforcement (auto-delete old backups)
- [ ] S3/MinIO backup source support
