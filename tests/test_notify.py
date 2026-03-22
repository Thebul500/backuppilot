"""Tests for Signal notification module."""

from __future__ import annotations

import json
from http.client import HTTPResponse
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backuppilot.checks import CheckResult
from backuppilot.notify import NotifyError, _get_signal_config, format_report, send_signal


class TestGetSignalConfig:
    def test_all_vars_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.setenv("SIGNAL_RECIPIENT", "+2222")
        url, sender, recipient = _get_signal_config()
        assert url == "http://localhost:8082/v2/send"
        assert sender == "+1111"
        assert recipient == "+2222"

    def test_missing_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SIGNAL_API_URL", raising=False)
        monkeypatch.delenv("SIGNAL_SENDER", raising=False)
        monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
        with pytest.raises(NotifyError, match="SIGNAL_API_URL"):
            _get_signal_config()

    def test_missing_one_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
        with pytest.raises(NotifyError, match="SIGNAL_RECIPIENT"):
            _get_signal_config()


class TestFormatReport:
    def test_all_passed(self) -> None:
        results = [
            CheckResult("check1", True, "all good"),
            CheckResult("check2", True, "looks fine"),
        ]
        msg = format_report(results, overall_passed=True)
        assert "[BackupPilot] OK" in msg
        assert "\u2713 check1" in msg
        assert "2/2 passed" in msg

    def test_some_failed(self) -> None:
        results = [
            CheckResult("check1", True, "ok"),
            CheckResult("check2", False, "broken"),
        ]
        msg = format_report(results, overall_passed=False)
        assert "FAILURES DETECTED" in msg
        assert "\u2717 check2" in msg
        assert "1/2 passed" in msg


class TestSendSignal:
    def test_send_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.setenv("SIGNAL_RECIPIENT", "+2222")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("backuppilot.notify.urlopen", return_value=mock_resp):
            send_signal([CheckResult("test", True, "ok")], True)

    def test_send_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.setenv("SIGNAL_RECIPIENT", "+2222")

        from urllib.error import HTTPError
        exc = HTTPError("http://test", 500, "Server Error", {}, BytesIO(b""))

        with patch("backuppilot.notify.urlopen", side_effect=exc):
            with pytest.raises(NotifyError, match="HTTP 500"):
                send_signal([CheckResult("test", False, "bad")], False)

    def test_send_url_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.setenv("SIGNAL_RECIPIENT", "+2222")

        from urllib.error import URLError
        exc = URLError("Connection refused")

        with patch("backuppilot.notify.urlopen", side_effect=exc):
            with pytest.raises(NotifyError, match="Cannot reach Signal API"):
                send_signal([CheckResult("test", False, "bad")], False)

    def test_send_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNAL_API_URL", "http://localhost:8082/v2/send")
        monkeypatch.setenv("SIGNAL_SENDER", "+1111")
        monkeypatch.setenv("SIGNAL_RECIPIENT", "+2222")

        with patch("backuppilot.notify.urlopen", side_effect=TimeoutError):
            with pytest.raises(NotifyError, match="timed out"):
                send_signal([CheckResult("test", False, "bad")], False)

    def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SIGNAL_API_URL", raising=False)
        monkeypatch.delenv("SIGNAL_SENDER", raising=False)
        monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
        with pytest.raises(NotifyError, match="Signal not configured"):
            send_signal([CheckResult("test", True, "ok")], True)
