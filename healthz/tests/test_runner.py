import time

from django.core.cache import cache
from django.test import override_settings

from healthz.registry import ConfiguredCheck
from healthz.runner import run_checks

CALL_COUNT = {"counting": 0}


def ok_check(**options):
    return {"status": "ok", "response_time_ms": 0.5}


def error_check(**options):
    return {"status": "error", "response_time_ms": 0.5, "error_class": "ProbeError"}


def raising_check(**options):
    raise RuntimeError("postgres://user:s3cretpass@db.internal/prod")


def hung_check(**options):
    time.sleep(2)
    return {"status": "ok", "response_time_ms": 2000.0}


def slow_check(**options):
    time.sleep(0.2)
    return {"status": "ok", "response_time_ms": 200.0}


def bad_return_check(**options):
    return ["not", "a", "dict"]


def slow_ok_check(**options):
    time.sleep(0.4)
    return {"status": "ok", "response_time_ms": 400.0}


def late_check(**options):
    time.sleep(0.2)
    return {"status": "ok", "response_time_ms": 200.0}


def counting_check(**options):
    CALL_COUNT["counting"] += 1
    return {"status": "ok", "response_time_ms": 0.1}


def make(name, func_name, timeout=5.0, critical=True):
    return ConfiguredCheck(
        name=name,
        path=f"healthz.tests.test_runner.{func_name}",
        critical=critical,
        timeout=timeout,
        options={"timeout": timeout},
    )


class TestExecution:
    def test_all_results_returned(self):
        results = run_checks([make("a", "ok_check"), make("b", "error_check")])
        by_name = {r.name: r for r in results}
        assert by_name["a"].status == "ok"
        assert by_name["b"].status == "error"
        assert by_name["b"].error_class == "ProbeError"

    def test_options_passed_to_check(self):
        seen = {}

        def spy(**options):
            seen.update(options)
            return {"status": "ok", "response_time_ms": 0.1}

        check = ConfiguredCheck(name="spy", path="healthz.tests.test_runner.spy_check",
                                timeout=1.0, options={"timeout": 1.0, "aliases": ["default"]})
        globals()["spy_check"] = spy
        try:
            run_checks([check])
        finally:
            del globals()["spy_check"]
        assert seen == {"timeout": 1.0, "aliases": ["default"]}

    def test_raising_check_reports_error_class_only(self, caplog):
        with caplog.at_level("ERROR", logger="healthz"):
            (result,) = run_checks([make("boom", "raising_check")])
        assert result.status == "error"
        assert result.error_class == "RuntimeError"
        assert result.detail is None or "s3cretpass" not in result.detail
        assert "s3cretpass" in caplog.text

    def test_invalid_return_value_reports_error(self):
        (result,) = run_checks([make("bad", "bad_return_check")])
        assert result.status == "error"
        assert result.error_class == "InvalidCheckResult"

    def test_unknown_check_reports_error(self):
        (result,) = run_checks([ConfiguredCheck(name="ghost", path=None)])
        assert result.status == "error"
        assert result.error_class == "UnknownCheck"


class TestTimeouts:
    def test_hung_check_times_out_and_others_still_report(self):
        start = time.monotonic()
        results = run_checks([make("hung", "hung_check", timeout=0.2), make("fast", "ok_check")])
        elapsed = time.monotonic() - start
        by_name = {r.name: r for r in results}
        assert by_name["hung"].status == "error"
        assert by_name["hung"].error_class == "Timeout"
        assert by_name["fast"].status == "ok"
        assert elapsed < 1.5

    @override_settings(HEALTHZ={"BUDGET": 0.2, "CHECKS": {}})
    def test_overall_budget_bounds_generous_per_check_timeouts(self):
        start = time.monotonic()
        (result,) = run_checks([make("hung", "hung_check", timeout=30.0)])
        elapsed = time.monotonic() - start
        assert result.error_class == "Timeout"
        assert elapsed < 1.5

    def test_late_finish_beyond_own_timeout_reports_timeout(self):
        # A generous first wait keeps the collection loop busy while the second
        # check finishes after its own deadline — it must still report Timeout.
        results = run_checks([
            make("slow", "slow_ok_check", timeout=5.0),
            make("late", "late_check", timeout=0.05),
        ])
        by_name = {r.name: r for r in results}
        assert by_name["slow"].status == "ok"
        assert by_name["late"].status == "error"
        assert by_name["late"].error_class == "Timeout"

    def test_checks_run_concurrently(self):
        checks = [make(f"slow{i}", "slow_check") for i in range(3)]
        start = time.monotonic()
        results = run_checks(checks)
        elapsed = time.monotonic() - start
        assert all(r.status == "ok" for r in results)
        assert elapsed < 0.5


class TestResultCache:
    @override_settings(HEALTHZ={"CACHE_SECONDS": 30})
    def test_cached_results_skip_execution(self):
        cache.clear()
        CALL_COUNT["counting"] = 0
        checks = [make("counting", "counting_check")]
        first = run_checks(checks, cache_key="health")
        second = run_checks(checks, cache_key="health")
        assert CALL_COUNT["counting"] == 1
        assert [r.name for r in first] == [r.name for r in second]

    @override_settings(HEALTHZ={"CACHE_SECONDS": 30})
    def test_cache_backend_outage_falls_back_to_live_execution(self, monkeypatch, caplog):
        class BrokenCache:
            def get(self, key, default=None):
                raise ConnectionError("cache backend down")

            def set(self, key, value, timeout=None):
                raise ConnectionError("cache backend down")

        monkeypatch.setattr("healthz.runner.cache", BrokenCache())
        CALL_COUNT["counting"] = 0
        checks = [make("counting", "counting_check")]
        with caplog.at_level("ERROR", logger="healthz"):
            (result,) = run_checks(checks, cache_key="health")
        assert result.status == "ok"
        assert CALL_COUNT["counting"] == 1

    def test_cache_disabled_by_default(self):
        cache.clear()
        CALL_COUNT["counting"] = 0
        checks = [make("counting", "counting_check")]
        run_checks(checks, cache_key="health")
        run_checks(checks, cache_key="health")
        assert CALL_COUNT["counting"] == 2
