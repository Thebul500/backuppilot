"""Signal notification via REST API using stdlib urllib."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from backuppilot.checks import CheckResult


class NotifyError(Exception):
    """Raised when notification fails."""


def _get_signal_config() -> tuple[str, str, str]:
    """Read Signal config from environment variables.

    Returns (api_url, sender, recipient).
    Raises NotifyError if not configured.
    """
    api_url = os.environ.get("SIGNAL_API_URL", "")
    sender = os.environ.get("SIGNAL_SENDER", "")
    recipient = os.environ.get("SIGNAL_RECIPIENT", "")

    missing = []
    if not api_url:
        missing.append("SIGNAL_API_URL")
    if not sender:
        missing.append("SIGNAL_SENDER")
    if not recipient:
        missing.append("SIGNAL_RECIPIENT")

    if missing:
        raise NotifyError(
            f"Signal not configured. Set environment variable(s): {', '.join(missing)}\n"
            "Example:\n"
            '  export SIGNAL_API_URL="http://127.0.0.1:8082/v2/send"\n'
            '  export SIGNAL_SENDER="+16304926987"\n'
            '  export SIGNAL_RECIPIENT="+17028858681"'
        )

    return api_url, sender, recipient


def format_report(results: list[CheckResult], overall_passed: bool) -> str:
    """Format check results into a notification message."""
    status = "OK" if overall_passed else "FAILURES DETECTED"
    lines = [f"[BackupPilot] {status}", ""]
    for r in results:
        icon = "\u2713" if r.passed else "\u2717"
        lines.append(f"{icon} {r.name}: {r.message}")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines.append(f"\n{passed}/{total} passed")
    return "\n".join(lines)


def send_signal(results: list[CheckResult], overall_passed: bool) -> None:
    """Send validation results via Signal.

    Raises NotifyError on configuration or send failure.
    """
    api_url, sender, recipient = _get_signal_config()

    body = format_report(results, overall_passed)
    payload = json.dumps({
        "message": body,
        "number": sender,
        "recipients": [recipient],
    }).encode()

    req = Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as resp:  # nosec B310 -- URL from env var
            if resp.status >= 300:
                raise NotifyError(
                    f"Signal API returned HTTP {resp.status}. "
                    "Check that signal-api container is running."
                )
    except HTTPError as e:
        raise NotifyError(
            f"Signal API error (HTTP {e.code}): {e.reason}. "
            "Check that signal-api container is running and account is registered."
        ) from e
    except URLError as e:
        raise NotifyError(
            f"Cannot reach Signal API at {api_url}: {e.reason}. "
            "Verify SIGNAL_API_URL and that the signal-api container is running."
        ) from e
    except TimeoutError as e:
        raise NotifyError(
            f"Signal API timed out after 10s ({api_url}). "
            "The signal-api container may be overloaded or unresponsive."
        ) from e


def emit_check_events(
    results: list[CheckResult],
    overall_passed: bool,
    webhook_urls: list[str] | None = None,
) -> list[dict]:
    """Emit standardized events for backup check results.

    Returns list of events that were created and sent.
    """
    from backuppilot.events import create_event, send_event

    events: list[dict] = []

    if overall_passed:
        passed_count = sum(1 for r in results if r.passed)
        ev = create_event(
            event_type="backup_check_passed",
            severity="info",
            title=f"All backup checks passed ({passed_count}/{len(results)})",
            description="All backup validation checks completed successfully",
            details={"passed": passed_count, "total": len(results)},
            tags=["reliability", "backup"],
        )
        events.append(ev)
    else:
        for r in results:
            if not r.passed:
                # Determine if stale vs failed
                if "stale" in r.message.lower() or "old" in r.message.lower():
                    event_type = "backup_stale"
                    severity = "warning"
                else:
                    event_type = "backup_check_failed"
                    severity = "critical"

                ev = create_event(
                    event_type=event_type,
                    severity=severity,
                    title=f"Backup check failed: {r.name} - {r.message}",
                    description=f"Check '{r.name}' failed: {r.message}",
                    details={"check_name": r.name, "message": r.message, **r.details},
                    tags=["reliability", "backup"],
                )
                events.append(ev)

    for ev in events:
        send_event(ev, webhook_urls=webhook_urls)

    return events
