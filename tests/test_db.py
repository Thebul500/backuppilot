"""Tests for SQLite persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from backuppilot.checks import CheckResult
from backuppilot.db import get_failures, get_history, get_run_details, prune_history, store_run


class TestStoreRun:
    def test_stores_and_returns_id(self, tmp_config_dir: Path) -> None:
        results = [
            CheckResult("test1", True, "all good"),
            CheckResult("test2", False, "not good", {"detail": "value"}),
        ]
        run_id = store_run(results)
        assert isinstance(run_id, int)
        assert run_id >= 1

    def test_increments_run_id(self, tmp_config_dir: Path) -> None:
        r1 = store_run([CheckResult("a", True, "ok")])
        r2 = store_run([CheckResult("b", True, "ok")])
        assert r2 > r1

    def test_db_file_created(self, tmp_config_dir: Path) -> None:
        store_run([CheckResult("test", True, "ok")])
        db_path = tmp_config_dir / "history.db"
        assert db_path.exists()


class TestGetHistory:
    def test_empty_history(self, tmp_config_dir: Path) -> None:
        assert get_history() == []

    def test_returns_runs(self, tmp_config_dir: Path) -> None:
        store_run([CheckResult("a", True, "ok")])
        store_run([CheckResult("b", False, "fail")])
        runs = get_history()
        assert len(runs) == 2
        # Most recent first
        assert runs[0]["passed"] == 0  # failed run
        assert runs[1]["passed"] == 1  # passed run

    def test_limit(self, tmp_config_dir: Path) -> None:
        for i in range(5):
            store_run([CheckResult(f"check{i}", True, "ok")])
        assert len(get_history(limit=3)) == 3

    def test_run_fields(self, tmp_config_dir: Path) -> None:
        store_run([
            CheckResult("pass1", True, "ok"),
            CheckResult("fail1", False, "bad"),
        ])
        run = get_history(1)[0]
        assert "id" in run
        assert "timestamp" in run
        assert run["total_checks"] == 2
        assert run["failed_checks"] == 1
        assert run["passed"] == 0  # overall failed


class TestGetRunDetails:
    def test_returns_check_results(self, tmp_config_dir: Path) -> None:
        run_id = store_run([
            CheckResult("check_a", True, "msg_a"),
            CheckResult("check_b", False, "msg_b"),
        ])
        details = get_run_details(run_id)
        assert len(details) == 2
        assert details[0]["check_name"] == "check_a"
        assert details[0]["passed"] == 1
        assert details[1]["check_name"] == "check_b"
        assert details[1]["passed"] == 0

    def test_nonexistent_run(self, tmp_config_dir: Path) -> None:
        assert get_run_details(9999) == []


class TestGetFailures:
    def test_no_failures(self, tmp_config_dir: Path) -> None:
        store_run([CheckResult("pass", True, "ok")])
        assert get_failures() == []

    def test_returns_failures(self, tmp_config_dir: Path) -> None:
        store_run([
            CheckResult("pass", True, "ok"),
            CheckResult("fail", False, "broken"),
        ])
        failures = get_failures()
        assert len(failures) == 1
        assert failures[0]["check_name"] == "fail"
        assert failures[0]["message"] == "broken"


class TestPruneHistory:
    def test_prune_old_runs(self, tmp_config_dir: Path) -> None:
        for i in range(10):
            store_run([CheckResult(f"check{i}", True, "ok")])
        deleted = prune_history(keep=3)
        assert deleted > 0
        remaining = get_history(limit=100)
        assert len(remaining) <= 3

    def test_prune_nothing(self, tmp_config_dir: Path) -> None:
        store_run([CheckResult("check", True, "ok")])
        deleted = prune_history(keep=100)
        assert deleted == 0
