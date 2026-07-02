import os
import socket

from healthz.checks.cache import check


class RecordingCache:
    def __init__(self):
        self.store = {}
        self.set_calls = []
        self.deleted = []

    def set(self, key, value, timeout=None):
        self.set_calls.append((key, value, timeout))
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)


class MismatchCache(RecordingCache):
    def get(self, key):
        return "not-the-probe-value"


class ExplodingCache:
    def set(self, key, value, timeout=None):
        raise ConnectionError("redis://user:s3cretpass@cache.internal:6379/0")


def patch_caches(monkeypatch, mapping):
    monkeypatch.setattr("healthz.checks.cache.caches", mapping)


class TestOkPath:
    def test_round_trip_on_locmem_reports_ok(self):
        result = check()
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0

    def test_accepts_timeout_option(self):
        result = check(timeout=1.0)
        assert result["status"] == "ok"

    def test_probe_key_has_prefix_uuid_host_pid_and_ttl(self, monkeypatch):
        fake = RecordingCache()
        patch_caches(monkeypatch, {"default": fake})
        check()
        ((key, value, ttl),) = fake.set_calls
        assert key.startswith("healthz:")
        assert socket.gethostname() in key
        assert str(os.getpid()) in key
        assert ttl == 10
        assert fake.deleted == [key]

    def test_probe_key_is_unique_per_run(self, monkeypatch):
        fake = RecordingCache()
        patch_caches(monkeypatch, {"default": fake})
        check()
        check()
        first, second = (call[0] for call in fake.set_calls)
        assert first != second

    def test_alias_option_selects_cache(self, monkeypatch):
        default, probe = RecordingCache(), RecordingCache()
        patch_caches(monkeypatch, {"default": default, "probe": probe})
        result = check(alias="probe")
        assert result["status"] == "ok"
        assert probe.set_calls
        assert not default.set_calls


class TestErrorPath:
    def test_round_trip_mismatch_reports_error(self, monkeypatch, caplog):
        patch_caches(monkeypatch, {"default": MismatchCache()})
        with caplog.at_level("ERROR", logger="healthz"):
            result = check()
        assert result["status"] == "error"
        assert result["error_class"] == "CacheMismatch"
        assert "mismatch" in caplog.text

    def test_exception_reports_error_class_only(self, monkeypatch, caplog):
        patch_caches(monkeypatch, {"default": ExplodingCache()})
        with caplog.at_level("ERROR", logger="healthz"):
            result = check()
        assert result["status"] == "error"
        assert result["error_class"] == "ConnectionError"
        assert "s3cretpass" not in str(result)
        assert "s3cretpass" in caplog.text


class TestSkippedPath:
    def test_unconfigured_alias_reports_skipped(self):
        result = check(alias="no-such-alias")
        assert result["status"] == "skipped"
        assert "no-such-alias" in result["detail"]
