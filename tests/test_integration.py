"""Integration tests for BackupPilot.

These tests exercise real file I/O, archive creation, XML parsing,
and database persistence — no mocks.
"""

from __future__ import annotations

import gzip
import json
import tarfile
import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from backuppilot.checks import (
    CheckResult,
    check_docker_contents,
    check_freshness,
    check_integrity,
    check_opnsense_config,
    check_size,
)
from backuppilot.cli import main
from backuppilot.db import get_history, get_run_details, store_run


@pytest.mark.integration
class TestTarGzValidation:
    """Create real tar.gz archives and validate them end-to-end."""

    def test_multi_volume_archive(self, tmp_path: Path) -> None:
        """Create a tar.gz with multiple volumes and verify all are detected."""
        volumes = ["grafana", "prometheus", "pihole", "vaultwarden"]
        content_root = tmp_path / "content"
        for vol in volumes:
            vol_dir = content_root / vol
            vol_dir.mkdir(parents=True)
            (vol_dir / "config.json").write_text(json.dumps({"volume": vol}))
            (vol_dir / "data.bin").write_bytes(b"\x00" * 1024)

        archive = tmp_path / "docker-backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for vol in volumes:
                tf.add(str(content_root / vol), arcname=vol)

        # Integrity check
        result = check_integrity(archive)
        assert result.passed, f"Integrity failed: {result.message}"

        # Size check
        size = archive.stat().st_size
        result = check_size(archive, 0, size * 2)
        assert result.passed

        # Freshness check (just created, should be fresh)
        result = check_freshness(archive, max_age_hours=1)
        assert result.passed

        # Contents check — all volumes present
        result = check_docker_contents(archive, volumes)
        assert result.passed
        assert f"{len(volumes)} volumes" in result.message

        # Contents check — missing volume should fail
        result = check_docker_contents(archive, volumes + ["nonexistent"])
        assert not result.passed
        assert "nonexistent" in result.message

    def test_empty_archive(self, tmp_path: Path) -> None:
        """A valid but empty tar.gz should pass integrity but fail contents."""
        archive = tmp_path / "empty.tar.gz"
        with tarfile.open(archive, "w:gz"):
            pass  # empty archive

        assert check_integrity(archive).passed
        assert not check_docker_contents(archive, ["anything"]).passed

    def test_nested_directory_structure(self, tmp_path: Path) -> None:
        """Archive with deeply nested paths should still be readable."""
        content = tmp_path / "deep" / "nested" / "path" / "volume"
        content.mkdir(parents=True)
        (content / "file.txt").write_text("deep content")

        archive = tmp_path / "nested.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(str(tmp_path / "deep"), arcname="deep")

        assert check_integrity(archive).passed
        result = check_docker_contents(archive, ["volume"])
        assert result.passed


