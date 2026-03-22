"""Validation checks for backup files."""

from __future__ import annotations

import gzip
import shutil
import subprocess  # nosec B404 -- used safely without shell=True
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET


def _resolve_executable(name: str) -> str:
    """Resolve an executable to its full absolute path via shutil.which."""
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"{name} not found in PATH")
    return path


@dataclass
class CheckResult:
    """Result of a single validation check."""

    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_freshness(path: Path, max_age_hours: float) -> CheckResult:
    """Check that file mtime is within max_age_hours."""
    if not path.exists():
        return CheckResult("freshness", False, f"File not found: {path}")
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    passed = age_hours <= max_age_hours
    msg = f"{age_hours:.1f}h old" + ("" if passed else f" (max {max_age_hours}h)")
    return CheckResult("freshness", passed, msg, {"age_hours": round(age_hours, 1)})


def check_integrity(path: Path) -> CheckResult:
    """Verify tar.gz archive is not corrupted."""
    if not path.exists():
        return CheckResult("integrity", False, f"File not found: {path}")
    try:
        tar_bin = _resolve_executable("tar")
        subprocess.run(  # nosec B603
            [tar_bin, "tzf", str(path)],
            capture_output=True,
            check=True,
            timeout=120,
        )
        return CheckResult("integrity", True, "Archive OK")
    except FileNotFoundError:
        return CheckResult("integrity", False, "tar not found in PATH")
    except subprocess.CalledProcessError as e:
        return CheckResult(
            "integrity", False, f"Corrupt archive: {e.stderr.decode()[:200]}"
        )
    except subprocess.TimeoutExpired:
        return CheckResult("integrity", False, "Integrity check timed out (>120s)")


def check_size(path: Path, min_bytes: int, max_bytes: int) -> CheckResult:
    """Verify file size is within expected range."""
    if not path.exists():
        return CheckResult("size", False, f"File not found: {path}")
    size = path.stat().st_size
    size_mb = size / (1024 * 1024)
    min_mb = min_bytes / (1024 * 1024)
    max_mb = max_bytes / (1024 * 1024)
    passed = min_bytes <= size <= max_bytes
    msg = f"{size_mb:.1f}MB" + (
        "" if passed else f" (expected {min_mb:.0f}-{max_mb:.0f}MB)"
    )
    return CheckResult("size", passed, msg, {"size_mb": round(size_mb, 1)})


def check_opnsense_config(path: Path, expected_sections: list[str]) -> CheckResult:
    """Parse XML config (plain or gzipped) and verify expected sections exist.

    Uses the sections list from config rather than a hardcoded list.
    """
    if not path.exists():
        return CheckResult("opnsense_config", False, f"File not found: {path}")
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as f:
                root = ET.fromstring(f.read())
        else:
            tree = ET.parse(path)
            parsed_root = tree.getroot()
            if parsed_root is None:
                return CheckResult("opnsense_config", False, "Empty XML document")
            root = parsed_root
    except ET.ParseError as e:
        return CheckResult("opnsense_config", False, f"Invalid XML: {e}")
    except gzip.BadGzipFile as e:
        return CheckResult("opnsense_config", False, f"Corrupt gzip: {e}")
    except Exception as e:
        return CheckResult("opnsense_config", False, f"Failed to read config: {e}")

    found = [s for s in expected_sections if root.find(s) is not None]
    missing = [s for s in expected_sections if s not in found]

    if missing:
        return CheckResult(
            "opnsense_config",
            False,
            f"Missing sections: {', '.join(missing)}",
            {"found": found, "missing": missing},
        )
    return CheckResult(
        "opnsense_config",
        True,
        f"All {len(expected_sections)} sections present",
        {"found": found},
    )


def check_docker_contents(path: Path, expected_volumes: list[str]) -> CheckResult:
    """List tar contents and verify expected volume directories exist."""
    if not path.exists():
        return CheckResult("docker_contents", False, f"File not found: {path}")
    try:
        tar_bin = _resolve_executable("tar")
        result = subprocess.run(  # nosec B603
            [tar_bin, "tzf", str(path)],
            capture_output=True,
            check=True,
            timeout=120,
        )
        entries = result.stdout.decode()
    except FileNotFoundError:
        return CheckResult("docker_contents", False, "tar not found in PATH")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return CheckResult("docker_contents", False, f"Cannot read archive: {e}")

    found = []
    missing = []
    for vol in expected_volumes:
        if any(vol in entry for entry in entries.splitlines()):
            found.append(vol)
        else:
            missing.append(vol)

    if missing:
        return CheckResult(
            "docker_contents",
            False,
            f"Missing volumes: {', '.join(missing)}",
            {"found": found, "missing": missing},
        )
    return CheckResult(
        "docker_contents",
        True,
        f"All {len(expected_volumes)} volumes present",
        {"found": found},
    )


def check_gdrive(
    remote_path: str,
    max_age_hours: float,
    expected_files: int = 1,
) -> CheckResult:
    """Check rclone remote for recent backup files.

    Parses rclone lsl timestamps and validates file ages, not just counts.
    """
    try:
        rclone_bin = _resolve_executable("rclone")
        result = subprocess.run(  # nosec B603
            [rclone_bin, "lsl", remote_path],
            capture_output=True,
            check=True,
            timeout=60,
        )
        lines = [ln.strip() for ln in result.stdout.decode().splitlines() if ln.strip()]
    except FileNotFoundError:
        return CheckResult(
            "gdrive", False, "rclone is not installed. Install from https://rclone.org/install/"
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode()[:200] if e.stderr else "unknown error"
        return CheckResult("gdrive", False, f"rclone error: {stderr}")
    except subprocess.TimeoutExpired:
        return CheckResult("gdrive", False, "rclone timed out (>60s)")

    if not lines:
        return CheckResult("gdrive", False, "No files found on remote")

    file_count = len(lines)

    if file_count < expected_files:
        return CheckResult(
            "gdrive",
            False,
            f"Only {file_count} file(s) on remote (expected {expected_files})",
            {"file_count": file_count},
        )

    # Parse timestamps from rclone lsl output
    # Format: "  size YYYY-MM-DD HH:MM:SS.nnnnnnnnn filename"
    now = datetime.now(timezone.utc)
    stale_files: list[str] = []
    fresh_count = 0

    for line in lines:
        parts = line.split()
        if len(parts) >= 4:
            try:
                date_str = parts[1]  # YYYY-MM-DD
                time_str = parts[2].split(".")[0]  # HH:MM:SS (strip nanoseconds)
                dt = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                age_hours = (now - dt).total_seconds() / 3600
                filename = " ".join(parts[3:])
                if age_hours > max_age_hours:
                    stale_files.append(f"{filename} ({age_hours:.0f}h old)")
                else:
                    fresh_count += 1
            except (ValueError, IndexError):
                # Could not parse timestamp -- count as present but unknown age
                fresh_count += 1

    if stale_files and fresh_count == 0:
        return CheckResult(
            "gdrive",
            False,
            f"All {file_count} file(s) are stale (>{max_age_hours}h)",
            {"stale_files": stale_files, "file_count": file_count},
        )

    msg = f"{file_count} file(s) on remote"
    if fresh_count > 0:
        msg += f", {fresh_count} fresh"
    if stale_files:
        msg += f", {len(stale_files)} stale"

    return CheckResult(
        "gdrive",
        True,
        msg,
        {
            "file_count": file_count,
            "fresh_count": fresh_count,
            "stale_files": stale_files,
        },
    )
