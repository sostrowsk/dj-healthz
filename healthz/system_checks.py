"""Django system checks: fail loudly at startup on misconfiguration (SPEC §4/§6)."""

import re
import sys
from importlib import util

from django.conf import settings
from django.core import checks

from healthz import conf, registry

PROBE_PATHS = ("healthz", "livez", "readyz", "health/")


def _dependency_missing(name: str) -> bool:
    # Already-imported modules are present even when their __spec__ is None
    # (kombu 5.x installs a lazy module subclass) — find_spec would raise
    # ValueError for them instead of answering. A None entry is Python's
    # "import blocked" sentinel and must still count as missing.
    if sys.modules.get(name) is not None:
        return False
    return util.find_spec(name) is None


@checks.register()
def check_healthz_config(app_configs, **kwargs):
    messages = []
    explicit = "CHECKS" in (getattr(settings, "HEALTHZ", None) or {})
    for check in registry.build_checks():
        if check.path is None:
            messages.append(checks.Error(
                f"HEALTHZ check '{check.name}' is not a built-in check and defines "
                "no 'check' dotted path.",
                hint=f"Built-ins: {', '.join(sorted(registry.BUILTINS))}.",
                id="healthz.E001",
            ))
            continue
        try:
            func = check.resolve()
        except ImportError:
            messages.append(checks.Error(
                f"HEALTHZ check '{check.name}' cannot be imported from '{check.path}'.",
                id="healthz.E001",
            ))
            continue
        if explicit:
            module = sys.modules.get(func.__module__)
            for dependency in getattr(module, "REQUIRES", ()):
                if _dependency_missing(dependency):
                    messages.append(checks.Error(
                        f"HEALTHZ check '{check.name}' requires the missing optional "
                        f"dependency '{dependency}'.",
                        id="healthz.E002",
                    ))
            is_configured = getattr(module, "is_configured", None)
            if is_configured is not None and not is_configured(check.options):
                messages.append(checks.Error(
                    f"HEALTHZ check '{check.name}' is explicitly enabled but its "
                    "required configuration (URL option/setting) is missing.",
                    id="healthz.E002",
                ))
    expose = conf.get("EXPOSE")
    if expose == "token" and not conf.get("TOKEN"):
        messages.append(checks.Error(
            'HEALTHZ["EXPOSE"] is "token" but HEALTHZ["TOKEN"] is not set.',
            id="healthz.E003",
        ))
    if expose not in ("public", "token", "staff"):
        messages.append(checks.Error(
            f'HEALTHZ["EXPOSE"] is {expose!r}; must be "public", "token" or "staff". '
            "The /health/ view fails closed for unknown values.",
            id="healthz.E004",
        ))
    return messages


@checks.register()
def check_ssl_redirect_exemption(app_configs, **kwargs):
    if not getattr(settings, "SECURE_SSL_REDIRECT", False):
        return []
    exempt = [re.compile(pattern) for pattern in settings.SECURE_REDIRECT_EXEMPT]
    covered = all(
        any(pattern.search(path) for pattern in exempt) for path in PROBE_PATHS
    )
    if covered:
        return []
    return [checks.Warning(
        "SECURE_SSL_REDIRECT is enabled but the healthz probe paths are not in "
        "SECURE_REDIRECT_EXEMPT; http probes will get 301s (curl -f treats 3xx as success).",
        hint=r'Add r"^(healthz|livez|readyz|health/)$" to SECURE_REDIRECT_EXEMPT.',
        id="healthz.W001",
    )]
