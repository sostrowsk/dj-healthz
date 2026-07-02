from django.apps import AppConfig


class HealthzConfig(AppConfig):
    name = "healthz"
    verbose_name = "Health Checks"

    def ready(self):
        from . import system_checks  # noqa: F401
