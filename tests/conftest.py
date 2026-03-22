"""Shared fixtures for BackupPilot tests."""

from __future__ import annotations

import gzip
import os
import tarfile
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config and DB to a temp directory."""
    config_dir = tmp_path / ".backuppilot"
    config_dir.mkdir()
    monkeypatch.setattr("backuppilot.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("backuppilot.config.CONFIG_PATH", config_dir / "config.yaml")
    monkeypatch.setattr("backuppilot.db.CONFIG_DIR", config_dir)
    monkeypatch.setattr("backuppilot.db.DB_PATH", config_dir / "history.db")
    return config_dir


@pytest.fixture
def sample_config(tmp_path: Path) -> dict:
    """Return a sample config dict with real temp dirs."""
    docker_dir = tmp_path / "docker_backups"
    docker_dir.mkdir()
    opnsense_dir = tmp_path / "opnsense_backups"
    opnsense_dir.mkdir()

    return {
        "docker": {
            "backup_dir": str(docker_dir),
            "max_age_hours": 170,
            "min_size_mb": 0,  # low threshold for test fixtures
            "max_size_mb": 5000,
            "expected_volumes": ["testvolume"],
        },
        "opnsense": {
            "backup_dir": str(opnsense_dir),
            "max_age_hours": 170,
            "expected_sections": ["system", "interfaces", "filter"],
        },
        "gdrive": {
            "remote": "gdrive:test/",
            "max_age_hours": 170,
            "expected_files": 1,
        },
    }


@pytest.fixture
def docker_tar_gz(tmp_path: Path) -> Path:
    """Create a minimal tar.gz containing a 'testvolume' directory."""
    docker_dir = tmp_path / "docker_backups"
    docker_dir.mkdir(exist_ok=True)

    # Create content to archive
    content_dir = tmp_path / "archive_content" / "testvolume"
    content_dir.mkdir(parents=True)
    (content_dir / "data.txt").write_text("test data")

    tar_path = docker_dir / "docker-backup-test.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(str(content_dir.parent / "testvolume"), arcname="testvolume")

    return tar_path


@pytest.fixture
def opnsense_xml(tmp_path: Path) -> Path:
    """Create a minimal OPNsense-like XML config file."""
    opnsense_dir = tmp_path / "opnsense_backups"
    opnsense_dir.mkdir(exist_ok=True)

    xml_content = textwrap.dedent("""\
        <?xml version="1.0"?>
        <opnsense>
            <system>
                <hostname>opnsense</hostname>
            </system>
            <interfaces>
                <lan><if>igc1</if></lan>
            </interfaces>
            <filter>
                <rule><type>pass</type></rule>
            </filter>
        </opnsense>
    """)

    xml_path = opnsense_dir / "config-test.xml"
    xml_path.write_text(xml_content)
    return xml_path


@pytest.fixture
def opnsense_xml_gz(tmp_path: Path, opnsense_xml: Path) -> Path:
    """Create a gzipped OPNsense config."""
    gz_path = opnsense_xml.parent / "config-test.xml.gz"
    with open(opnsense_xml, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            f_out.write(f_in.read())
    return gz_path


@pytest.fixture
def clean_signal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Signal env vars to test 'not configured' path."""
    monkeypatch.delenv("SIGNAL_API_URL", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
