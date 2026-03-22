"""Tests for CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from backuppilot.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCLIHelp:
    def test_main_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "BackupPilot" in result.output

    def test_check_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["check", "--help"])
        assert result.exit_code == 0
        assert "--type" in result.output
        assert "--notify" in result.output

    def test_history_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["history", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.output

    def test_init_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0

    def test_restore_test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["restore-test", "--help"])
        assert result.exit_code == 0

    def test_prune_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["prune", "--help"])
        assert result.exit_code == 0

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output


class TestCheckCommand:
    def test_no_config_fails_gracefully(
        self, runner: CliRunner, tmp_config_dir: Path
    ) -> None:
        result = runner.invoke(main, ["check"])
        assert result.exit_code != 0
        assert "config" in result.output.lower() or "init" in result.output.lower()

    def test_docker_check_with_config(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        # Write config using the sample
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        result = runner.invoke(main, ["check", "--type", "docker"])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_docker_check_json(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        result = runner.invoke(main, ["check", "--type", "docker", "--json-output"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "passed" in data
        assert "results" in data
        assert "run_id" in data

    def test_opnsense_check_with_config(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        opnsense_xml: Path,
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        result = runner.invoke(main, ["check", "--type", "opnsense"])
        assert result.exit_code == 0
        assert "PASS" in result.output


class TestHistoryCommand:
    def test_empty_history(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        result = runner.invoke(main, ["history"])
        assert result.exit_code == 0
        assert "no validation history" in result.output.lower()

    def test_history_after_check(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        runner.invoke(main, ["check", "--type", "docker"])
        result = runner.invoke(main, ["history"])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_history_json(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        result = runner.invoke(main, ["history", "--json-output"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_run_details(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        runner.invoke(main, ["check", "--type", "docker"])
        result = runner.invoke(main, ["history", "--run", "1"])
        assert result.exit_code == 0

    def test_nonexistent_run(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        result = runner.invoke(main, ["history", "--run", "9999"])
        assert result.exit_code == 0
        assert "no results" in result.output.lower()

    def test_failures_none(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        result = runner.invoke(main, ["history", "--failures"])
        assert result.exit_code == 0
        assert "no failures" in result.output.lower()


class TestPruneCommand:
    def test_prune_nothing(self, runner: CliRunner, tmp_config_dir: Path) -> None:
        result = runner.invoke(main, ["prune"])
        assert result.exit_code == 0
        assert "nothing to prune" in result.output.lower()


class TestNotifyFlags:
    def test_notify_on_failure_no_signal_env(
        self,
        runner: CliRunner,
        tmp_config_dir: Path,
        clean_signal_env: None,
    ) -> None:
        """--notify with missing signal env prints error, doesn't crash."""
        # Config with a non-existent backup dir to force failure
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({
            "docker": {"backup_dir": "/nonexistent", "max_age_hours": 170},
        }))
        result = runner.invoke(main, ["check", "--type", "docker", "--notify"])
        # Should fail (no backups) but not crash
        assert result.exit_code != 0
        assert "notification error" in result.output.lower() or "FAIL" in result.output
