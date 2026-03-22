"""CLI entry point for BackupPilot."""

from __future__ import annotations

import json
import subprocess  # nosec B404 -- used safely without shell=True
import sys
import tempfile
from pathlib import Path
from typing import Any

import click

from backuppilot.checks import CheckResult, _resolve_executable
from backuppilot.config import ConfigError, get_section, interactive_init, load_config, save_config
from backuppilot.db import get_failures, get_history, get_run_details, prune_history, store_run
from backuppilot.notify import NotifyError, send_signal


def _style_pass(text: str) -> str:
    return click.style(text, fg="green")


def _style_fail(text: str) -> str:
    return click.style(text, fg="red", bold=True)


def _print_report(results: list[CheckResult]) -> None:
    """Print check results as a formatted table."""
    click.echo()
    click.echo(click.style("  Backup Validation Results", bold=True))
    click.echo("  " + "-" * 60)
    for r in results:
        icon = _style_pass("[PASS]") if r.passed else _style_fail("[FAIL]")
        name = click.style(r.name, bold=True)
        click.echo(f"  {icon} {name}: {r.message}")
    click.echo("  " + "-" * 60)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    summary = f"  {passed}/{total} checks passed"
    if passed == total:
        click.echo(_style_pass(summary))
    else:
        click.echo(_style_fail(summary))
    click.echo()


