"""End-to-end: /health/ with all nine built-in checks registered at once."""

import json
import time

import pytest
from django.core.cache import cache

ALL_BUILTINS = {
    "database": {},
    "cache": {},
    "redis": {},
    "broker": {},
    "celery_workers": {},
    "filesystem": {},
    "storage": {"critical": False, "readiness": False},
    "migrations": {},
    "staticfiles": {},
}


@pytest.mark.django_db
class TestAllBuiltinsHealthEndpoint:
    @pytest.fixture(autouse=True)
    def full_config(self, settings, tmp_path, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        settings.REDIS_URL = None
        settings.CELERY_BROKER_URL = None
        settings.MEDIA_ROOT = str(tmp_path)
        settings.HEALTHZ = {"CHECKS": ALL_BUILTINS}
        cache.set(
            "healthz:celery_workers",
            {"status": "ok", "workers": 2, "time": time.time()},
            30,
        )
        yield
        cache.delete("healthz:celery_workers")

    def test_health_json_with_all_nine_builtins(self, client):
        response = client.get("/health/")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/health+json"
        payload = json.loads(response.content)
        assert payload["status"] == "pass"
        assert set(payload["checks"]) == set(ALL_BUILTINS)
        for name, entries in payload["checks"].items():
            entry = entries[0]
            assert entry["status"] == "pass", f"{name}: {entry}"
            assert entry["observedUnit"] == "ms"
            assert isinstance(entry["observedValue"], (int, float))
            assert entry["componentType"] in ("datastore", "component")
            assert entry["time"]
        for skipped in ("redis", "broker"):
            assert payload["checks"][skipped][0]["output"] == "skipped"

    def test_readyz_excludes_storage_and_reports_ok(self, client):
        response = client.get("/readyz")

        assert response.status_code == 200
        assert response.content == b"OK"
