"""Raw Redis round-trip (set/get/delete) with a dedicated short-lived probe client."""

import logging
import os
import time
import uuid

from django.conf import settings

logger = logging.getLogger("healthz")

REQUIRES = ("redis",)

PROBE_VALUE = b"probe"
PROBE_TTL_SECONDS = 10


def _redis_url(options: dict) -> str | None:
    return (options.get("redis_url") or getattr(settings, "REDIS_URL", None)
            or os.environ.get("REDIS_URL"))


def is_configured(options: dict) -> bool:
    return bool(_redis_url(options))


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


def check(**options) -> dict:
    start = time.monotonic()
    try:
        import redis
    except ImportError:
        return {"status": "skipped", "response_time_ms": _elapsed_ms(start),
                "detail": "redis package not installed"}
    url = _redis_url(options)
    if not url:
        return {"status": "skipped", "response_time_ms": _elapsed_ms(start),
                "detail": "no redis URL configured"}
    timeout = float(options.get("timeout", 5.0))
    key = f"healthz:redis:{uuid.uuid4().hex}"
    client = None
    try:
        client = redis.Redis.from_url(url, socket_timeout=timeout,
                                      socket_connect_timeout=timeout)
        client.set(key, PROBE_VALUE, ex=PROBE_TTL_SECONDS)
        value = client.get(key)
        client.delete(key)
        if value != PROBE_VALUE:
            return {"status": "error", "response_time_ms": _elapsed_ms(start),
                    "error_class": "ProbeMismatch"}
    except Exception as exc:
        logger.exception("healthz redis check failed")
        return {"status": "error", "response_time_ms": _elapsed_ms(start),
                "error_class": type(exc).__name__}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.exception("healthz redis probe client close failed")
    return {"status": "ok", "response_time_ms": _elapsed_ms(start)}
