"""Celery beat helper writing the worker heartbeat consumed by the celery_workers check."""

import logging
import time

from django.core.cache import cache

from healthz.checks.celery_workers import CACHE_KEY

logger = logging.getLogger("healthz")

try:
    from celery import shared_task
except ImportError:  # celery not installed: keep the module importable
    def shared_task(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda func: func


def probe_workers_impl(timeout: float = 5.0, expires: int = 299) -> dict:
    from celery import current_app

    try:
        replies = current_app.control.ping(timeout=timeout)
    except Exception as exc:
        logger.exception("healthz worker probe failed")
        entry = {"status": "error", "workers": 0, "time": time.time(),
                 "error_class": type(exc).__name__}
    else:
        workers = len(replies or [])
        entry = {"status": "ok" if workers else "error", "workers": workers,
                 "time": time.time()}
    cache.set(CACHE_KEY, entry, expires)
    return entry


def _probe_workers(timeout: float = 5.0, expires: int = 299) -> dict:
    return probe_workers_impl(timeout=timeout, expires=expires)


probe_workers = shared_task(ignore_result=True, name="healthz.tasks.probe_workers")(
    _probe_workers
)
