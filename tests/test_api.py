"""Tests for the FastAPI REST API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from backuppilot.api import create_app
from backuppilot.checks import CheckResult
from backuppilot.db import store_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set and return a test API key."""
    key = "test-api-key-12345"
    monkeypatch.setenv("BACKUPPILOT_API_KEY", key)
    return key


@pytest.fixture
def auth_headers(api_key: str) -> dict[str, str]:
    """Return Authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient from a fresh app."""
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint (no auth)
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(
        self, client: TestClient, tmp_config_dir: Path, sample_config: dict
    ) -> None:
        config_path = tmp_config_dir / "config.yaml"
        import yaml
        config_path.write_text(yaml.dump(sample_config))
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "backuppilot"
        assert "version" in data
        assert "timestamp" in data
        assert "checks" in data
        assert data["checks"]["database"] == "ok"
        assert data["checks"]["config"] == "ok"

    def test_health_no_auth_required(self, client: TestClient) -> None:
        """Health endpoint works without any Authorization header."""
        resp = client.get("/health")
        assert resp.status_code in (200, 503)

    def test_health_degraded_on_db_failure(
        self, client: TestClient, tmp_config_dir: Path, sample_config: dict
    ) -> None:
        """Health returns 503 when database check fails."""
        import yaml
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))
        with patch("backuppilot.api._connect", side_effect=RuntimeError("db broken")):
            resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "failed"
        assert "version" in data
        assert "timestamp" in data

    def test_health_degraded_no_config(
        self, client: TestClient, tmp_config_dir: Path
    ) -> None:
        """Health returns 503 when config file is missing."""
        resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["config"] == "failed"


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_auth_header(
        self, client: TestClient, api_key: str
    ) -> None:
        """Endpoints return 401 without Authorization header."""
        resp = client.get("/api/history")
        assert resp.status_code == 401

    def test_wrong_token(
        self, client: TestClient, api_key: str
    ) -> None:
        """Endpoints return 401 with wrong Bearer token."""
        resp = client.get(
            "/api/history", headers={"Authorization": "Bearer wrong-key"}
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_malformed_auth_header(
        self, client: TestClient, api_key: str
    ) -> None:
        """Endpoints return 401 with non-Bearer auth scheme."""
        resp = client.get(
            "/api/history", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )
        assert resp.status_code == 401

    def test_no_api_key_env_var(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """401 when BACKUPPILOT_API_KEY env var is not set."""
        monkeypatch.delenv("BACKUPPILOT_API_KEY", raising=False)
        resp = client.get(
            "/api/history", headers={"Authorization": "Bearer anything"}
        )
        assert resp.status_code == 401
        assert "not set" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/check
# ---------------------------------------------------------------------------


class TestCheckEndpoint:
    def test_check_docker_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        """Successful Docker check via API."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        resp = client.post(
            "/api/check",
            headers=auth_headers,
            json={"types": ["docker"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["run_id"] is not None
        assert data["summary"]["failed"] == 0
        assert len(data["results"]) > 0

    def test_check_no_config_returns_503(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        """503 when config is not initialized."""
        resp = client.post(
            "/api/check",
            headers=auth_headers,
            json={"types": ["docker"]},
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"].lower()

    def test_check_invalid_type(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
    ) -> None:
        """422 for invalid check type."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        resp = client.post(
            "/api/check",
            headers=auth_headers,
            json={"types": ["invalid_type"]},
        )
        assert resp.status_code == 422

    def test_check_default_types(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
        opnsense_xml: Path,
    ) -> None:
        """Default types runs all configured checks."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        # gdrive will fail (rclone not available), but docker/opnsense should work
        with patch("backuppilot.checks._resolve_executable") as mock_resolve:
            # Let tar work normally but mock rclone as not found
            def selective_resolve(name: str) -> str:
                if name == "rclone":
                    raise FileNotFoundError("rclone not found")
                import shutil

                path = shutil.which(name)
                if path is None:
                    raise FileNotFoundError(f"{name} not found in PATH")
                return path

            mock_resolve.side_effect = selective_resolve
            resp = client.post(
                "/api/check",
                headers=auth_headers,
                json={},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) > 0

    def test_check_config_error_for_section(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        """ConfigError for a specific section returns errors list."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"docker": "not-a-dict"}))

        resp = client.post(
            "/api/check",
            headers=auth_headers,
            json={"types": ["docker"]},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["passed"] is False
        assert len(data["errors"]) > 0

    def test_check_store_run_failure(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
        docker_tar_gz: Path,
    ) -> None:
        """Check still returns results even if store_run fails."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        with patch("backuppilot.api.store_run", side_effect=RuntimeError("db fail")):
            resp = client.post(
                "/api/check",
                headers=auth_headers,
                json={"types": ["docker"]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] is None
        assert len(data["results"]) > 0


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------


class TestHistoryEndpoint:
    def test_empty_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        resp = client.get("/api/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_with_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        store_run([CheckResult("test_a", True, "ok")])
        store_run([CheckResult("test_b", False, "fail")])

        resp = client.get("/api/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_history_with_limit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        for i in range(5):
            store_run([CheckResult(f"check_{i}", True, "ok")])

        resp = client.get("/api/history?limit=2", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_history_failures_only(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        store_run([CheckResult("pass", True, "ok")])
        store_run([CheckResult("fail", False, "broken")])

        resp = client.get(
            "/api/history?failures_only=true", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["check_name"] == "fail"


# ---------------------------------------------------------------------------
# GET /api/history/{run_id}
# ---------------------------------------------------------------------------


class TestRunDetailsEndpoint:
    def test_existing_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        run_id = store_run([
            CheckResult("check_a", True, "ok"),
            CheckResult("check_b", False, "fail"),
        ])

        resp = client.get(f"/api/history/{run_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["check_name"] == "check_a"

    def test_nonexistent_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        resp = client.get("/api/history/9999", headers=auth_headers)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    def test_status_no_config(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        """503 when config missing."""
        resp = client.get("/api/status", headers=auth_headers)
        assert resp.status_code == 503

    def test_status_no_runs(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
    ) -> None:
        """Status with config but no check history."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        resp = client.get("/api/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_check"] is None
        assert data["overall_passed"] is None
        assert "no checks" in data["message"].lower()

    def test_status_with_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
    ) -> None:
        """Status returns last check info."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        store_run([CheckResult("check_a", True, "ok")])

        resp = client.get("/api/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_passed"] is True
        assert data["total_checks"] == 1
        assert data["failed_checks"] == 0
        assert data["run_id"] is not None
        assert data["last_check"] is not None

    def test_status_failed_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
        sample_config: dict,
    ) -> None:
        """Status reflects failed check."""
        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump(sample_config))

        store_run([
            CheckResult("ok", True, "pass"),
            CheckResult("bad", False, "fail"),
        ])

        resp = client.get("/api/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_passed"] is False
        assert data["failed_checks"] == 1


# ---------------------------------------------------------------------------
# DELETE /api/history/prune
# ---------------------------------------------------------------------------


class TestPruneEndpoint:
    def test_prune_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        resp = client.request(
            "DELETE",
            "/api/history/prune",
            headers=auth_headers,
            json={"keep_days": 100},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 0
        assert data["kept"] == 100

    def test_prune_old_runs(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        for i in range(10):
            store_run([CheckResult(f"check_{i}", True, "ok")])

        resp = client.request(
            "DELETE",
            "/api/history/prune",
            headers=auth_headers,
            json={"keep_days": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] > 0
        assert data["kept"] == 3

    def test_prune_default_keep(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        tmp_config_dir: Path,
    ) -> None:
        """Prune with default keep_days value."""
        resp = client.request(
            "DELETE",
            "/api/history/prune",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["kept"] == 100


# ---------------------------------------------------------------------------
# GET /metrics  (no auth — Prometheus scrape)
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_metrics_no_auth_required(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """/metrics returns 200 without any Authorization header."""
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Response is plain text."""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_empty_db(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Metrics with no history return zero counters and default gauges."""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text

        assert "backuppilot_checks_total 0" in body
        assert "backuppilot_checks_passed_total 0" in body
        assert "backuppilot_checks_failed_total 0" in body
        assert "backuppilot_last_check_timestamp 0" in body
        assert "backuppilot_last_check_passed 0" in body

    def test_metrics_counters_reflect_db(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Counters reflect stored runs."""
        store_run([CheckResult("check_a", True, "ok")])
        store_run([CheckResult("check_b", False, "fail")])
        store_run([CheckResult("check_c", True, "ok")])

        resp = client.get("/metrics")
        body = resp.text

        assert "backuppilot_checks_total 3" in body
        assert "backuppilot_checks_passed_total 2" in body
        assert "backuppilot_checks_failed_total 1" in body

    def test_metrics_last_check_passed(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """last_check_passed reflects the most recent run."""
        store_run([CheckResult("a", True, "ok")])
        resp = client.get("/metrics")
        assert "backuppilot_last_check_passed 1" in resp.text

    def test_metrics_last_check_failed(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """last_check_passed is 0 when last run has a failure."""
        store_run([CheckResult("a", True, "ok")])
        store_run([CheckResult("b", False, "broken")])
        resp = client.get("/metrics")
        assert "backuppilot_last_check_passed 0" in resp.text

    def test_metrics_last_check_timestamp(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """last_check_timestamp is a non-zero unix timestamp after a run."""
        store_run([CheckResult("t", True, "ok")])
        resp = client.get("/metrics")
        body = resp.text

        # Extract the timestamp value
        for line in body.splitlines():
            if line.startswith("backuppilot_last_check_timestamp "):
                ts_val = float(line.split()[-1])
                assert ts_val > 0
                break
        else:
            pytest.fail("backuppilot_last_check_timestamp not found in output")

    def test_metrics_check_result_labels(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Per-check-type results appear with type labels."""
        store_run([
            CheckResult("freshness", True, "2.0h old", {"age_hours": 2.0}),
            CheckResult("integrity", True, "Archive OK"),
            CheckResult("size", False, "too big"),
        ])
        resp = client.get("/metrics")
        body = resp.text

        assert 'backuppilot_check_result{type="freshness"} 1' in body
        assert 'backuppilot_check_result{type="integrity"} 1' in body
        assert 'backuppilot_check_result{type="size"} 0' in body

    def test_metrics_backup_age_hours(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """backup_age_hours is emitted from freshness check details."""
        store_run([
            CheckResult("freshness", True, "5.3h old", {"age_hours": 5.3}),
        ])
        resp = client.get("/metrics")
        body = resp.text

        assert 'backuppilot_backup_age_hours{type="backup"} 5.3' in body

    def test_metrics_no_age_without_freshness(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """backup_age_hours is not emitted when no freshness check exists."""
        store_run([CheckResult("integrity", True, "OK")])
        resp = client.get("/metrics")
        body = resp.text

        assert "backuppilot_backup_age_hours" not in body

    def test_metrics_valid_prometheus_format(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """All lines are valid Prometheus text format (# comments or metric lines)."""
        store_run([
            CheckResult("freshness", True, "2h old", {"age_hours": 2.0}),
            CheckResult("integrity", True, "OK"),
        ])
        resp = client.get("/metrics")
        body = resp.text

        for line in body.splitlines():
            if not line:
                continue  # blank lines are fine
            if line.startswith("#"):
                # Must be HELP or TYPE
                assert line.startswith("# HELP ") or line.startswith("# TYPE ")
            else:
                # Metric line: name{labels} value or name value
                parts = line.split()
                assert len(parts) == 2, f"Invalid metric line: {line!r}"
                # Value must be numeric
                float(parts[1])

    def test_metrics_help_and_type_annotations(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """All metric families have HELP and TYPE annotations."""
        store_run([CheckResult("freshness", True, "ok", {"age_hours": 1.0})])
        resp = client.get("/metrics")
        body = resp.text

        expected_families = [
            "backuppilot_checks_total",
            "backuppilot_checks_passed_total",
            "backuppilot_checks_failed_total",
            "backuppilot_last_check_timestamp",
            "backuppilot_last_check_passed",
            "backuppilot_check_result",
            "backuppilot_backup_age_hours",
        ]

        for family in expected_families:
            assert f"# HELP {family} " in body, f"Missing HELP for {family}"
            assert f"# TYPE {family} " in body, f"Missing TYPE for {family}"

    def test_metrics_freshness_bad_details_json(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Malformed details_json in freshness check is handled gracefully."""
        # Store a run with a freshness check that has invalid JSON details
        store_run([CheckResult("freshness", True, "ok", {"age_hours": 3.0})])

        # Corrupt the details_json in the DB directly
        from backuppilot.db import _connect

        conn = _connect()
        conn.execute(
            "UPDATE results SET details_json = 'not-json' WHERE check_name = 'freshness'"
        )
        conn.commit()
        conn.close()

        resp = client.get("/metrics")
        assert resp.status_code == 200
        # Should not crash, age metric just won't appear
        assert "backuppilot_backup_age_hours" not in resp.text

    def test_metrics_freshness_no_age_key(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Freshness check with details but no age_hours key is handled."""
        store_run([CheckResult("freshness", True, "ok", {"other_key": "val"})])
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "backuppilot_backup_age_hours" not in resp.text

    def test_metrics_invalid_timestamp_in_db(
        self,
        client: TestClient,
        tmp_config_dir: Path,
    ) -> None:
        """Corrupt timestamp in DB falls back to 0."""
        store_run([CheckResult("a", True, "ok")])

        from backuppilot.db import _connect

        conn = _connect()
        conn.execute("UPDATE runs SET timestamp = 'not-a-date'")
        conn.commit()
        conn.close()

        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "backuppilot_last_check_timestamp 0.000" in resp.text


# ---------------------------------------------------------------------------
# CLI serve command
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_serve_help(self) -> None:
        from click.testing import CliRunner

        from backuppilot.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output

    def test_serve_starts_uvicorn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """serve command calls uvicorn.run with correct arguments."""
        from click.testing import CliRunner

        from backuppilot.cli import main

        runner = CliRunner()
        with patch("uvicorn.run") as mock_run:
            result = runner.invoke(main, ["serve", "--host", "0.0.0.0", "--port", "9000"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            "backuppilot.api:app", host="0.0.0.0", port=9000, log_level="info"
        )

    def test_serve_uvicorn_not_installed(self) -> None:
        """serve command shows error when uvicorn not installed."""
        from click.testing import CliRunner

        from backuppilot.cli import main

        runner = CliRunner()
        with patch.dict("sys.modules", {"uvicorn": None}):
            # Force ImportError on import
            import builtins

            original_import = builtins.__import__

            def mock_import(name: str, *args: object, **kwargs: object) -> object:
                if name == "uvicorn":
                    raise ImportError("No module named 'uvicorn'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = runner.invoke(main, ["serve"])
        assert result.exit_code != 0
        assert "not installed" in result.output.lower()
