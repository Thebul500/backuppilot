"""Standardized event format for cross-product webhook integration.

All events follow a common schema so OpsEngine (and other consumers)
can ingest events from any product without product-specific parsing.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SOURCE = "backuppilot"


def create_event(
    event_type: str,
    severity: str,
    title: str,
    description: str = "",
    details: dict | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Create a standardized event payload.

    Args:
        event_type: Product-specific event type (e.g. 'backup_check_failed').
        severity: One of 'critical', 'warning', 'info'.
        title: Short human-readable summary.
        description: Longer description of what happened.
        details: Arbitrary product-specific details dict.
        tags: List of classification tags.

    Returns:
        Standardized event dict.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "severity": severity,
        "event_type": event_type,
        "title": title,
        "description": description,
        "details": details or {},
        "tags": tags or [],
    }


def send_event(event: dict, webhook_urls: list[str] | None = None) -> dict[str, bool]:
    """POST an event to configured webhook URLs and OpsEngine.

    Sends to:
    1. Any explicitly provided webhook_urls
    2. OPSENGINE_URL/api/events (if OPSENGINE_URL env var is set)

    Returns:
        Dict mapping each URL to success/failure bool.
    """
    targets: list[str] = list(webhook_urls or [])

    opsengine_url = os.environ.get("OPSENGINE_URL", "")
    if opsengine_url:
        targets.append(f"{opsengine_url.rstrip('/')}/api/events")

    results: dict[str, bool] = {}
    data = json.dumps(event).encode("utf-8")

    for url in targets:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                results[url] = 200 <= resp.status < 300
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("Event send failed to %s: %s", url, exc)
            results[url] = False

    return results