def _report_to_dict(results: list[CheckResult]) -> dict[str, Any]:
    return {
        "passed": all(r.passed for r in results),
        "results": [
            {
                "name": r.name,
                "passed": r.passed,
                "message": r.message,
                "details": r.details,
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
    }


def _newest_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(
        directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return files[0] if files else None


# ---------------------------------------------------------------------------
# Validation runners (moved from validator.py -- keep CLI self-contained)
# ---------------------------------------------------------------------------

def _validate_docker(cfg: dict[str, Any]) -> list[CheckResult]:
    from backuppilot.checks import check_docker_contents, check_freshness, check_integrity, check_size

    section = get_section(cfg, "docker")
    backup_dir = Path(section["backup_dir"])
    if not backup_dir.exists():
        return [CheckResult("docker", False, f"Directory not found: {backup_dir}")]

    newest = _newest_file(backup_dir, "*.tar.gz")
    if not newest:
        return [CheckResult("docker", False, "No .tar.gz files found")]

    max_age = section.get("max_age_hours", 170)
    min_mb = section.get("min_size_mb", 500)
    max_mb = section.get("max_size_mb", 3000)
    volumes = section.get("expected_volumes", [])

    results: list[CheckResult] = []
    results.append(CheckResult("docker_file", True, newest.name))
    results.append(check_freshness(newest, max_age))
    results.append(check_size(newest, min_mb * 1024 * 1024, max_mb * 1024 * 1024))
    results.append(check_integrity(newest))
    if volumes:
        results.append(check_docker_contents(newest, volumes))
    return results


def _validate_opnsense(cfg: dict[str, Any]) -> list[CheckResult]:
    from backuppilot.checks import check_freshness, check_opnsense_config

    section = get_section(cfg, "opnsense")
    backup_dir = Path(section["backup_dir"])
    if not backup_dir.exists():
        return [CheckResult("opnsense", False, f"Directory not found: {backup_dir}")]

    newest = _newest_file(backup_dir, "*.xml*")
    if not newest:
        return [CheckResult("opnsense", False, "No .xml/.xml.gz files found")]

    max_age = section.get("max_age_hours", 170)
    expected_sections = section.get("expected_sections", ["system", "interfaces", "filter"])

    results: list[CheckResult] = []
    results.append(CheckResult("opnsense_file", True, newest.name))
    results.append(check_freshness(newest, max_age))
    results.append(check_opnsense_config(newest, expected_sections))
    return results


def _validate_gdrive(cfg: dict[str, Any]) -> list[CheckResult]:
    from backuppilot.checks import check_gdrive

    section = get_section(cfg, "gdrive")
    remote = section["remote"]
    max_age = section.get("max_age_hours", 170)
    expected = section.get("expected_files", 1)
    return [check_gdrive(remote, max_age, expected)]


def _run_all(check_type: str | None = None) -> list[CheckResult]:
    """Load config and run validation checks."""
    cfg = load_config()
    results: list[CheckResult] = []

    runners = {
        "docker": _validate_docker,
        "opnsense": _validate_opnsense,
        "gdrive": _validate_gdrive,
    }

    if check_type:
        if check_type not in runners:
            return [CheckResult("config", False, f"Unknown check type: {check_type}")]
        try:
            results.extend(runners[check_type](cfg))
        except ConfigError as e:
            results.append(CheckResult("config", False, str(e)))
    else:
        for name, runner in runners.items():
            try:
                results.extend(runner(cfg))
            except ConfigError:
                # Skip unconfigured sections in full run
                pass

    if not results:
        results.append(
            CheckResult("config", False, "No checks configured. Run 'backuppilot init'.")
        )

    return results


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="backuppilot")
def main() -> None:
    """BackupPilot -- backup lifecycle manager for home infrastructure."""


@main.command()
def init() -> None:
    """Interactive setup -- creates ~/.backuppilot/config.yaml."""
    try:
        config = interactive_init()
        path = save_config(config)
        click.echo()
        click.echo(_style_pass(f"Config saved to {path}"))
        click.echo("Run 'backuppilot check' to validate your backups.")
    except Exception as e:
        click.echo(_style_fail(f"Init failed: {e}"), err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--type", "check_type", type=click.Choice(["docker", "opnsense", "gdrive"]),
    help="Run only one check type.",
)
@click.option("--notify", is_flag=True, help="Send Signal alert on failure.")
@click.option("--always-notify", is_flag=True, help="Send Signal alert on every run.")
@click.option("--json-output", "use_json", is_flag=True, help="Output results as JSON.")
def check(
    check_type: str | None, notify: bool, always_notify: bool, use_json: bool
) -> None:
    """Run backup validation checks."""
    try:
        results = _run_all(check_type)
    except ConfigError as e:
        click.echo(_style_fail(str(e)), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(_style_fail(f"Unexpected error: {e}"), err=True)
        sys.exit(1)

    overall_passed = all(r.passed for r in results)

    # Store to history
    try:
        run_id = store_run(results)
    except Exception as e:
        click.echo(_style_fail(f"Failed to save history: {e}"), err=True)
        run_id = -1

    if use_json:
        data = _report_to_dict(results)
        data["run_id"] = run_id
        click.echo(json.dumps(data, indent=2))
    else:
        _print_report(results)
        if run_id >= 0:
            click.echo(click.style(f"  Run #{run_id} saved to history", dim=True))

    # Signal notifications
    should_notify = always_notify or (notify and not overall_passed)
    if should_notify:
        try:
            send_signal(results, overall_passed)
            if not use_json:
                click.echo(click.style("  Signal notification sent", dim=True))
        except NotifyError as e:
            if not use_json:
                click.echo(_style_fail(f"  Notification error: {e}"), err=True)

    if not overall_passed:
        sys.exit(1)


@main.command()
@click.option("-n", "--limit", default=10, help="Number of runs to show.")
@click.option("--failures", is_flag=True, help="Show only failed checks.")
@click.option("--days", default=30, help="Days to look back (with --failures).")
@click.option("--run", "run_id", type=int, help="Show details for a specific run.")
@click.option("--json-output", "use_json", is_flag=True, help="Output as JSON.")
def history(
    limit: int, failures: bool, days: int, run_id: int | None, use_json: bool
) -> None:
    """Show validation history from SQLite."""
    try:
        if run_id is not None:
            details = get_run_details(run_id)
            if not details:
                click.echo(_style_fail(f"No results found for run #{run_id}"))
                return
            if use_json:
                click.echo(json.dumps(details, indent=2))
            else:
                click.echo()
                click.echo(click.style(f"  Run #{run_id} Details", bold=True))
                click.echo("  " + "-" * 50)
                for d in details:
                    icon = _style_pass("[PASS]") if d["passed"] else _style_fail("[FAIL]")
                    click.echo(f"  {icon} {d['check_name']}: {d['message']}")
                click.echo()
            return

        if failures:
            fails = get_failures(days)
            if use_json:
                click.echo(json.dumps(fails, indent=2))
            elif not fails:
                click.echo(_style_pass(f"No failures in the last {days} days"))
            else:
                click.echo()
                click.echo(click.style(f"  Failures (last {days} days)", bold=True))
                click.echo("  " + "-" * 60)
                for f in fails:
                    ts = f["timestamp"][:19]
                    click.echo(
                        f"  Run #{f['run_id']} [{ts}] {f['check_name']}: {f['message']}"
                    )
                click.echo()
            return

        runs = get_history(limit)
        if use_json:
            click.echo(json.dumps(runs, indent=2))
        elif not runs:
            click.echo(
                click.style("No validation history. Run 'backuppilot check' first.", dim=True)
            )
        else:
            click.echo()
            click.echo(click.style(f"  Last {min(limit, len(runs))} Validation Runs", bold=True))
            click.echo("  " + "-" * 60)
            for r in runs:
                icon = _style_pass("PASS") if r["passed"] else _style_fail("FAIL")
                ts = r["timestamp"][:19]
                click.echo(
                    f"  #{r['id']:>4}  {ts}  {icon}  "
                    f"{r['total_checks']} checks, {r['failed_checks']} failed"
                )
            click.echo()
    except Exception as e:
        click.echo(_style_fail(f"Error reading history: {e}"), err=True)
        sys.exit(1)


@main.command("restore-test")
def restore_test() -> None:
    """Extract newest Docker backup to temp dir, verify, cleanup."""
    try:
        cfg = load_config()
        section = get_section(cfg, "docker")
    except ConfigError as e:
        click.echo(_style_fail(str(e)), err=True)
        sys.exit(1)

    backup_dir = Path(section["backup_dir"])
    if not backup_dir.exists():
        click.echo(_style_fail(f"Docker backup directory not found: {backup_dir}"), err=True)
        sys.exit(1)

    files = sorted(
        backup_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not files:
        click.echo(_style_fail("No Docker backup files found"), err=True)
        sys.exit(1)

    newest = files[0]
    size_mb = newest.stat().st_size / 1024 / 1024
    click.echo(f"Testing restore of {click.style(newest.name, bold=True)} ({size_mb:.1f}MB)")

    with tempfile.TemporaryDirectory(prefix="backuppilot-") as tmpdir:
        click.echo(f"Extracting to {tmpdir}...")
        try:
            tar_bin = _resolve_executable("tar")
            subprocess.run(  # nosec B603
                [tar_bin, "xzf", str(newest), "-C", tmpdir],
                check=True,
                capture_output=True,
                timeout=300,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode()[:300] if e.stderr else "unknown error"
            msg = f"Extraction failed: {stderr}"
            if "mknod" in stderr.lower() or "operation not permitted" in stderr.lower():
                msg += (
                    "\n\nHint: Docker backups may contain device nodes. "
                    "Try running with sudo: sudo backuppilot restore-test"
                )
            click.echo(_style_fail(msg), err=True)
            sys.exit(1)
        except subprocess.TimeoutExpired:
            click.echo(_style_fail("Extraction timed out (>5min)"), err=True)
            sys.exit(1)

        extracted = list(Path(tmpdir).rglob("*"))
        dirs = [p for p in extracted if p.is_dir()]
        files_found = [p for p in extracted if p.is_file()]

        click.echo(
            _style_pass(f"Extracted successfully: {len(dirs)} dirs, {len(files_found)} files")
        )

        expected = section.get("expected_volumes", [])
        if expected:
            top_dirs = {p.name for p in Path(tmpdir).iterdir() if p.is_dir()}
            found = [v for v in expected if any(v in d for d in top_dirs)]
            missing = [v for v in expected if v not in found]

            if missing:
                click.echo(
                    click.style(f"Missing volumes: {', '.join(missing)}", fg="yellow")
                )
            else:
                click.echo(_style_pass(f"All {len(expected)} expected volumes present"))

    click.echo(click.style("Temp directory cleaned up", dim=True))


@main.command()
@click.option("--keep", default=100, help="Number of recent runs to keep.")
def prune(keep: int) -> None:
    """Delete old history entries, keeping the most recent N runs."""
    try:
        deleted = prune_history(keep)
        if deleted:
            click.echo(f"Pruned {deleted} old run(s), kept {keep} most recent.")
        else:
            click.echo("Nothing to prune.")
    except Exception as e:
        click.echo(_style_fail(f"Prune failed: {e}"), err=True)
        sys.exit(1)


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", default=8392, type=int, help="Port number.")
def serve(host: str, port: int) -> None:
    """Start the BackupPilot REST API server."""
    try:
        import uvicorn  # lazy import -- don't break CLI-only usage
    except ImportError:
        click.echo(
            _style_fail(
                "Server dependencies not installed.\n"
                "Install with: pip install 'backuppilot[server]'"
            ),
            err=True,
        )
        sys.exit(1)

    click.echo(f"Starting BackupPilot API on {host}:{port}")
    uvicorn.run("backuppilot.api:app", host=host, port=port, log_level="info")
