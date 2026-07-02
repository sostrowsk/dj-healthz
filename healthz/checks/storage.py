"""Built-in check: default_storage save/exists/delete of a tiny probe file.

For remote backends (S3 via django-storages etc.) configure this check with
``critical: False`` and ``readiness: False`` — every probe costs real PUT/HEAD/
DELETE requests and belongs in ``/health/`` diagnostics only, never in the
readiness path. Option ``storage`` accepts a dotted path to an alternative
storage class or instance.
"""

import contextlib
import logging
import time
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.module_loading import import_string

logger = logging.getLogger("healthz")


def _resolve_storage(dotted_path: str | None):
    if not dotted_path:
        return default_storage
    storage = import_string(dotted_path)
    if isinstance(storage, type):
        storage = storage()
    return storage


def check(**options) -> dict:
    start = time.monotonic()
    probe_name = f"healthz/probe-{uuid.uuid4().hex}.txt"
    storage = None
    saved_name = None
    try:
        storage = _resolve_storage(options.get("storage"))
        saved_name = storage.save(probe_name, ContentFile(b"healthz storage probe"))
        if not storage.exists(saved_name):
            raise FileNotFoundError("probe file missing after save")
        storage.delete(saved_name)
    except Exception as exc:
        if storage is not None and saved_name is not None:
            with contextlib.suppress(Exception):
                storage.delete(saved_name)
        logger.exception("healthz storage check failed")
        return {
            "status": "error",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "error_class": type(exc).__name__,
        }
    return {"status": "ok", "response_time_ms": (time.monotonic() - start) * 1000}
