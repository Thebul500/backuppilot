# Changelog

All notable changes to BackupPilot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-22

### Added
- Docker backup validation: freshness, file size range, tar.gz integrity, expected volume contents
- OPNsense config validation: XML and XML.gz parsing with defusedxml, configurable expected sections
- Google Drive validation: rclone remote listing, file count, timestamp-based freshness checking
- Interactive configuration wizard (`backuppilot init`)
- SQLite history database with WAL mode for concurrent access
- History browsing: list runs, view details, filter failures, JSON output
- History pruning to manage database size
- Restore testing: extract Docker backup to temp directory, verify contents, auto-cleanup
- Signal REST API notifications on check failure or every run
- JSON output mode for all commands (machine-readable for automation)
- Secure file permissions: 0o700 config directory, 0o600 config and database files
- Comprehensive test suite: 139 tests with 100% code coverage
- Integration tests with real file I/O and database operations
- CI pipeline (GitHub Actions) with lint, type check, security scan, and coverage
- Docker support: multi-stage build, non-root user, read-only backup mounts
- Kubernetes manifests: Deployment, Service, Kustomization
- Performance benchmarks for all core operations
- Full documentation: README, PLAN, ANALYSIS, SECURITY, CONTRIBUTING
- SBOM generation with CycloneDX
- Dependency audit with pip-audit
