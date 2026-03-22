# BackupPilot - Competitive Analysis

## Overview

BackupPilot occupies a niche between heavyweight enterprise backup suites and ad-hoc shell scripts. It focuses specifically on **backup validation** (not backup creation), targeting homelab operators who already have backup pipelines but lack systematic verification.

## Competing Tools

### 1. Restic (`restic check`)

**What it does**: Built-in integrity verification for restic repositories. Checks pack files, index consistency, and optionally reads all data blobs.

**Strengths**: Deep integration with restic's content-addressable storage; cryptographic verification; `--read-data` option for full bit-rot detection.

**Limitations**: Only works with restic-format repositories. Cannot validate arbitrary tar.gz archives, OPNsense XML configs, or remote file presence. No notification system. No historical tracking of check results over time.

**BackupPilot advantage**: Validates heterogeneous backup formats (tar.gz, XML, rclone remotes) in a single tool. Tracks check history in SQLite for trend analysis.

### 2. BorgBackup (`borg check`)

**What it does**: Repository and archive consistency checks. Verifies metadata, segment structure, and optionally data integrity.

**Strengths**: Deduplication-aware verification. Repair mode can fix some corruption. Well-documented with clear error messages.

**Limitations**: Borg-only repositories. No multi-source validation. No notification integration. No concept of "expected contents" validation (e.g., verifying that specific Docker volumes exist in a backup).

**BackupPilot advantage**: Content-aware validation (expected volumes, expected OPNsense config sections). Signal notifications. Configuration-driven expected-value checks.

### 3. Bacula Verify

**What it does**: Post-backup verification in the Bacula enterprise backup suite. Three modes: catalog-only, volume-to-catalog, and disk-to-catalog comparison.

**Strengths**: Enterprise-grade with job scheduling, multi-client support, and detailed reporting. Integrates with Bacula Director for automated workflows.

**Limitations**: Massive complexity -- requires Director, Storage Daemon, File Daemon, and PostgreSQL/MySQL. Overkill for homelab. Configuration is notoriously difficult. Only validates Bacula-managed backups.

**BackupPilot advantage**: Zero infrastructure required (single pip install). Validates any backup format. Config in one YAML file vs. hundreds of lines of Bacula config.

### 4. Veeam Backup Validator

**What it does**: SureBackup and SureReplica features verify backup recoverability by booting VMs from backups in an isolated sandbox.

**Strengths**: Actual recovery testing (boots the backup). Application-level verification (can run scripts inside restored VMs). Enterprise support and reporting.

**Limitations**: Windows/VMware/Hyper-V only. Requires Veeam license ($$$). Not applicable to Docker volumes or firewall configs. Cloud-first approach doesn't fit airgapped homelabs.

**BackupPilot advantage**: Free, open-source, runs on Linux. Purpose-built for homelab infrastructure (Docker, OPNsense, GDrive). The `restore-test` command provides a lightweight version of Veeam's recovery testing.

### 5. Custom Shell Scripts

**What it does**: Most homelab operators write bash scripts that check file age, size, and maybe run `tar -tzf`.

**Strengths**: Infinitely customizable. No dependencies. Operators understand their own scripts.

**Limitations**: No error handling standards. No history tracking. No structured output (JSON). Notification is usually a bolted-on `curl` call. Scripts grow organically and become unmaintainable. No testing.

**BackupPilot advantage**: Structured `CheckResult` data model. SQLite history with querying. JSON output for automation. Tested codebase. Extensible check system.

## Feature Comparison Matrix

| Feature | BackupPilot | restic check | borg check | Bacula | Veeam | Scripts |
|---------|:-----------:|:------------:|:----------:|:------:|:-----:|:-------:|
| tar.gz validation | Yes | No | No | No | No | Partial |
| XML config parsing | Yes | No | No | No | No | Rare |
| GDrive/rclone check | Yes | No | No | No | No | Partial |
| Content verification | Yes | Yes | Yes | Yes | Yes | Partial |
| Check history (DB) | Yes | No | No | Yes | Yes | No |
| Signal notifications | Yes | No | No | Email | Email | DIY |
| JSON output | Yes | JSON | JSON | No | API | No |
| Interactive setup | Yes | No | No | No | GUI | No |
| Restore testing | Yes | Partial | No | Yes | Yes | DIY |
| Zero infrastructure | Yes | Yes | Yes | No | No | Yes |
| Homelab-focused | Yes | Partial | Partial | No | No | Yes |

## Gaps BackupPilot Fills

1. **Multi-format validation**: No single existing tool validates Docker tar.gz archives, OPNsense XML configs, and rclone remotes together. BackupPilot unifies these under one CLI.

2. **Content-aware checks**: BackupPilot doesn't just check "is the file there?" -- it verifies expected Docker volumes exist inside archives and expected config sections exist in OPNsense XML.

3. **Validation history**: Shell scripts run and forget. BackupPilot stores every check result in SQLite, enabling trend analysis and failure investigation.

4. **Homelab-native notifications**: Signal messaging integration is purpose-built for privacy-conscious homelab operators, unlike enterprise email/Slack integrations.

5. **Lightweight restore testing**: The `restore-test` command extracts Docker backups to a temp directory and verifies contents without requiring VM infrastructure like Veeam's SureBackup.

6. **Configuration-driven**: All thresholds (max age, size range, expected contents) are in a single YAML file, making it trivial to adjust as infrastructure evolves.
