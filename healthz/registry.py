"""Resolve configured checks: built-in names and custom dotted paths (lazily)."""

from dataclasses import dataclass, field

from django.utils.module_loading import import_string

from healthz import conf

BUILTINS = {
    name: f"healthz.checks.{name}.check"
    for name in (
        "database", "cache", "redis", "broker", "celery_workers",
        "filesystem", "storage", "migrations", "staticfiles",
    )
}

RESERVED_OPTIONS = ("check", "critical", "readiness")


class UnknownCheck(Exception):
    """Configured check name is neither a built-in nor a dotted path."""


@dataclass(frozen=True)
class ConfiguredCheck:
    name: str
    path: str | None
    critical: bool = True
    readiness: bool = True
    timeout: float = 5.0
    options: dict = field(default_factory=dict)

    def resolve(self):
        if self.path is None:
            raise UnknownCheck(self.name)
        return import_string(self.path)


def build_checks() -> list[ConfiguredCheck]:
    default_timeout = float(conf.get("TIMEOUT"))
    checks = []
    for name, options in conf.get("CHECKS").items():
        path = options.get("check", BUILTINS.get(name))
        timeout = float(options.get("timeout", default_timeout))
        extra = {k: v for k, v in options.items() if k not in RESERVED_OPTIONS}
        extra["timeout"] = timeout
        checks.append(ConfiguredCheck(
            name=name,
            path=path,
            critical=bool(options.get("critical", True)),
            readiness=bool(options.get("readiness", True)),
            timeout=timeout,
            options=extra,
        ))
    return checks


def resolution_errors() -> list[str]:
    """Collect (not raise) resolution problems for Django system checks."""
    errors = []
    for check in build_checks():
        if check.path is None:
            errors.append(f"'{check.name}' is not a built-in check and has no 'check' path")
            continue
        try:
            check.resolve()
        except ImportError:
            errors.append(f"check '{check.name}' cannot be imported from '{check.path}'")
    return errors
