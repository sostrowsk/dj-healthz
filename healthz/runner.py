"""ThreadPoolExecutor engine: per-check timeout, overall budget, optional result cache."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from django.core.cache import cache

from healthz import conf
from healthz.protocol import CheckResult
from healthz.registry import ConfiguredCheck

logger = logging.getLogger("healthz")


def run_checks(checks: list[ConfiguredCheck], cache_key: str | None = None) -> list[CheckResult]:
    cache_seconds = conf.get("CACHE_SECONDS")
    full_key = f"healthz:results:{cache_key}" if cache_key else None
    if cache_seconds > 0 and full_key:
        try:
            cached = cache.get(full_key)
        except Exception:
            logger.exception("healthz result cache get failed for %r", full_key)
        else:
            if cached is not None:
                return cached
    results = _execute(checks)
    if cache_seconds > 0 and full_key:
        try:
            cache.set(full_key, results, cache_seconds)
        except Exception:
            logger.exception("healthz result cache set failed for %r", full_key)
    return results


def _execute(checks: list[ConfiguredCheck]) -> list[CheckResult]:
    if not checks:
        return []
    budget = float(conf.get("BUDGET"))
    start = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="healthz")
    futures = [(check, executor.submit(_run_one, check)) for check in checks]
    results = []
    for check, future in futures:
        deadline = start + min(check.timeout, budget)
        wait = max(0.0, deadline - time.monotonic())
        try:
            results.append(future.result(timeout=wait))
        except FutureTimeoutError:
            future.cancel()
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error("healthz check %r timed out after %.0f ms", check.name, elapsed_ms)
            results.append(CheckResult(name=check.name, status="error",
                                       response_time_ms=elapsed_ms, critical=check.critical,
                                       error_class="Timeout"))
    executor.shutdown(wait=False, cancel_futures=True)
    return results


def _run_one(check: ConfiguredCheck) -> CheckResult:
    start = time.monotonic()
    try:
        func = check.resolve()
        output = func(**check.options)
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.exception("healthz check %r raised", check.name)
        return CheckResult(name=check.name, status="error", response_time_ms=elapsed_ms,
                           critical=check.critical, error_class=type(exc).__name__)
    elapsed_ms = (time.monotonic() - start) * 1000
    # Enforce the deadline here as well: a future can finish past its timeout
    # while the collection loop is still waiting on an earlier, slower check.
    if elapsed_ms > check.timeout * 1000:
        logger.error("healthz check %r exceeded its %.1fs timeout (%.0f ms)",
                     check.name, check.timeout, elapsed_ms)
        return CheckResult(name=check.name, status="error", response_time_ms=elapsed_ms,
                           critical=check.critical, error_class="Timeout")
    return CheckResult.from_output(check.name, output, check.critical, elapsed_ms=elapsed_ms)
