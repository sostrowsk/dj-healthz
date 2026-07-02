"""Broker connectivity probe via kombu (Redis & RabbitMQ agnostic)."""

import logging
import time

from django.conf import settings

logger = logging.getLogger("healthz")

REQUIRES = ("kombu",)


def _broker_url(options: dict) -> str | None:
    return options.get("broker_url") or getattr(settings, "CELERY_BROKER_URL", None)


def is_configured(options: dict) -> bool:
    return bool(_broker_url(options))


def check(**options) -> dict:
    start = time.monotonic()
    try:
        import kombu
    except ImportError:
        return {"status": "skipped", "response_time_ms": (time.monotonic() - start) * 1000,
                "detail": "kombu not installed"}
    broker_url = _broker_url(options)
    if not broker_url:
        return {"status": "skipped", "response_time_ms": (time.monotonic() - start) * 1000,
                "detail": "no broker URL configured"}
    timeout = float(options.get("timeout", 5.0))
    connection = kombu.Connection(broker_url, transport_options={"connect_timeout": timeout})
    try:
        connection.ensure_connection(max_retries=1, timeout=timeout)
    except Exception as exc:
        logger.exception("healthz broker check failed")
        return {"status": "error", "response_time_ms": (time.monotonic() - start) * 1000,
                "error_class": type(exc).__name__}
    finally:
        connection.close()
    return {"status": "ok", "response_time_ms": (time.monotonic() - start) * 1000}