@pytest.mark.integration
class TestXmlValidation:
    """Create real OPNsense XML configs and validate parsing."""

    def test_full_opnsense_config(self, tmp_path: Path) -> None:
        """Parse a realistic OPNsense config with multiple sections."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <opnsense>
                <system>
                    <hostname>fw01</hostname>
                    <domain>bul-network.com</domain>
                    <dnsserver>10.0.2.2</dnsserver>
                </system>
                <interfaces>
                    <wan><if>igc0</if><ipaddr>dhcp</ipaddr></wan>
                    <lan><if>igc1</if><ipaddr>10.0.2.1</ipaddr></lan>
                </interfaces>
                <filter>
                    <rule><type>pass</type><interface>lan</interface></rule>
                    <rule><type>block</type><interface>wan</interface></rule>
                </filter>
                <dhcpd>
                    <lan><range><from>10.0.2.100</from><to>10.0.2.200</to></range></lan>
                </dhcpd>
                <unbound>
                    <active>on</active>
                </unbound>
            </opnsense>
        """)
        xml_path = tmp_path / "config.xml"
        xml_path.write_text(xml)

        # All expected sections present
        result = check_opnsense_config(xml_path, ["system", "interfaces", "filter"])
        assert result.passed
        assert "3 sections" in result.message

        # Extra sections also found
        result = check_opnsense_config(
            xml_path, ["system", "interfaces", "filter", "dhcpd", "unbound"]
        )
        assert result.passed
        assert "5 sections" in result.message

    def test_gzipped_config(self, tmp_path: Path) -> None:
        """Validate gzipped OPNsense config round-trip."""
        xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <opnsense>
                <system><hostname>fw</hostname></system>
                <interfaces><lan><if>igc1</if></lan></interfaces>
            </opnsense>
        """)
        xml_path = tmp_path / "config.xml"
        xml_path.write_text(xml)

        gz_path = tmp_path / "config.xml.gz"
        with open(xml_path, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                f_out.write(f_in.read())

        result = check_opnsense_config(gz_path, ["system", "interfaces"])
        assert result.passed

    def test_malformed_xml_fails(self, tmp_path: Path) -> None:
        """Invalid XML should produce a clear failure."""
        bad = tmp_path / "bad.xml"
        bad.write_text("<opnsense><system><unclosed>")
        result = check_opnsense_config(bad, ["system"])
        assert not result.passed
        assert "xml" in result.message.lower()

    def test_missing_sections_reports_which(self, tmp_path: Path) -> None:
        """Missing sections should be named in the message."""
        xml_path = tmp_path / "minimal.xml"
        xml_path.write_text("<opnsense><system/></opnsense>")
        result = check_opnsense_config(xml_path, ["system", "syslog", "cron"])
        assert not result.passed
        assert "syslog" in result.message
        assert "cron" in result.message


@pytest.mark.integration
class TestDbPersistence:
    """Test real SQLite round-trips with actual data."""

    def test_store_and_retrieve(self, tmp_config_dir: Path) -> None:
        """Store results, retrieve by run ID, verify data integrity."""
        results = [
            CheckResult("freshness", True, "2.3h old", {"age_hours": 2.3}),
            CheckResult("integrity", True, "Archive OK"),
            CheckResult("size", True, "1234.5MB", {"size_mb": 1234.5}),
            CheckResult("contents", False, "Missing: grafana", {"missing": ["grafana"]}),
        ]
        run_id = store_run(results)
        assert run_id >= 1

        # Verify run summary
        runs = get_history(limit=1)
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["total_checks"] == 4
        assert runs[0]["failed_checks"] == 1
        assert runs[0]["passed"] == 0  # overall failed

        # Verify individual results
        details = get_run_details(run_id)
        assert len(details) == 4
        assert details[0]["check_name"] == "freshness"
        assert details[0]["passed"] == 1
        assert details[3]["check_name"] == "contents"
        assert details[3]["passed"] == 0

    def test_multiple_runs_ordering(self, tmp_config_dir: Path) -> None:
        """Multiple runs are returned in reverse chronological order."""
        ids = []
        for i in range(5):
            passed = i % 2 == 0
            rid = store_run([CheckResult(f"check_{i}", passed, f"run {i}")])
            ids.append(rid)

        runs = get_history(limit=10)
        assert len(runs) == 5
        # Most recent first
        assert runs[0]["id"] == ids[-1]
        assert runs[-1]["id"] == ids[0]

    def test_details_with_json(self, tmp_config_dir: Path) -> None:
        """Details JSON column preserves complex data structures."""
        details_data = {
            "found": ["pihole", "grafana"],
            "missing": ["prometheus"],
            "nested": {"key": [1, 2, 3]},
        }
        run_id = store_run([
            CheckResult("complex", False, "partial", details_data)
        ])
        stored = get_run_details(run_id)
        assert len(stored) == 1
        parsed = json.loads(stored[0]["details_json"])
        assert parsed["found"] == ["pihole", "grafana"]
        assert parsed["nested"]["key"] == [1, 2, 3]


@pytest.mark.integration
class TestEndToEnd:
    """Full CLI end-to-end tests with real files."""

    def test_check_and_history_roundtrip(
        self, tmp_config_dir: Path, tmp_path: Path
    ) -> None:
        """Run check, verify history records it, verify details match."""
        runner = CliRunner()

        # Create real docker backup
        docker_dir = tmp_path / "docker"
        docker_dir.mkdir()
        content = tmp_path / "vol" / "testvolume"
        content.mkdir(parents=True)
        (content / "data").write_bytes(b"x" * 512)
        archive = docker_dir / "backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(str(content), arcname="testvolume")

        # Write config
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

        # Run check
        result = runner.invoke(main, ["check", "--type", "docker"])
        assert result.exit_code == 0
        assert "PASS" in result.output

        # Verify history
        result = runner.invoke(main, ["history"])
        assert result.exit_code == 0
        assert "PASS" in result.output

        # Verify JSON output
        result = runner.invoke(main, ["history", "--run", "1", "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert all(d["passed"] == 1 for d in data)
