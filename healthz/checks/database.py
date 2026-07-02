"""Built-in check: SELECT 1 against every configured database alias."""

import logging
import time

logger = logging.getLogger("healthz")


def check(**options) -> dict:
    from django.conf import settings
    from django.db import connections

    start = time.monotonic()
    aliases = options.get("aliases") or list(settings.DATABASES)
    if not aliases:
        return {
            "status": "skipped",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "detail": "no databases configured",
        }
    timings = []
    for alias in aliases:
        alias_start = time.monotonic()
        try:
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:
            logger.exception("healthz database check failed for alias %r", alias)
            return {
                "status": "error",
                "response_time_ms": (time.monotonic() - start) * 1000,
                "detail": f"alias '{alias}' failed",
                "error_class": type(exc).__name__,
            }
        timings.append(f"{alias}={(time.monotonic() - alias_start) * 1000:.1f}ms")
    return {
        "status": "ok",
        "response_time_ms": (time.monotonic() - start) * 1000,
        "detail": ", ".join(timings),
    }
