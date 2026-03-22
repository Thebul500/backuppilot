"""Tests to cover remaining uncovered lines and reach 100% coverage."""

from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from backuppilot.checks import (
    CheckResult,
    _resolve_executable,
    check_docker_contents,
    check_gdrive,
    check_integrity,
    check_opnsense_config,
)
from backuppilot.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# __main__.py  (lines 3-5)
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_module_invocation(self) -> None:
        """Importing __main__ calls main(); verify it's importable."""
        with patch("backuppilot.cli.main") as mock_main:
            # prevent actual CLI execution
            mock_main.side_effect = SystemExit(0)
            with pytest.raises(SystemExit):
                import importlib
                import backuppilot.__main__  # noqa: F811

                importlib.reload(backuppilot.__main__)


# ---------------------------------------------------------------------------
# checks.py gaps
# ---------------------------------------------------------------------------


class TestResolveExecutable:
    def test_not_found_raises(self) -> None:
        """_resolve_executable raises FileNotFoundError for missing binary (line 21)."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="nonexistent_bin not found"):
                _resolve_executable("nonexistent_bin")


class TestCheckIntegrityEdgeCases:
    def test_tar_not_in_path(self, docker_tar_gz: Path) -> None:
        """check_integrity returns failure when tar is not found (line 64)."""
        with patch(
            "backuppilot.checks._resolve_executable",
            side_effect=FileNotFoundError("tar not found in PATH"),
        ):
            result = check_integrity(docker_tar_gz)
        assert not result.passed
        assert "tar not found" in result.message.lower()

    def test_timeout(self, docker_tar_gz: Path) -> None:
        """check_integrity handles TimeoutExpired (lines 69-70)."""
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/tar"
        ):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="tar", timeout=120),
            ):
                result = check_integrity(docker_tar_gz)
        assert not result.passed
        assert "timed out" in result.message.lower()


class TestCheckOpnsenseConfigEdgeCases:
    def test_empty_xml_document(self, tmp_path: Path) -> None:
        """check_opnsense_config with empty root returns failure (line 103)."""
        # defusedxml.ElementTree.parse returns a tree whose getroot() could
        # theoretically return None; we mock that scenario.
        xml_path = tmp_path / "empty_root.xml"
        xml_path.write_text('<?xml version="1.0"?><opnsense/>')

        mock_tree = MagicMock()
        mock_tree.getroot.return_value = None
        with patch("backuppilot.checks.ET.parse", return_value=mock_tree):
            result = check_opnsense_config(xml_path, ["system"])
        assert not result.passed
        assert "empty xml" in result.message.lower()

    def test_generic_exception(self, tmp_path: Path) -> None:
        """check_opnsense_config catches generic exceptions (lines 109-110)."""
        xml_path = tmp_path / "error.xml"
        xml_path.write_text("<data/>")

        with patch(
            "backuppilot.checks.ET.parse", side_effect=OSError("disk error")
        ):
            result = check_opnsense_config(xml_path, ["system"])
        assert not result.passed
        assert "failed to read" in result.message.lower()


class TestCheckDockerContentsEdgeCases:
    def test_tar_not_in_path(self, docker_tar_gz: Path) -> None:
        """check_docker_contents returns failure when tar not found (line 143-144)."""
        with patch(
            "backuppilot.checks._resolve_executable",
            side_effect=FileNotFoundError("tar not found in PATH"),
        ):
            result = check_docker_contents(docker_tar_gz, ["testvolume"])
        assert not result.passed
        assert "tar not found" in result.message.lower()

    def test_called_process_error(self, docker_tar_gz: Path) -> None:
        """check_docker_contents handles CalledProcessError (lines 145-146)."""
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/tar"
        ):
            with patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    1, "tar", stderr=b"error reading archive"
                ),
            ):
                result = check_docker_contents(docker_tar_gz, ["testvolume"])
        assert not result.passed
        assert "cannot read" in result.message.lower()

    def test_timeout(self, docker_tar_gz: Path) -> None:
        """check_docker_contents handles TimeoutExpired (lines 145-146)."""
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/tar"
        ):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="tar", timeout=120),
            ):
                result = check_docker_contents(docker_tar_gz, ["testvolume"])
        assert not result.passed
        assert "cannot read" in result.message.lower()


class TestCheckGdriveEdgeCases:
    def test_rclone_timeout(self) -> None:
        """check_gdrive handles rclone timeout (lines 196-197)."""
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"
        ):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="rclone", timeout=60),
            ):
                result = check_gdrive("gdrive:test/", 170)
        assert not result.passed
        assert "timed out" in result.message.lower()

    def test_unparseable_timestamp(self) -> None:
        """check_gdrive counts files with unparseable timestamps as fresh (lines 233-235)."""
        output = "   1234567 BADDATE BADTIME backup.tar.gz\n"
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output.encode(), stderr=b""
        )
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = check_gdrive("gdrive:test/", 170, expected_files=1)
        assert result.passed
        assert "1 fresh" in result.message

    def test_mixed_stale_and_fresh(self) -> None:
        """check_gdrive with both stale and fresh files shows stale count (line 249)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        fresh_ts = now.strftime("%Y-%m-%d %H:%M:%S.000000000")
        output = (
            f"   1234567 {fresh_ts} fresh-backup.tar.gz\n"
            "   2345678 2020-01-01 00:00:00.000000000 old-backup.tar.gz\n"
        )
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output.encode(), stderr=b""
        )
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = check_gdrive("gdrive:test/", 170, expected_files=1)
        assert result.passed
        assert "1 fresh" in result.message
        assert "1 stale" in result.message

    def test_rclone_called_process_error(self) -> None:
        """check_gdrive handles rclone CalledProcessError (lines 193-195)."""
        with patch(
            "backuppilot.checks._resolve_executable", return_value="/usr/bin/rclone"
        ):
            with patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    1, "rclone", stderr=b"config not found"
                ),
            ):
                result = check_gdrive("gdrive:test/", 170)
        assert not result.passed
        assert "rclone error" in result.message.lower()


