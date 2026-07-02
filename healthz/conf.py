"""Access to settings.HEALTHZ with SPEC defaults (works with zero configuration)."""

from django.conf import settings

DEFAULTS = {
    "SERVICE_ID": None,
    "RELEASE_ID": None,
    "ENVIRONMENT": None,
    "EXPOSE": "public",
    "TOKEN": None,
    "CACHE_SECONDS": 0,
    "TIMEOUT": 5.0,
    "BUDGET": 10.0,
    "CHECKS": {"database": {}, "cache": {}},
}


def get(name: str):
    # HEALTHZ=None is treated exactly like an absent HEALTHZ setting.
    return (getattr(settings, "HEALTHZ", None) or {}).get(name, DEFAULTS[name])
