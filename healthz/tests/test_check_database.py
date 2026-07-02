from unittest import mock

import pytest
from django.db import OperationalError
from django.test import override_settings

from healthz.checks.database import check

DSN_ERROR = OperationalError("postgres://user:s3cretpass@db.internal/prod refused")


def mock_connections():
    return mock.patch("django.db.connections", mock.MagicMock())


class TestOkPath:
    @pytest.mark.django_db
    def test_select_1_on_default_alias_reports_ok(self):
        result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0

    @pytest.mark.django_db
    def test_detail_contains_per_alias_timing(self):
        result = check(timeout=5.0)
        assert "default=" in result["detail"]
        assert result["detail"].endswith("ms")

    def test_checks_every_configured_alias(self):
        with mock_connections() as connections:
            with override_settings(DATABASES={"default": {}, "replica": {}}):
                result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert connections.__getitem__.call_args_list == [
            mock.call("default"), mock.call("replica"),
        ]

    def test_aliases_option_limits_checked_databases(self):
        with mock_connections() as connections:
            result = check(timeout=5.0, aliases=["replica"])
        assert result["status"] == "ok"
        connections.__getitem__.assert_called_once_with("replica")
        cursor = connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cursor.execute.assert_called_once_with("SELECT 1")


class TestErrorPath:
    def test_failing_alias_reports_error_class_only(self, caplog):
        with mock_connections() as connections:
            connections.__getitem__.return_value.cursor.side_effect = DSN_ERROR
            with caplog.at_level("ERROR", logger="healthz"):
                result = check(timeout=5.0, aliases=["default"])
        assert result["status"] == "error"
        assert result["error_class"] == "OperationalError"
        assert isinstance(result["response_time_ms"], float)
        assert "s3cretpass" not in str(result)
        assert "s3cretpass" in caplog.text

    def test_error_detail_names_failing_alias(self, caplog):
        with mock_connections() as connections:
            connections.__getitem__.return_value.cursor.side_effect = DSN_ERROR
            with caplog.at_level("ERROR", logger="healthz"):
                result = check(timeout=5.0, aliases=["replica"])
        assert result["detail"] == "alias 'replica' failed"


class TestSkippedPath:
    def test_no_databases_configured_reports_skipped(self):
        with override_settings(DATABASES={}):
            result = check(timeout=5.0)
        assert result["status"] == "skipped"
        assert isinstance(result["response_time_ms"], float)
