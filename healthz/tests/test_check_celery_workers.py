import sys
import time
import types

import pytest
from django.core.cache import cache

from healthz.checks.celery_workers import CACHE_KEY, check

NOW = 1_750_000_000.0


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr("healthz.checks.celery_workers.time.time", lambda: NOW)
    return NOW


class TestCeleryWorkersCheck:
    def test_missing_cache_key_reports_stale_probe(self):
        result = check(timeout=5.0)
        assert result["status"] == "error"
        assert result["error_class"] == "StaleProbe"
        assert isinstance(result["response_time_ms"], float)

    def test_fresh_ok_entry_reports_ok(self, frozen_now):
        cache.set(CACHE_KEY, {"status": "ok", "workers": 2, "time": NOW - 30})
        result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert "2" in result["detail"]

    def test_entry_older_than_default_max_age_reports_stale_probe(self, frozen_now):
        cache.set(CACHE_KEY, {"status": "ok", "workers": 2, "time": NOW - 121})
        result = check(timeout=5.0)
        assert result["status"] == "error"
        assert result["error_class"] == "StaleProbe"

    def test_max_age_option_overrides_default(self, frozen_now):
        cache.set(CACHE_KEY, {"status": "ok", "workers": 1, "time": NOW - 200})
        result = check(timeout=5.0, max_age=300)
        assert result["status"] == "ok"

    def test_fresh_error_entry_reports_error(self, frozen_now):
        cache.set(CACHE_KEY, {"status": "error", "workers": 0, "time": NOW - 10})
        result = check(timeout=5.0)
        assert result["status"] == "error"
        assert result["error_class"] == "NoWorkers"

    def test_malformed_entry_reports_stale_probe(self):
        cache.set(CACHE_KEY, {"status": "ok", "workers": 1})
        result = check(timeout=5.0)
        assert result["status"] == "error"
        assert result["error_class"] == "StaleProbe"


def fake_celery(ping):
    module = types.ModuleType("celery")
    module.current_app = types.SimpleNamespace(
        control=types.SimpleNamespace(ping=ping)
    )
    return module


class TestProbeWorkersTask:
    def test_module_imports_without_celery(self):
        assert "celery" not in sys.modules
        from healthz.tasks import probe_workers
        assert callable(probe_workers)

    def test_ping_replies_write_ok_entry(self, monkeypatch):
        from healthz import tasks
        seen = {}

        def ping(timeout):
            seen["timeout"] = timeout
            return [{"worker1@host": {"ok": "pong"}}, {"worker2@host": {"ok": "pong"}}]

        monkeypatch.setitem(sys.modules, "celery", fake_celery(ping))
        entry = tasks.probe_workers_impl(timeout=3.0)
        assert seen["timeout"] == 3.0
        assert entry["status"] == "ok"
        assert entry["workers"] == 2
        assert entry["time"] == pytest.approx(time.time(), abs=5)
        assert cache.get(CACHE_KEY) == entry

    def test_no_replies_write_error_entry(self, monkeypatch):
        from healthz import tasks
        monkeypatch.setitem(sys.modules, "celery", fake_celery(lambda timeout: []))
        entry = tasks.probe_workers_impl()
        assert entry["status"] == "error"
        assert entry["workers"] == 0
        assert cache.get(CACHE_KEY) == entry

    def test_ping_exception_writes_error_entry_without_raw_text(self, monkeypatch, caplog):
        from healthz import tasks

        def ping(timeout):
            raise ConnectionError("redis://:s3cretpass@broker.internal:6379/0")

        monkeypatch.setitem(sys.modules, "celery", fake_celery(ping))
        with caplog.at_level("ERROR", logger="healthz"):
            entry = tasks.probe_workers_impl()
        assert entry["status"] == "error"
        assert entry["error_class"] == "ConnectionError"
        assert "s3cretpass" not in str(entry)
        assert "s3cretpass" in caplog.text
        assert cache.get(CACHE_KEY) == entry

    def test_probe_workers_task_delegates_to_impl(self, monkeypatch):
        from healthz import tasks
        seen = {}

        def fake_impl(**options):
            seen.update(options)
            return {"status": "ok"}

        monkeypatch.setattr(tasks, "probe_workers_impl", fake_impl)
        assert callable(tasks.probe_workers)
        result = tasks._probe_workers(timeout=3.0, expires=60)
        assert result == {"status": "ok"}
        assert seen == {"timeout": 3.0, "expires": 60}