# ---------------------------------------------------------------------------
# config.py — interactive_init() (lines 73-158)
# ---------------------------------------------------------------------------


class TestInteractiveInit:
    def test_full_init_with_gdrive(self, tmp_config_dir: Path) -> None:
        """interactive_init() with GDrive enabled."""
        from backuppilot.config import interactive_init

        inputs = [
            "/tmp/docker",  # docker backup dir
            "170",  # max age
            "500",  # min size
            "3000",  # max size
            "pihole,grafana",  # expected volumes
            "/tmp/opnsense",  # opnsense backup dir
            "170",  # max age
            "system,interfaces,filter",  # expected sections
            # click.confirm is patched separately (returns True)
            "gdrive:backups/",  # remote path
            "170",  # max age
            "2",  # expected file count
        ]
        with patch("click.prompt", side_effect=inputs):
            with patch("click.confirm", return_value=True):
                config = interactive_init()

        assert "docker" in config
        assert config["docker"]["backup_dir"] == "/tmp/docker"
        assert config["docker"]["expected_volumes"] == ["pihole", "grafana"]

        assert "opnsense" in config
        assert config["opnsense"]["backup_dir"] == "/tmp/opnsense"

        assert "gdrive" in config
        assert config["gdrive"]["remote"] == "gdrive:backups/"

    def test_init_without_gdrive(self, tmp_config_dir: Path) -> None:
        """interactive_init() with GDrive declined."""
        from backuppilot.config import interactive_init

        inputs = [
            "/tmp/docker",
            "170",
            "500",
            "3000",
            "pihole",
            "/tmp/opnsense",
            "170",
            "system",
        ]
        with patch("click.prompt", side_effect=inputs):
            with patch("click.confirm", return_value=False):
                config = interactive_init()

        assert "docker" in config
        assert "opnsense" in config
        assert "gdrive" not in config


