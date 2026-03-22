"""Tests for config loading and init."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backuppilot.config import ConfigError, get_section, load_config, save_config


class TestLoadConfig:
    def test_missing_config_raises(self, tmp_config_dir: Path) -> None:
        """load_config raises ConfigError when config file does not exist."""
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config()

    def test_loads_valid_config(self, tmp_config_dir: Path) -> None:
        """load_config returns parsed YAML dict."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"docker": {"backup_dir": "/tmp/test"}}))
        cfg = load_config()
        assert cfg["docker"]["backup_dir"] == "/tmp/test"

    def test_invalid_yaml_raises(self, tmp_config_dir: Path) -> None:
        """load_config raises ConfigError for non-mapping YAML."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text("just a string")
        with pytest.raises(ConfigError, match="Invalid config file"):
            load_config()

    def test_empty_file_raises(self, tmp_config_dir: Path) -> None:
        """load_config raises ConfigError for empty config file."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text("")
        with pytest.raises(ConfigError, match="Invalid config file"):
            load_config()


class TestGetSection:
    def test_returns_section(self) -> None:
        cfg = {"docker": {"backup_dir": "/backups"}}
        assert get_section(cfg, "docker")["backup_dir"] == "/backups"

    def test_missing_section_raises(self) -> None:
        with pytest.raises(ConfigError, match="Missing 'gdrive' section"):
            get_section({}, "gdrive")

    def test_non_dict_section_raises(self) -> None:
        with pytest.raises(ConfigError, match="must be a mapping"):
            get_section({"docker": "not-a-dict"}, "docker")


class TestSaveConfig:
    def test_creates_file(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / "config.yaml"
        save_config({"docker": {"backup_dir": "/test"}})
        assert config_path.exists()

    def test_roundtrip(self, tmp_config_dir: Path) -> None:
        """Saved config can be loaded back."""
        data = {
            "docker": {"backup_dir": "/test", "max_age_hours": 48},
            "opnsense": {"backup_dir": "/ops", "expected_sections": ["system"]},
        }
        save_config(data)
        loaded = load_config()
        assert loaded == data

    def test_file_permissions(self, tmp_config_dir: Path) -> None:
        """Config file has 0o600 permissions."""
        save_config({"docker": {"backup_dir": "/test"}})
        config_path = tmp_config_dir / "config.yaml"
        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600
