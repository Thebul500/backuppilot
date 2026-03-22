"""Extended CLI tests for coverage improvement."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from backuppilot.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCheckCommandExtended:
    def test_unknown_check_type_via_run_all(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """Check with unknown type returns error."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"docker": {"backup_dir": "/tmp/none"}}))
        # Using the CLI's --type choice restriction, this won't pass through,
        # but we can test the _run_all path with valid type but missing dir
        result = runner.invoke(main, ["check", "--type", "docker"])
        # docker backup_dir might not exist — should get FAIL
        assert result.exit_code != 0

    def test_check_all_types_skips_unconfigured(
        self, runner: CliRunner, tmp_config_dir: Path, docker_tar_gz: Path
    ) -> None:
        """Full check run skips unconfigured sections (no gdrive/opnsense)."""
        docker_dir = docker_tar_gz.parent
        config = {
            "docker": {
                "backup_dir": str(docker_dir),
                "max_age_hours": 170,
                "min_size_mb": 0,
                "max_size_mb": 5000,
                "expected_volumes": ["testvolume"],
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_check_opnsense_missing_dir(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """OPNsense check with missing directory."""
        config = {
            "opnsense": {
                "backup_dir": "/nonexistent/path",
                "max_age_hours": 170,
                "expected_sections": ["system"],
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["check", "--type", "opnsense"])
        assert result.exit_code != 0
        assert "FAIL" in result.output

    def test_check_opnsense_no_files(
        self, runner: CliRunner, tmp_config_dir: Path, tmp_path: Path
    ) -> None:
        """OPNsense check with empty directory."""
        empty_dir = tmp_path / "empty_ops"
        empty_dir.mkdir()
        config = {
            "opnsense": {
                "backup_dir": str(empty_dir),
                "max_age_hours": 170,
                "expected_sections": ["system"],
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["check", "--type", "opnsense"])
        assert result.exit_code != 0

    def test_check_docker_no_files(
        self, runner: CliRunner, tmp_config_dir: Path, tmp_path: Path
    ) -> None:
        """Docker check with empty directory."""
        empty_dir = tmp_path / "empty_docker"
        empty_dir.mkdir()
        config = {
            "docker": {
                "backup_dir": str(empty_dir),
                "max_age_hours": 170,
                "min_size_mb": 0,
                "max_size_mb": 5000,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["check", "--type", "docker"])
        assert result.exit_code != 0
        assert "FAIL" in result.output

    def test_check_docker_no_volumes_config(
        self, runner: CliRunner, tmp_config_dir: Path, docker_tar_gz: Path
    ) -> None:
        """Docker check passes without expected_volumes in config."""
        docker_dir = docker_tar_gz.parent
        config = {
            "docker": {
                "backup_dir": str(docker_dir),
                "max_age_hours": 170,
                "min_size_mb": 0,
                "max_size_mb": 5000,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["check", "--type", "docker"])
        assert result.exit_code == 0

    def test_check_json_on_failure(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """JSON output on failed check."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({
            "docker": {"backup_dir": "/nonexistent", "max_age_hours": 170},
        }))
        result = runner.invoke(main, ["check", "--type", "docker", "--json-output"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["passed"] is False


class TestHistoryExtended:
    def test_history_failures_exist(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """Test --failures when failures exist."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({
            "docker": {"backup_dir": "/nonexistent", "max_age_hours": 170},
        }))
        # Create a failed check run
        runner.invoke(main, ["check", "--type", "docker"])
        result = runner.invoke(main, ["history", "--failures"])
        assert result.exit_code == 0
        assert "Failures" in result.output or "Run #" in result.output

    def test_history_failures_json(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """Test --failures --json-output."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({
            "docker": {"backup_dir": "/nonexistent", "max_age_hours": 170},
        }))
        runner.invoke(main, ["check", "--type", "docker"])
        result = runner.invoke(main, ["history", "--failures", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_run_details_json(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        runner.invoke(main, ["check", "--type", "docker"])
        result = runner.invoke(main, ["history", "--run", "1", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_prune_after_checks(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        for _ in range(5):
            runner.invoke(main, ["check", "--type", "docker"])
        result = runner.invoke(main, ["prune", "--keep", "2"])
        assert result.exit_code == 0
        assert "Pruned" in result.output


class TestGdriveCheck:
    def test_gdrive_check_via_cli(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """Test gdrive check type with rclone not installed."""
        config = {
            "gdrive": {
                "remote": "gdrive:test/",
                "max_age_hours": 170,
                "expected_files": 1,
            }
        }
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(config))
        result = runner.invoke(main, ["check", "--type", "gdrive"])
        # Will fail because rclone is likely not installed or no remote configured
        assert result.exit_code != 0


class TestAlwaysNotify:
    def test_always_notify_on_success(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--always-notify triggers signal even on success."""
        monkeypatch.delenv("SIGNAL_API_URL", raising=False)
        monkeypatch.delenv("SIGNAL_SENDER", raising=False)
        monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        result = runner.invoke(main, ["check", "--type", "docker", "--always-notify"])
        # Should pass checks but fail notification (no signal env)
        assert result.exit_code == 0
        assert "Notification error" in result.output or "PASS" in result.output

    def test_always_notify_json_on_success(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--always-notify with --json-output."""
        monkeypatch.delenv("SIGNAL_API_URL", raising=False)
        monkeypatch.delenv("SIGNAL_SENDER", raising=False)
        monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        result = runner.invoke(
            main, ["check", "--type", "docker", "--always-notify", "--json-output"]
        )
        assert result.exit_code == 0


class TestNoConfiguredChecks:
    def test_empty_config_reports_error(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        """Config with no recognized sections reports helpful error."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"misc": "value"}))
        result = runner.invoke(main, ["check"])
        assert result.exit_code != 0
        assert "No checks configured" in result.output or "init" in result.output.lower()
