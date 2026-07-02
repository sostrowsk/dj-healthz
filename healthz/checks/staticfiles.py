"""Built-in check: staticfiles manifest loadable / probe asset URL resolvable."""

import logging
import time

logger = logging.getLogger("healthz")


def check(**options) -> dict:
    start = time.monotonic()
    from django.apps import apps

    if not apps.is_installed("django.contrib.staticfiles"):
        return {
            "status": "skipped",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "detail": "django.contrib.staticfiles not in INSTALLED_APPS",
        }
    try:
        from django.contrib.staticfiles.storage import ManifestFilesMixin, staticfiles_storage

        if isinstance(staticfiles_storage, ManifestFilesMixin):
            if staticfiles_storage.read_manifest() is None:
                raise FileNotFoundError(
                    f"staticfiles manifest {staticfiles_storage.manifest_name!r} not found "
                    "(collectstatic not run?)"
                )
        else:
            staticfiles_storage.url("healthz-probe.txt")
    except Exception as exc:
        logger.exception("healthz staticfiles check failed")
        return {
            "status": "error",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "error_class": type(exc).__name__,
        }
    return {"status": "ok", "response_time_ms": (time.monotonic() - start) * 1000}