# ---------------------------------------------------------------------------
# cli.py gaps
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_init_success(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        """init command saves config on success (lines 187-193)."""
        mock_config = {"docker": {"backup_dir": "/tmp/test"}}
        with patch("backuppilot.cli.interactive_init", return_value=mock_config):
            result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "config saved" in result.output.lower()
        assert "backuppilot check" in result.output.lower()

    def test_init_failure(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        """init command handles exception (lines 193-195)."""
        with patch(
            "backuppilot.cli.interactive_init",
            side_effect=RuntimeError("wizard crashed"),
        ):
            result = runner.invoke(main, ["init"])
        assert result.exit_code != 0
        assert "init failed" in result.output.lower()


class TestCheckCommandGaps:
    def test_unexpected_error(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        """check command handles unexpected exceptions (lines 215-217)."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"docker": {"backup_dir": "/tmp"}}))
        with patch(
            "backuppilot.cli._run_all",
            side_effect=RuntimeError("something broke"),
        ):
            result = runner.invoke(main, ["check"])
        assert result.exit_code != 0
        assert "unexpected error" in result.output.lower()

    def test_store_run_failure(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        """check command handles store_run failure (lines 224-226)."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        with patch(
            "backuppilot.cli.store_run",
            side_effect=RuntimeError("db write failed"),
        ):
            result = runner.invoke(main, ["check", "--type", "docker"])
        assert result.exit_code == 0
        assert "failed to save history" in result.output.lower()

    def test_notify_success_message(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """check command prints signal notification sent (lines 242-243)."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        with patch("backuppilot.cli.send_signal"):
            result = runner.invoke(
                main, ["check", "--type", "docker", "--always-notify"]
            )
        assert result.exit_code == 0
        assert "signal notification sent" in result.output.lower()

    def test_config_error_for_specific_check(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """_run_all catches ConfigError for a specific check type (lines 155-156)."""
        # Config exists but gdrive section is malformed (not a dict)
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"gdrive": "not-a-dict"}))
        result = runner.invoke(main, ["check", "--type", "gdrive"])
        assert result.exit_code != 0
        assert "FAIL" in result.output


class TestRunAllUnknownType:
    def test_unknown_check_type(self, tmp_config_dir: Path) -> None:
        """_run_all returns error for unknown check type (line 152)."""
        from backuppilot.cli import _run_all

        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"docker": {"backup_dir": "/tmp"}}))
        results = _run_all("unknown_type")
        assert len(results) == 1
        assert not results[0].passed
        assert "unknown check type" in results[0].message.lower()


class TestHistoryCommandGaps:
    def test_history_exception(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        """history command handles exceptions (lines 317-319)."""
        with patch(
            "backuppilot.cli.get_history",
            side_effect=RuntimeError("db read failed"),
        ):
            result = runner.invoke(main, ["history"])
        assert result.exit_code != 0
        assert "error reading history" in result.output.lower()


class TestPruneCommandGaps:
    def test_prune_exception(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        """prune command handles exceptions (lines 406-408)."""
        with patch(
            "backuppilot.cli.prune_history",
            side_effect=RuntimeError("db prune failed"),
        ):
            result = runner.invoke(main, ["prune"])
        assert result.exit_code != 0
        assert "prune failed" in result.output.lower()


class TestRestoreTestCommand:
    def test_no_config(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        """restore-test with no config file (lines 325-330)."""
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0
        assert "config" in result.output.lower()

    def test_missing_docker_section(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """restore-test with config missing docker section (lines 328-330)."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"opnsense": {"backup_dir": "/tmp"}}))
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0

    def test_backup_dir_not_found(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """restore-test with non-existent docker backup dir (lines 333-335)."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(
            yaml.dump({"docker": {"backup_dir": "/nonexistent/path"}})
        )
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_no_tar_files(
        self, runner: CliRunner, tmp_config_dir: Path, tmp_path: Path
    ) -> None:
        """restore-test with empty backup dir (lines 340-342)."""
        empty_dir = tmp_path / "empty_backups"
        empty_dir.mkdir()
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(
            yaml.dump({"docker": {"backup_dir": str(empty_dir)}})
        )
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0
        assert "no docker backup" in result.output.lower()

    def test_successful_restore(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        """restore-test successfully extracts and verifies (lines 344-393)."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code == 0
        assert "extracted successfully" in result.output.lower()
        assert "expected volumes present" in result.output.lower()
        assert "cleaned up" in result.output.lower()

    def test_successful_restore_no_volumes(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        docker_tar_gz: Path,
    ) -> None:
        """restore-test without expected_volumes in config (lines 380-381)."""
        config = {
            "docker": {
                "backup_dir": str(docker_tar_gz.parent),
                "max_age_hours": 170,
                "min_size_mb": 0,
                "max_size_mb": 5000,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code == 0
        assert "extracted successfully" in result.output.lower()

    def test_restore_missing_volumes(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        docker_tar_gz: Path,
    ) -> None:
        """restore-test with some expected volumes missing (lines 386-389)."""
        config = {
            "docker": {
                "backup_dir": str(docker_tar_gz.parent),
                "max_age_hours": 170,
                "min_size_mb": 0,
                "max_size_mb": 5000,
                "expected_volumes": ["testvolume", "nonexistent_vol"],
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["restore-test"])
        assert result.exit_code == 0
        assert "missing volumes" in result.output.lower()

    def test_extraction_failure(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        docker_tar_gz: Path,
    ) -> None:
        """restore-test handles extraction failure (lines 358-367)."""
        config = {
            "docker": {
                "backup_dir": str(docker_tar_gz.parent),
                "max_age_hours": 170,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "tar", stderr=b"extraction error"
            ),
        ):
            result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0
        assert "extraction failed" in result.output.lower()

    def test_extraction_failure_with_mknod_hint(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        docker_tar_gz: Path,
    ) -> None:
        """restore-test shows hint when extraction fails with mknod (lines 361-366)."""
        config = {
            "docker": {
                "backup_dir": str(docker_tar_gz.parent),
                "max_age_hours": 170,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "tar", stderr=b"mknod: Operation not permitted"
            ),
        ):
            result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0
        assert "hint" in result.output.lower() or "sudo" in result.output.lower()

    def test_extraction_timeout(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        docker_tar_gz: Path,
    ) -> None:
        """restore-test handles extraction timeout (lines 368-370)."""
        config = {
            "docker": {
                "backup_dir": str(docker_tar_gz.parent),
                "max_age_hours": 170,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tar", timeout=300),
        ):
            result = runner.invoke(main, ["restore-test"])
        assert result.exit_code != 0
        assert "timed out" in result.output.lower()


# ---------------------------------------------------------------------------
# db.py — lastrowid is None (line 68)
# ---------------------------------------------------------------------------


class TestDbEdgeCases:
    def test_store_run_no_lastrowid(self, tmp_config_dir: Path) -> None:
        """store_run raises RuntimeError when lastrowid is None (line 68)."""
        from backuppilot.db import store_run

        results = [CheckResult("test", True, "ok")]
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = None

        with patch("backuppilot.db._connect") as mock_connect:
            mock_conn = MagicMock()
            mock_conn.execute.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            with pytest.raises(RuntimeError, match="no lastrowid"):
                store_run(results)


# ---------------------------------------------------------------------------
# notify.py — HTTP status >= 300 (line 86)
# ---------------------------------------------------------------------------


class TestNotifyEdgeCases:
    def test_http_300_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_signal raises NotifyError for HTTP status >= 300 (line 86)."""
        from backuppilot.notify import send_signal

        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.setenv("SIGNAL_RECIPIENT", "+2222")

        mock_resp = MagicMock()
        mock_resp.status = 301
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("backuppilot.notify.urlopen", return_value=mock_resp):
            from backuppilot.notify import NotifyError

            with pytest.raises(NotifyError, match="HTTP 301"):
                send_signal([CheckResult("test", True, "ok")], True)
