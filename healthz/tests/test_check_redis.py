"""Tests for the redis built-in check (mocked redis package, no live server)."""

import os
import sys
import types
from unittest import mock

from django.test import override_settings

from healthz.checks import redis as redis_check


def make_fake_redis():
    stored = {}
    client = mock.MagicMock()
    client.set.side_effect = lambda key, value, **kwargs: stored.__setitem__(key, value)
    client.get.side_effect = stored.get
    module = types.ModuleType("redis")
    module.Redis = mock.MagicMock()
    module.Redis.from_url.return_value = client
    return module, client


def no_redis_url_env():
    patcher = mock.patch.dict(os.environ)
    patcher.start()
    os.environ.pop("REDIS_URL", None)
    return patcher


class TestOkPath:
    def test_round_trip_ok(self):
        module, client = make_fake_redis()
        with mock.patch.dict(sys.modules, {"redis": module}):
            result = redis_check.check(redis_url="redis://localhost:6379/0", timeout=2.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0
        client.set.assert_called_once()
        client.get.assert_called_once()
        client.delete.assert_called_once()
        client.close.assert_called_once()

    def test_probe_client_uses_check_timeout_for_sockets(self):
        module, _ = make_fake_redis()
        with mock.patch.dict(sys.modules, {"redis": module}):
            redis_check.check(redis_url="redis://localhost:6379/0", timeout=1.5)
        kwargs = module.Redis.from_url.call_args.kwargs
        assert kwargs["socket_timeout"] == 1.5
        assert kwargs["socket_connect_timeout"] == 1.5


class TestUrlSources:
    def test_option_wins_over_settings(self):
        module, _ = make_fake_redis()
        with mock.patch.dict(sys.modules, {"redis": module}):
            with override_settings(REDIS_URL="redis://from-settings/1"):
                redis_check.check(redis_url="redis://from-option/0", timeout=1.0)
        assert module.Redis.from_url.call_args.args[0] == "redis://from-option/0"

    def test_settings_redis_url_used(self):
        module, _ = make_fake_redis()
        with mock.patch.dict(sys.modules, {"redis": module}):
            with override_settings(REDIS_URL="redis://from-settings/1"):
                result = redis_check.check(timeout=1.0)
        assert result["status"] == "ok"
        assert module.Redis.from_url.call_args.args[0] == "redis://from-settings/1"

    def test_env_redis_url_used(self):
        module, _ = make_fake_redis()
        with mock.patch.dict(sys.modules, {"redis": module}):
            with mock.patch.dict(os.environ, {"REDIS_URL": "redis://from-env/2"}):
                result = redis_check.check(timeout=1.0)
        assert result["status"] == "ok"
        assert module.Redis.from_url.call_args.args[0] == "redis://from-env/2"


class TestSkipped:
    def test_skipped_when_package_missing(self):
        with mock.patch.dict(sys.modules, {"redis": None}):
            result = redis_check.check(redis_url="redis://localhost:6379/0", timeout=1.0)
        assert result["status"] == "skipped"
        assert isinstance(result["response_time_ms"], float)

    def test_skipped_when_no_url_configured(self):
        module, _ = make_fake_redis()
        env = no_redis_url_env()
        try:
            with mock.patch.dict(sys.modules, {"redis": module}):
                result = redis_check.check(timeout=1.0)
        finally:
            env.stop()
        assert result["status"] == "skipped"
        module.Redis.from_url.assert_not_called()


class TestErrorPath:
    def test_connection_error_reports_class_only(self, caplog):
        module, client = make_fake_redis()
        client.set.side_effect = ConnectionError("redis://user:s3cretpass@db.internal/0 refused")
        with mock.patch.dict(sys.modules, {"redis": module}):
            with caplog.at_level("ERROR", logger="healthz"):
                result = redis_check.check(redis_url="redis://x/0", timeout=1.0)
        assert result["status"] == "error"
        assert result["error_class"] == "ConnectionError"
        assert "s3cretpass" not in str(result)
        assert "s3cretpass" in caplog.text
        client.close.assert_called_once()

    def test_value_mismatch_reports_error(self):
        module, client = make_fake_redis()
        client.get.side_effect = None
        client.get.return_value = b"garbage"
        with mock.patch.dict(sys.modules, {"redis": module}):
            result = redis_check.check(redis_url="redis://x/0", timeout=1.0)
        assert result["status"] == "error"
        assert result["error_class"] == "ProbeMismatch"
        client.close.assert_called_once()


def test_requires_declares_redis():
    assert redis_check.REQUIRES == ("redis",)
