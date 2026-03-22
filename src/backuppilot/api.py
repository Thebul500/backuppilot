"""FastAPI REST API for BackupPilot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from backuppilot import __version__
from backuppilot.checks import CheckResult
from backuppilot import config as config_mod
from backuppilot.config import ConfigError, load_config
from backuppilot.db import (
    _connect,
    get_failures,
    get_history,
    get_run_details,
    prune_history,
    store_run,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CheckRequest(BaseModel):
    """Request body for POST /api/check."""

    types: list[str] = Field(
        default_factory=lambda: ["docker", "opnsense", "gdrive"],
        description="Check types to run. Valid: docker, opnsense, gdrive.",
    )


class PruneRequest(BaseModel):
    """Request body for DELETE /api/history/prune."""

    keep_days: int = Field(default=100, ge=1, description="Number of recent runs to keep.")


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _get_api_key() -> str:
    """Read the expected API key from the environment."""
    key = os.environ.get("BACKUPPILOT_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=401,
            detail="BACKUPPILOT_API_KEY environment variable is not set.",
        )
    return key


def _verify_token(request: Request) -> str:
    """FastAPI dependency that enforces Bearer token auth."""
    api_key = _get_api_key()
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = auth_header[len("Bearer "):]
    if token != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return token


# ---------------------------------------------------------------------------
# Config dependency
# ---------------------------------------------------------------------------


def _require_config() -> dict[str, Any]:
    """Load config or return 503 if not initialized."""
    try:
        return load_config()
    except ConfigError:
        raise HTTPException(
            status_code=503,
            detail="BackupPilot not configured. Run 'backuppilot init' first.",
        )


# ---------------------------------------------------------------------------
# Prometheus metrics (text format, no prometheus_client dependency)
# ---------------------------------------------------------------------------


def _generate_metrics() -> str:
    """Generate Prometheus text exposition format from DB history."""
    lines: list[str] = []

    conn = _connect()
    try:
        # --- Counter metrics: total / passed / failed runs ---
        row = conn.execute("SELECT COUNT(*) AS cnt FROM runs").fetchone()
        total_runs = row["cnt"] if row else 0

        row = conn.execute("SELECT COUNT(*) AS cnt FROM runs WHERE passed = 1").fetchone()
        passed_runs = row["cnt"] if row else 0

        row = conn.execute("SELECT COUNT(*) AS cnt FROM runs WHERE passed = 0").fetchone()
        failed_runs = row["cnt"] if row else 0

        lines.append("# HELP backuppilot_checks_total Total validation runs.")
        lines.append("# TYPE backuppilot_checks_total counter")
        lines.append(f"backuppilot_checks_total {total_runs}")

        lines.append("# HELP backuppilot_checks_passed_total Runs where all checks passed.")
        lines.append("# TYPE backuppilot_checks_passed_total counter")
        lines.append(f"backuppilot_checks_passed_total {passed_runs}")

        lines.append("# HELP backuppilot_checks_failed_total Runs with at least one failure.")
        lines.append("# TYPE backuppilot_checks_failed_total counter")
        lines.append(f"backuppilot_checks_failed_total {failed_runs}")

        # --- Gauge metrics: last run ---
        last_run = conn.execute(
            "SELECT id, timestamp, passed FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if last_run:
            # Parse ISO timestamp to unix epoch
            ts_str = last_run["timestamp"]
            try:
                dt = datetime.fromisoformat(ts_str)
                unix_ts = dt.timestamp()
            except (ValueError, TypeError):
                unix_ts = 0.0

            lines.append(
                "# HELP backuppilot_last_check_timestamp "
                "Unix timestamp of most recent check."
            )
            lines.append("# TYPE backuppilot_last_check_timestamp gauge")
            lines.append(f"backuppilot_last_check_timestamp {unix_ts:.3f}")

            lines.append(
                "# HELP backuppilot_last_check_passed "
                "1 if last check all passed, 0 if any failed."
            )
            lines.append("# TYPE backuppilot_last_check_passed gauge")
            lines.append(f"backuppilot_last_check_passed {last_run['passed']}")

            # --- Per-check-type results from last run ---
            results = conn.execute(
                "SELECT check_name, passed, details_json "
                "FROM results WHERE run_id = ? ORDER BY id",
                (last_run["id"],),
            ).fetchall()

            if results:
                lines.append(
                    "# HELP backuppilot_check_result "
                    "1=pass, 0=fail for each check type from last run."
                )
                lines.append("# TYPE backuppilot_check_result gauge")
                for r in results:
                    check_type = r["check_name"]
                    lines.append(
                        f'backuppilot_check_result{{type="{check_type}"}} {r["passed"]}'
                    )

                # --- Backup age from freshness checks ---
                age_lines: list[str] = []
                for r in results:
                    if r["check_name"] == "freshness" and r["details_json"]:
                        try:
                            details = json.loads(r["details_json"])
                        except (json.JSONDecodeError, TypeError):
                            continue
                        age_hours = details.get("age_hours")
                        if age_hours is not None:
                            age_lines.append(
                                f'backuppilot_backup_age_hours{{type="backup"}} {age_hours}'
                            )

                if age_lines:
                    lines.append(
                        "# HELP backuppilot_backup_age_hours "
                        "Age of newest backup in hours."
                    )
                    lines.append("# TYPE backuppilot_backup_age_hours gauge")
                    lines.extend(age_lines)
        else:
            # No runs yet -- still emit gauges with defaults
            lines.append(
                "# HELP backuppilot_last_check_timestamp "
                "Unix timestamp of most recent check."
            )
            lines.append("# TYPE backuppilot_last_check_timestamp gauge")
            lines.append("backuppilot_last_check_timestamp 0")

            lines.append(
                "# HELP backuppilot_last_check_passed "
                "1 if last check all passed, 0 if any failed."
            )
            lines.append("# TYPE backuppilot_last_check_passed gauge")
            lines.append("backuppilot_last_check_passed 0")
    finally:
        conn.close()

    lines.append("")  # trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="BackupPilot API",
        version=__version__,
        description="REST API for backup lifecycle validation.",
    )

    # ------------------------------------------------------------------
    # GET /health  (no auth)
    # ------------------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, Any]:
        checks: dict[str, str] = {}
        overall = "ok"

        # Check DB connectivity
        try:
            conn = _connect()
            conn.execute("SELECT 1")
            conn.close()
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "failed"
            overall = "degraded"

        # Check config file exists
        if config_mod.CONFIG_PATH.exists():
            checks["config"] = "ok"
        else:
            checks["config"] = "failed"
            overall = "degraded"

        status_code = 200 if overall == "ok" else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall,
                "service": "backuppilot",
                "version": __version__,
                "checks": checks,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # ------------------------------------------------------------------
    # GET /metrics  (no auth — Prometheus scrape endpoint)
    # ------------------------------------------------------------------

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return _generate_metrics()

    # ------------------------------------------------------------------
    # POST /api/check  (auth required)
    # ------------------------------------------------------------------

    @app.post("/api/check", dependencies=[Depends(_verify_token)])
    def run_check(body: CheckRequest) -> dict[str, Any]:
        cfg = _require_config()
        valid_types = {"docker", "opnsense", "gdrive"}
        invalid = [t for t in body.types if t not in valid_types]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid check type(s): {', '.join(invalid)}. "
                f"Valid: {', '.join(sorted(valid_types))}.",
            )

        from backuppilot.cli import _validate_docker, _validate_gdrive, _validate_opnsense

        runners = {
            "docker": _validate_docker,
            "opnsense": _validate_opnsense,
            "gdrive": _validate_gdrive,
        }

        all_results: list[CheckResult] = []
        errors: list[str] = []
        for check_type in body.types:
            try:
                all_results.extend(runners[check_type](cfg))
            except ConfigError as e:
                errors.append(f"{check_type}: {e}")

        if not all_results and errors:
            return JSONResponse(
                status_code=422,
                content={"passed": False, "errors": errors, "results": [], "run_id": None},
            )

        # Store to history
        run_id: int | None = None
        if all_results:
            try:
                run_id = store_run(all_results)
            except Exception:
                pass  # non-fatal; results still returned

        return {
            "passed": all(r.passed for r in all_results),
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                }
                for r in all_results
            ],
            "summary": {
                "total": len(all_results),
                "passed": sum(1 for r in all_results if r.passed),
                "failed": sum(1 for r in all_results if not r.passed),
            },
            "errors": errors,
            "run_id": run_id,
        }

    # ------------------------------------------------------------------
    # GET /api/history  (auth required)
    # ------------------------------------------------------------------

    @app.get("/api/history", dependencies=[Depends(_verify_token)])
    def list_history(limit: int = 10, failures_only: bool = False) -> Any:
        if failures_only:
            return get_failures(days=30)
        return get_history(limit)

    # ------------------------------------------------------------------
    # GET /api/history/{run_id}  (auth required)
    # ------------------------------------------------------------------

    @app.get("/api/history/{run_id}", dependencies=[Depends(_verify_token)])
    def run_details(run_id: int) -> Any:
        details = get_run_details(run_id)
        if not details:
            raise HTTPException(status_code=404, detail=f"Run #{run_id} not found.")
        return details

    # ------------------------------------------------------------------
    # GET /api/status  (auth required)
    # ------------------------------------------------------------------

    @app.get("/api/status", dependencies=[Depends(_verify_token)])
    def current_status() -> dict[str, Any]:
        _require_config()
        runs = get_history(limit=1)
        if not runs:
            return {
                "last_check": None,
                "overall_passed": None,
                "message": "No checks have been run yet.",
            }

        last = runs[0]
        return {
            "last_check": last["timestamp"],
            "overall_passed": bool(last["passed"]),
            "total_checks": last["total_checks"],
            "failed_checks": last["failed_checks"],
            "run_id": last["id"],
        }

    # ------------------------------------------------------------------
    # DELETE /api/history/prune  (auth required)
    # ------------------------------------------------------------------

    @app.delete("/api/history/prune", dependencies=[Depends(_verify_token)])
    def prune(body: PruneRequest) -> dict[str, Any]:
        deleted = prune_history(body.keep_days)
        return {"deleted": deleted, "kept": body.keep_days}

    return app


app = create_app()
