from unittest import mock

import pytest
from django.db import OperationalError
from django.test import override_settings

from healthz.checks.migrations import check

DSN_ERROR = OperationalError("postgres://user:s3cretpass@db.internal/prod refused")


def mock_executor(**attrs):
    executor = mock.MagicMock(**attrs)
    return mock.patch(
        "django.db.migrations.executor.MigrationExecutor", return_value=executor
    ), executor


class TestOkPath:
    @pytest.mark.django_db
    def test_no_pending_migrations_reports_ok(self):
        result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0

    def test_plan_is_built_against_graph_leaf_nodes(self):
        patcher, executor = mock_executor(**{"migration_plan.return_value": []})
        with patcher:
            result = check(timeout=5.0)
        assert result["status"] == "ok"
        executor.migration_plan.assert_called_once_with(
            executor.loader.graph.leaf_nodes.return_value
        )


class TestErrorPath:
    def test_pending_migrations_report_error_with_count(self):
        plan = [(mock.Mock(), False), (mock.Mock(), False)]
        patcher, _ = mock_executor(**{"migration_plan.return_value": plan})
        with patcher:
            result = check(timeout=5.0)
        assert result["status"] == "error"
        assert result["detail"] == "2 pending migrations"
        assert isinstance(result["response_time_ms"], float)

    def test_executor_failure_reports_error_class_only(self, caplog):
        with mock.patch(
            "django.db.migrations.executor.MigrationExecutor", side_effect=DSN_ERROR
        ):
            with caplog.at_level("ERROR", logger="healthz"):
                result = check(timeout=5.0)
        assert result["status"] == "error"
        assert result["error_class"] == "OperationalError"
        assert isinstance(result["response_time_ms"], float)
        assert "s3cretpass" not in str(result)
        assert "s3cretpass" in caplog.text


class TestSkippedPath:
    def test_no_databases_configured_reports_skipped(self):
        with override_settings(DATABASES={}):
            result = check(timeout=5.0)
        assert result["status"] == "skipped"
        assert isinstance(result["response_time_ms"], float)
