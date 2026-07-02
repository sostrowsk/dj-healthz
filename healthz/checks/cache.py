"""Built-in check: set/get/compare/delete round-trip on a Django cache backend."""

import logging
import os
import socket
import time
import uuid

from django.core.cache import InvalidCacheBackendError, caches

logger = logging.getLogger("healthz")

PROBE_TTL_SECONDS = 10


def is_configured(options: dict) -> bool:
    from django.conf import settings

    return options.get("alias", "default") in getattr(settings, "CACHES", {})


def check(**options) -> dict:
    alias = options.get("alias", "default")
    start = time.monotonic()
    try:
        backend = caches[alias]
    except InvalidCacheBackendError:
        return {
            "status": "skipped",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "detail": f"cache alias '{alias}' is not configured",
        }
    key = f"healthz:{uuid.uuid4().hex}:{socket.gethostname()}:{os.getpid()}"
    value = uuid.uuid4().hex
    try:
        backend.set(key, value, PROBE_TTL_SECONDS)
        stored = backend.get(key)
        backend.delete(key)
    except Exception as exc:
        logger.exception("healthz cache check failed on alias %r", alias)
        return {
            "status": "error",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "error_class": type(exc).__name__,
        }
    elapsed_ms = (time.monotonic() - start) * 1000
    if stored != value:
        logger.error("healthz cache check round-trip mismatch on alias %r", alias)
        return {"status": "error", "response_time_ms": elapsed_ms, "error_class": "CacheMismatch"}
    return {"status": "ok", "response_time_ms": elapsed_ms}
