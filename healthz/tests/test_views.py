import json
import time

import pytest
from django.test import override_settings


def ok_check(**options):
    return {"status": "ok", "response_time_ms": 1.2}


def error_check(**options):
    return {"status": "error", "response_time_ms": 1.2, "error_class": "ProbeError"}


def skipped_check(**options):
    return {"status": "skipped", "response_time_ms": 0.0}


def hung_check(**options):
    time.sleep(2)
    return {"status": "ok", "response_time_ms": 2000.0}


NON_CRITICAL_SPY = {"count": 0}


def non_critical_spy_check(**options):
    NON_CRITICAL_SPY["count"] += 1
    return {"status": "ok", "response_time_ms": 0.1}


def _checks(**names_to_options):
    prefix = "healthz.tests.test_views"
    return {
        name: {"check": f"{prefix}.{func}", **opts}
        for name, (func, opts) in names_to_options.items()
    }


ALL_OK = {"CHECKS": _checks(alpha=("ok_check", {}), beta=("ok_check", {}))}
CRITICAL_FAIL = {"CHECKS": _checks(alpha=("ok_check", {}), boom=("error_check", {}))}
NON_CRITICAL_FAIL = {"CHECKS": _checks(alpha=("ok_check", {}),
                                       boom=("error_check", {"critical": False}))}
ALL_ERROR = {"CHECKS": _checks(boom=("error_check", {}), bang=("error_check", {}))}


class TestLiveness:
    @override_settings(HEALTHZ=ALL_ERROR)
    @pytest.mark.django_db
    @pytest.mark.parametrize("path", ["/healthz", "/livez"])
    def test_200_ok_zero_queries_even_when_all_checks_error(
        self, client, django_assert_num_queries, path,
    ):
        with django_assert_num_queries(0):
            response = client.get(path)
        assert response.status_code == 200
        assert response.content == b"OK"
        assert response["Content-Type"].startswith("text/plain")

    @override_settings(HEALTHZ=ALL_OK)
    @pytest.mark.parametrize("path", ["/healthz", "/livez", "/readyz"])
    def test_no_trailing_slash_redirect(self, client, path):
        response = client.get(path)
        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["/healthz", "/livez", "/readyz", "/health/"])
    def test_post_is_405(self, client, path):
        assert client.post(path).status_code == 405

    @pytest.mark.parametrize("path", ["/healthz", "/livez", "/readyz", "/health/"])
    def test_no_store_cache_control(self, client, path):
        response = client.get(path)
        assert "no-store" in response["Cache-Control"]


class TestReadyz:
    @override_settings(HEALTHZ=ALL_OK)
    def test_ok(self, client):
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.content == b"OK"

    @override_settings(HEALTHZ=CRITICAL_FAIL)
    def test_critical_failure_is_503_not_ready(self, client):
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.content == b"NOT READY"

    @override_settings(HEALTHZ=NON_CRITICAL_FAIL)
    def test_non_critical_failure_stays_200(self, client):
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.content == b"OK"

    @override_settings(HEALTHZ={"CHECKS": _checks(
        alpha=("ok_check", {}),
        diagnostics_only=("error_check", {"readiness": False}),
    )})
    def test_readiness_false_checks_excluded(self, client):
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.content == b"OK"

    @override_settings(HEALTHZ={"CHECKS": _checks(
        alpha=("ok_check", {}),
        informational=("non_critical_spy_check", {"critical": False}),
    )})
    def test_non_critical_checks_do_not_run_on_readyz(self, client):
        NON_CRITICAL_SPY["count"] = 0
        response = client.get("/readyz")
        assert response.status_code == 200
        assert NON_CRITICAL_SPY["count"] == 0

    @override_settings(HEALTHZ={"BUDGET": 0.5, "CHECKS": _checks(
        hung=("hung_check", {"timeout": 0.2}),
        fast=("ok_check", {"critical": False}),
    )})
    def test_hung_check_flips_readiness_within_budget(self, client):
        start = time.monotonic()
        response = client.get("/readyz")
        assert time.monotonic() - start < 1.5
        assert response.status_code == 503


class TestHealthJson:
    @override_settings(HEALTHZ=ALL_OK)
    def test_pass_payload(self, client):
        response = client.get("/health/")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/health+json"
        body = json.loads(response.content)
        assert body["status"] == "pass"
        assert body["version"] == "1"
        entry = body["checks"]["alpha"][0]
        assert entry["status"] == "pass"
        assert entry["observedValue"] == 1.2
        assert entry["observedUnit"] == "ms"
        assert entry["componentType"] == "component"
        assert "time" in entry

    @override_settings(HEALTHZ=CRITICAL_FAIL)
    def test_critical_failure_is_fail_503(self, client):
        response = client.get("/health/")
        assert response.status_code == 503
        body = json.loads(response.content)
        assert body["status"] == "fail"
        assert body["checks"]["boom"][0]["status"] == "fail"

    @override_settings(HEALTHZ=NON_CRITICAL_FAIL)
    def test_non_critical_failure_is_warn_200(self, client):
        response = client.get("/health/")
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["status"] == "warn"
        assert body["checks"]["boom"][0]["status"] == "warn"

    @override_settings(HEALTHZ={"CHECKS": _checks(maybe=("skipped_check", {}))})
    def test_skipped_check_is_pass_and_annotated(self, client):
        body = json.loads(client.get("/health/").content)
        assert body["status"] == "pass"
        entry = body["checks"]["maybe"][0]
        assert entry["status"] == "pass"
        assert entry["output"] == "skipped"

    @override_settings(HEALTHZ={
        "SERVICE_ID": "leasing", "RELEASE_ID": "1.2.3", "ENVIRONMENT": "staging",
        **ALL_OK,
    })
    def test_metadata_from_config(self, client):
        body = json.loads(client.get("/health/").content)
        assert body["serviceId"] == "leasing"
        assert body["releaseId"] == "1.2.3"
        assert body["notes"] == ["environment: staging"]

    @override_settings(HEALTHZ=ALL_OK)
    def test_metadata_absent_when_unconfigured(self, client):
        body = json.loads(client.get("/health/").content)
        assert "serviceId" not in body
        assert "releaseId" not in body
        assert "notes" not in body

    @override_settings(HEALTHZ={
        "CHECKS": {"database": {"check": "healthz.tests.test_views.ok_check"}},
    })
    def test_database_component_type_is_datastore(self, client):
        body = json.loads(client.get("/health/").content)
        assert body["checks"]["database"][0]["componentType"] == "datastore"


class TestI18nHost:
    @override_settings(ROOT_URLCONF="healthz.tests.i18n_urls", USE_I18N=True, HEALTHZ=ALL_OK)
    def test_probes_resolve_without_locale_prefix_or_redirect(self, client):
        for path in ("/healthz", "/livez", "/readyz", "/health/"):
            response = client.get(path, follow=False)
            assert response.status_code == 200, path
