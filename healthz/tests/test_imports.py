import importlib

from django.apps import apps


def test_package_imports():
    importlib.import_module("healthz")
    importlib.import_module("healthz.urls")


def test_app_config_loaded():
    config = apps.get_app_config("healthz")
    assert config.name == "healthz"
