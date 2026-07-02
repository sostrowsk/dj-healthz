"""Minimal settings so the suite runs standalone and via --pyargs from hosts."""

SECRET_KEY = "healthz-test-secret-key"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "healthz",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

ROOT_URLCONF = "healthz.tests.urls"
USE_TZ = True
STATIC_URL = "/static/"

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

SESSION_ENGINE = "django.contrib.sessions.backends.cache"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
