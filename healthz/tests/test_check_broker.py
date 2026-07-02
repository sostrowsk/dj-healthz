import sys
import types
from unittest import mock

from django.test import override_settings

from healthz.checks import broker


def make_fake_kombu(ensure_side_effect=None):
    fake = types.ModuleType("kombu")
    connection = mock.MagicMock(name="connection")
    if ensure_side_effect is not None:
        connection.ensure_connection.side_effect = ensure_side_effect
    fake.Connection = mock.MagicMock(name="Connection", return_value=connection)
    return fake, connection


class TestBrokerOk:
    def test_ok_with_broker_url_option(self):
        fake, connection = make_fake_kombu()
        with mock.patch.dict(sys.modules, {"kombu": fake}):
            result = broker.check(broker_url="redis://localhost:6379/0", timeout=3.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        args, kwargs = fake.Connection.call_args
        assert args == ("redis://localhost:6379/0",)
        assert kwargs["transport_options"] == {"connect_timeout": 3.0}
        connection.ensure_connection.assert_called_once_with(max_retries=1, timeout=3.0)
        connection.close.assert_called_once()

    @override_settings(CELERY_BROKER_URL="amqp://guest@rabbit:5672//")
    def test_url_falls_back_to_celery_broker_url_setting(self):
        fake, connection = make_fake_kombu()
        with mock.patch.dict(sys.modules, {"kombu": fake}):
            result = broker.check(timeout=5.0)
        assert result["status"] == "ok"
        assert fake.Connection.call_args.args == ("amqp://guest@rabbit:5672//",)

    @override_settings(CELERY_BROKER_URL="amqp://guest@rabbit:5672//")
    def test_broker_url_option_wins_over_setting(self):
        fake, connection = make_fake_kombu()
        with mock.patch.dict(sys.modules, {"kombu": fake}):
            broker.check(broker_url="redis://override:6379/1", timeout=5.0)
        assert fake.Connection.call_args.args == ("redis://override:6379/1",)


class TestBrokerError:
    def test_connection_failure_reports_error_class_only(self, caplog):
        secret_url = "amqp://user:s3cretpass@broker.internal:5672//"
        fake, connection = make_fake_kombu(
            ensure_side_effect=ConnectionRefusedError(f"cannot reach {secret_url}")
        )
        with caplog.at_level("ERROR", logger="healthz"):
            with mock.patch.dict(sys.modules, {"kombu": fake}):
                result = broker.check(broker_url=secret_url, timeout=2.0)
        assert result["status"] == "error"
        assert result["error_class"] == "ConnectionRefusedError"
        assert all("s3cretpass" not in str(value) for value in result.values())
        assert "s3cretpass" in caplog.text

    def test_connection_closed_on_failure(self):
        fake, connection = make_fake_kombu(ensure_side_effect=OSError("boom"))
        with mock.patch.dict(sys.modules, {"kombu": fake}):
            broker.check(broker_url="redis://localhost:6379/0", timeout=2.0)
        connection.close.assert_called_once()


class TestBrokerSkipped:
    def test_skipped_when_kombu_missing(self):
        with mock.patch.dict(sys.modules, {"kombu": None}):
            result = broker.check(broker_url="redis://localhost:6379/0", timeout=5.0)
        assert result["status"] == "skipped"
        assert isinstance(result["response_time_ms"], float)

    @override_settings(CELERY_BROKER_URL=None)
    def test_skipped_without_broker_url(self):
        fake, connection = make_fake_kombu()
        with mock.patch.dict(sys.modules, {"kombu": fake}):
            result = broker.check(timeout=5.0)
        assert result["status"] == "skipped"
        fake.Connection.assert_not_called()


def test_declares_kombu_requirement():
    assert broker.REQUIRES == ("kombu",)
