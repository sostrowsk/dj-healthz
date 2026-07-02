"""Built-in check: pending migrations via MigrationExecutor plan."""

import logging
import time

logger = logging.getLogger("healthz")


def check(**options) -> dict:
    from django.conf import settings
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    start = time.monotonic()
    if not settings.DATABASES:
        return {
            "status": "skipped",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "detail": "no databases configured",
        }
    try:
        executor = MigrationExecutor(connections["default"])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:
        logger.exception("healthz migrations check failed")
        return {
            "status": "error",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "error_class": type(exc).__name__,
        }
    elapsed_ms = (time.monotonic() - start) * 1000
    if plan:
        return {
            "status": "error",
            "response_time_ms": elapsed_ms,
            "detail": f"{len(plan)} pending migrations",
        }
    return {"status": "ok", "response_time_ms": elapsed_ms}
