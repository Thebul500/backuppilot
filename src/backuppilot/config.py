"""Configuration loading and interactive init for BackupPilot."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import click
import yaml

CONFIG_DIR = Path.home() / ".backuppilot"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


def _ensure_dir() -> None:
    """Create config directory with secure permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, stat.S_IRWXU)  # 0o700


def load_config() -> dict[str, Any]:
    """Load config from ~/.backuppilot/config.yaml.

    Raises ConfigError if the config file does not exist.
    """
    if not CONFIG_PATH.exists():
        raise ConfigError(
            f"Config file not found: {CONFIG_PATH}\n"
            "Run 'backuppilot init' to create one."
        )
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(
            f"Invalid config file: {CONFIG_PATH}\n"
            "Expected a YAML mapping. Run 'backuppilot init' to recreate."
        )
    return data


def get_section(cfg: dict[str, Any], section: str) -> dict[str, Any]:
    """Get a config section, raising ConfigError if missing."""
    if section not in cfg:
        raise ConfigError(
            f"Missing '{section}' section in config.\n"
            "Run 'backuppilot init' to reconfigure."
        )
    val = cfg[section]
    if not isinstance(val, dict):
        raise ConfigError(
            f"Config section '{section}' must be a mapping, got {type(val).__name__}."
        )
    return val


def save_config(data: dict[str, Any]) -> Path:
    """Write config to disk."""
    _ensure_dir()
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    return CONFIG_PATH


def interactive_init() -> dict[str, Any]:
    """Interactively prompt the user for configuration values."""
    click.echo("BackupPilot configuration wizard")
    click.echo("=" * 40)

    config: dict[str, Any] = {}

    # --- Docker section ---
    click.echo()
    click.echo(click.style("Docker Backup Settings", bold=True))
    docker_dir = click.prompt(
        "Docker backup directory (tar.gz files)",
        type=click.Path(),
    )
    docker_max_age = click.prompt(
        "Max backup age in hours",
        default=170,
        type=int,
    )
    docker_min_size = click.prompt(
        "Minimum backup size (MB)",
        default=500,
        type=int,
    )
    docker_max_size = click.prompt(
        "Maximum backup size (MB)",
        default=3000,
        type=int,
    )
    volumes_str = click.prompt(
        "Expected volume names (comma-separated)",
        default="pihole,grafana,prometheus,n8n,vaultwarden,nginx-proxy-manager",
    )
    config["docker"] = {
        "backup_dir": str(docker_dir),
        "max_age_hours": docker_max_age,
        "min_size_mb": docker_min_size,
        "max_size_mb": docker_max_size,
        "expected_volumes": [v.strip() for v in volumes_str.split(",") if v.strip()],
    }

    # --- OPNsense section ---
    click.echo()
    click.echo(click.style("OPNsense Backup Settings", bold=True))
    opnsense_dir = click.prompt(
        "OPNsense backup directory (XML/XML.gz files)",
        type=click.Path(),
    )
    opnsense_max_age = click.prompt(
        "Max backup age in hours",
        default=170,
        type=int,
    )
    sections_str = click.prompt(
        "Expected config sections (comma-separated)",
        default="system,interfaces,filter",
    )
    config["opnsense"] = {
        "backup_dir": str(opnsense_dir),
        "max_age_hours": opnsense_max_age,
        "expected_sections": [s.strip() for s in sections_str.split(",") if s.strip()],
    }

    # --- GDrive section ---
    click.echo()
    click.echo(click.style("GDrive Backup Settings", bold=True))
    if click.confirm("Configure GDrive (rclone) validation?", default=True):
        gdrive_remote = click.prompt(
            "Rclone remote path",
            default="gdrive:Infrastructure-Backups/",
        )
        gdrive_max_age = click.prompt(
            "Max backup age in hours",
            default=170,
            type=int,
        )
        gdrive_expected = click.prompt(
            "Expected minimum file count",
            default=2,
            type=int,
        )
        config["gdrive"] = {
            "remote": gdrive_remote,
            "max_age_hours": gdrive_max_age,
            "expected_files": gdrive_expected,
        }

    return config
