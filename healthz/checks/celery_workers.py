"""Reads the worker heartbeat cached by healthz.tasks.probe_workers (no live ping)."""

import time

from django.core.cache import cache

CACHE_KEY = "healthz:celery_workers"
DEFAULT_MAX_AGE = 120.0


def check(**options) -> dict:
    max_age = float(options.get("max_age", DEFAULT_MAX_AGE))
    start = time.monotonic()
    entry = cache.get(CACHE_KEY)
    elapsed_ms = (time.monotonic() - start) * 1000
    if not isinstance(entry, dict) or not isinstance(entry.get("time"), (int, float)):
        return {"status": "error", "response_time_ms": elapsed_ms, "error_class": "StaleProbe",
                "detail": "no worker probe result in cache"}
    age = time.time() - float(entry["time"])
    if age > max_age:
        return {"status": "error", "response_time_ms": elapsed_ms, "error_class": "StaleProbe",
                "detail": f"probe is {age:.0f}s old (max_age {max_age:.0f}s)"}
    workers = entry.get("workers", 0)
    if entry.get("status") != "ok":
        return {"status": "error", "response_time_ms": elapsed_ms, "error_class": "NoWorkers",
                "detail": f"workers: {workers}"}
    return {"status": "ok", "response_time_ms": elapsed_ms, "detail": f"workers: {workers}"}
