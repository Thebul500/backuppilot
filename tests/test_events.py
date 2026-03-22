"""Tests for standardized event format and sending."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backuppilot.checks import CheckResult
from backuppilot.events import SOURCE, create_event, send_event
from backuppilot.notify import emit_check_events


class TestCreateEvent:
    def test_basic_event(self):
        ev = create_event(
            event_type="backup_check_failed",
            severity="critical",
            title="Docker backup check failed",
        )
        assert ev["source"] == "backuppilot"
        assert ev["event_type"] == "backup_check_failed"
        assert ev["severity"] == "critical"
        assert ev["title"] == "Docker backup check failed"
        assert ev["description"] == ""
        assert ev["details"] == {}
        assert ev["tags"] == []
        assert "timestamp" in ev

    def test_full_event(self):
        ev = create_event(
            event_type="backup_stale",
            severity="warning",
            title="Backup is 48h old",
            description="Docker backup exceeds 24h threshold",
            details={"age_hours": 48.2, "threshold": 24},
            tags=["reliability", "backup"],
        )
        assert ev["description"] == "Docker backup exceeds 24h threshold"
        assert ev["details"]["age_hours"] == 48.2
        assert ev["tags"] == ["reliability", "backup"]

    def test_source_constant(self):
        assert SOURCE == "backuppilot"


class TestSendEvent:
    def test_send_to_webhook(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        ev = create_event("test", "info", "test event")

        with patch("backuppilot.events.urllib.request.urlopen", return_value=mock_resp) as mock_url:
            results = send_event(ev, webhook_urls=["https://hooks.example.com/test"])

        assert results["https://hooks.example.com/test"] is True
        req = mock_url.call_args[0][0]
        payload = json.loads(req.data.decode())
        assert payload["source"] == "backuppilot"

    def test_send_to_opsengine(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        ev = create_event("backup_check_failed", "critical", "test")

        with patch.dict("os.environ", {"OPSENGINE_URL": "http://localhost:8392"}), \
             patch("backuppilot.events.urllib.request.urlopen", return_value=mock_resp):
            results = send_event(ev)

        assert results["http://localhost:8392/api/events"] is True

    def test_send_failure(self):
        ev = create_event("test", "info", "test")

        with patch("backuppilot.events.urllib.request.urlopen",
                   side_effect=OSError("connection refused")):
            results = send_event(ev, webhook_urls=["http://bad.example.com"])

        assert results["http://bad.example.com"] is False

    def test_no_targets(self):
        ev = create_event("test", "info", "test")
        results = send_event(ev)
        assert results == {}


class TestEmitCheckEvents:
    def test_all_passed(self):
        results = [
            CheckResult("freshness", True, "2h old"),
            CheckResult("integrity", True, "Archive OK"),
        ]
        with patch("backuppilot.events.send_event"):
            events = emit_check_events(results, overall_passed=True)
        assert len(events) == 1
        assert events[0]["event_type"] == "backup_check_passed"
        assert events[0]["severity"] == "info"
        assert events[0]["details"]["passed"] == 2
        assert events[0]["details"]["total"] == 2

    def test_check_failed(self):
        results = [
            CheckResult("freshness", True, "2h old"),
            CheckResult("integrity", False, "Corrupt archive"),
        ]
        with patch("backuppilot.events.send_event"):
            events = emit_check_events(results, overall_passed=False)
        assert len(events) == 1
        assert events[0]["event_type"] == "backup_check_failed"
        assert events[0]["severity"] == "critical"
        assert "integrity" in events[0]["title"]

    def test_stale_backup(self):
        results = [
            CheckResult("freshness", False, "48h old (max 24h)", {"age_hours": 48.0}),
        ]
        with patch("backuppilot.events.send_event"):
            events = emit_check_events(results, overall_passed=False)
        assert len(events) == 1
        assert events[0]["event_type"] == "backup_stale"
        assert events[0]["severity"] == "warning"

    def test_multiple_failures(self):
        results = [
            CheckResult("freshness", False, "too old", {}),
            CheckResult("integrity", False, "corrupt", {}),
        ]
        with patch("backuppilot.events.send_event"):
            events = emit_check_events(results, overall_passed=False)
        assert len(events) == 2

    def test_events_sent_to_webhook(self):
        results = [CheckResult("test", True, "ok")]
        with patch("backuppilot.events.send_event") as mock_send:
            emit_check_events(results, overall_passed=True, webhook_urls=["http://hook.example.com"])
        assert mock_send.called
        call_kwargs = mock_send.call_args
        assert call_kwargs[1]["webhook_urls"] == ["http://hook.example.com"]

    def test_stale_detection_via_old_keyword(self):
        """'old' keyword in message triggers backup_stale event type."""
        results = [
            CheckResult("freshness", False, "168.5h old (max 170h)", {}),
        ]
        with patch("backuppilot.events.send_event"):
            events = emit_check_events(results, overall_passed=False)
        assert events[0]["event_type"] == "backup_stale"

    def test_details_forwarded(self):
        """Check result details are included in the event."""
        results = [
            CheckResult("integrity", False, "Corrupt archive", {"error": "bad header"}),
        ]
        with patch("backuppilot.events.send_event"):
            events = emit_check_events(results, overall_passed=False)
        assert events[0]["details"]["error"] == "bad header"
