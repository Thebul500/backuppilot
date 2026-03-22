"""Tests for validation checks."""

from __future__ import annotations

import gzip
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backuppilot.checks import (
    CheckResult,
    check_docker_contents,
    check_freshness,
    check_gdrive,
    check_integrity,
    check_opnsense_config,
    check_size,
)


class TestCheckFreshness:
    def test_fresh_file(self, docker_tar_gz: Path) -> None:
        result = check_freshness(docker_tar_gz, max_age_hours=24)
        assert result.passed
        assert "h old" in result.message

    def test_stale_file(self, docker_tar_gz: Path) -> None:
        # Set mtime to 72 hours ago
        old_time = time.time() - (72 * 3600)
        os.utime(docker_tar_gz, (old_time, old_time))
        result = check_freshness(docker_tar_gz, max_age_hours=48)
        assert not result.passed
        assert "max 48" in result.message

    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_freshness(tmp_path / "nonexistent.tar.gz", max_age_hours=24)
        assert not result.passed
        assert "not found" in result.message.lower()


class TestCheckIntegrity:
    def test_valid_archive(self, docker_tar_gz: Path) -> None:
        result = check_integrity(docker_tar_gz)
        assert result.passed
        assert result.message == "Archive OK"

    def test_corrupt_archive(self, tmp_path: Path) -> None:
        bad = tmp_path / "corrupt.tar.gz"
        bad.write_bytes(b"this is not a real archive")
        result = check_integrity(bad)
        assert not result.passed
        assert "corrupt" in result.message.lower() or "error" in result.message.lower()

    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_integrity(tmp_path / "missing.tar.gz")
        assert not result.passed


class TestCheckSize:
    def test_within_range(self, docker_tar_gz: Path) -> None:
        size = docker_tar_gz.stat().st_size
        result = check_size(docker_tar_gz, 0, size + 1024)
        assert result.passed

    def test_too_small(self, docker_tar_gz: Path) -> None:
        size = docker_tar_gz.stat().st_size
        result = check_size(docker_tar_gz, size + 1, size + 1024)
        assert not result.passed
        assert "expected" in result.message.lower()

    def test_too_large(self, docker_tar_gz: Path) -> None:
        result = check_size(docker_tar_gz, 0, 1)
        assert not result.passed

    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_size(tmp_path / "missing", 0, 100)
        assert not result.passed


class TestCheckOpnsenseConfig:
    def test_valid_xml(self, opnsense_xml: Path) -> None:
        result = check_opnsense_config(opnsense_xml, ["system", "interfaces", "filter"])
        assert result.passed
        assert "3 sections" in result.message

    def test_valid_xml_gz(self, opnsense_xml_gz: Path) -> None:
        result = check_opnsense_config(opnsense_xml_gz, ["system", "interfaces"])
        assert result.passed

    def test_missing_sections(self, opnsense_xml: Path) -> None:
        result = check_opnsense_config(opnsense_xml, ["system", "dhcpd"])
        assert not result.passed
        assert "dhcpd" in result.message

    def test_reads_sections_from_config(self, opnsense_xml: Path) -> None:
        """Verify the function uses the passed-in sections list, not hardcoded ones."""
        # Only check for 'system' -- should pass
        result = check_opnsense_config(opnsense_xml, ["system"])
        assert result.passed
        assert "1 sections" in result.message

    def test_invalid_xml(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.xml"
        bad.write_text("not xml at all <<<<")
        result = check_opnsense_config(bad, ["system"])
        assert not result.passed
        assert "invalid xml" in result.message.lower()

    def test_corrupt_gzip(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.xml.gz"
        bad.write_bytes(b"not gzipped")
        result = check_opnsense_config(bad, ["system"])
        assert not result.passed

    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_opnsense_config(tmp_path / "missing.xml", ["system"])
        assert not result.passed


class TestCheckDockerContents:
    def test_volume_present(self, docker_tar_gz: Path) -> None:
        result = check_docker_contents(docker_tar_gz, ["testvolume"])
        assert result.passed
        assert "1 volumes" in result.message

    def test_volume_missing(self, docker_tar_gz: Path) -> None:
        result = check_docker_contents(docker_tar_gz, ["nonexistent"])
        assert not result.passed
        assert "nonexistent" in result.message

    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_docker_contents(tmp_path / "missing.tar.gz", ["vol"])
        assert not result.passed


class TestCheckGdrive:
    def test_rclone_not_installed(self) -> None:
        with patch("backuppilot.checks._resolve_executable", side_effect=FileNotFoundError("rclone not found")):
            result = check_gdrive("gdrive:test/", 170)
        assert not result.passed
        assert "not installed" in result.message.lower() or "not found" in result.message.lower()

    def test_empty_remote(self) -> None:
        import subprocess
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
        with patch("backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"):
            with patch("subprocess.run", return_value=mock_result):
                result = check_gdrive("gdrive:test/", 170)
        assert not result.passed
        assert "no files" in result.message.lower()

    def test_files_present_and_fresh(self) -> None:
        import subprocess
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d %H:%M:%S.000000000")
        output = f"   1234567 {ts} backup1.tar.gz\n   2345678 {ts} backup2.tar.gz\n"
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output.encode(), stderr=b""
        )
        with patch("backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"):
            with patch("subprocess.run", return_value=mock_result):
                result = check_gdrive("gdrive:test/", 170, expected_files=2)
        assert result.passed
        assert "2 file(s)" in result.message
        assert "2 fresh" in result.message

    def test_all_files_stale(self) -> None:
        import subprocess

        # Timestamps from a year ago
        output = "   1234567 2025-01-01 00:00:00.000000000 old-backup.tar.gz\n"
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output.encode(), stderr=b""
        )
        with patch("backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"):
            with patch("subprocess.run", return_value=mock_result):
                result = check_gdrive("gdrive:test/", 170, expected_files=1)
        assert not result.passed
        assert "stale" in result.message.lower()

    def test_fewer_than_expected(self) -> None:
        import subprocess
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d %H:%M:%S.000000000")
        output = f"   1234567 {ts} backup1.tar.gz\n"
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output.encode(), stderr=b""
        )
        with patch("backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"):
            with patch("subprocess.run", return_value=mock_result):
                result = check_gdrive("gdrive:test/", 170, expected_files=3)
        assert not result.passed
        assert "expected 3" in result.message.lower()
