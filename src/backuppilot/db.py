"""SQLite persistence for validation history."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from typing import Any

from backuppilot.checks import CheckResult
from backuppilot.config import CONFIG_DIR

DB_PATH = CONFIG_DIR / "history.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    passed INTEGER NOT NULL,
    total_checks INTEGER NOT NULL,
    failed_checks INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    check_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT
);
"""


def _connect() -> sqlite3.Connection:
    """Open or create the history database with secure permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    db_exists = DB_PATH.exists()
    conn = sqlite3.connect(str(DB_PATH))

    if not db_exists:
        os.chmod(DB_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_CREATE_SQL)
    return conn


def store_run(results: list[CheckResult]) -> int:
    """Store a validation run and its results. Returns the run ID."""
    conn = _connect()
    try:
        passed = all(r.passed for r in results)
        total = len(results)
        failed = sum(1 for r in results if not r.passed)
        now = datetime.now(timezone.utc).isoformat()

        cur = conn.execute(
            "INSERT INTO runs (timestamp, passed, total_checks, failed_checks) "
            "VALUES (?, ?, ?, ?)",
            (now, int(passed), total, failed),
        )
        run_id = cur.lastrowid
        if run_id is None:
            raise RuntimeError("Failed to insert run -- no lastrowid returned")

        for r in results:
            conn.execute(
                "INSERT INTO results (run_id, check_name, passed, message, details_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    r.name,
                    int(r.passed),
                    r.message,
                    json.dumps(r.details) if r.details else None,
                ),
            )

        conn.commit()
        return run_id
    finally:
        conn.close()


def get_history(limit: int = 10) -> list[dict[str, Any]]:
    """Return the last N runs with summary info."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, passed, total_checks, failed_checks "
            "FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run_details(run_id: int) -> list[dict[str, Any]]:
    """Return all check results for a given run."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT check_name, passed, message, details_json "
            "FROM results WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_failures(days: int = 30) -> list[dict[str, Any]]:
    """Return all failed checks in the last N days."""
    conn = _connect()
    try:
        cutoff = datetime.now(timezone.utc).isoformat()[:10]
        rows = conn.execute(
            """SELECT r.id as run_id, r.timestamp, res.check_name, res.message
               FROM runs r JOIN results res ON r.id = res.run_id
               WHERE res.passed = 0 AND r.timestamp >= date(?, '-' || ? || ' days')
               ORDER BY r.id DESC""",
            (cutoff, days),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def prune_history(keep: int = 100) -> int:
    """Delete old runs keeping only the most recent `keep` entries.

    Returns the number of runs deleted.
    """
    conn = _connect()
    try:
        # Find the cutoff run id
        row = conn.execute(
            "SELECT id FROM runs ORDER BY id DESC LIMIT 1 OFFSET ?",
            (keep - 1,),
        ).fetchone()
        if row is None:
            return 0  # fewer runs than keep limit

        cutoff_id = row["id"]
        conn.execute("DELETE FROM results WHERE run_id < ?", (cutoff_id,))
        cur = conn.execute("DELETE FROM runs WHERE id < ?", (cutoff_id,))
        deleted = cur.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()
