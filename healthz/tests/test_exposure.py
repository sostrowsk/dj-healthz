import json

from django.test import RequestFactory, override_settings

from healthz.views import health

FAKE_DSN = "postgres://user:s3cretpass@db.internal/prod"


def ok_check(**options):
    return {"status": "ok", "response_time_ms": 1.0}


def error_check(**options):
    return {"status": "error", "response_time_ms": 1.0, "error_class": "ProbeError"}


def dsn_raising_check(**options):
    raise ConnectionError(f"could not connect to {FAKE_DSN}")


SPY_CALLS = {"count": 0}


def spy_diagnostic_check(**options):
    SPY_CALLS["count"] += 1
    return {"status": "ok", "response_time_ms": 1.0}


CHECKS = {
    "alpha": {"check": "healthz.tests.test_exposure.ok_check"},
    "boom": {"check": "healthz.tests.test_exposure.error_check"},
}
SPY_CHECKS = {
    "alpha": {"check": "healthz.tests.test_exposure.ok_check"},
    "deep": {"check": "healthz.tests.test_exposure.spy_diagnostic_check", "readiness": False},
}
DSN_CHECKS = {"leaky": {"check": "healthz.tests.test_exposure.dsn_raising_check"}}

TOKEN_MODE = {"EXPOSE": "token", "TOKEN": "s3cret-token", "CHECKS": CHECKS}
STAFF_MODE = {"EXPOSE": "staff", "CHECKS": CHECKS}


def bearer(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class TestTokenMode:
    @override_settings(HEALTHZ=TOKEN_MODE)
    def test_anonymous_gets_plain_body_with_correct_status(self, client):
        response = client.get("/health/")
        assert response.status_code == 503
        assert response.content == b"NOT READY"
        assert response["Content-Type"].startswith("text/plain")

    @override_settings(HEALTHZ={**TOKEN_MODE, "CHECKS": {"alpha": CHECKS["alpha"]}})
    def test_anonymous_passing_gets_plain_ok(self, client):
        response = client.get("/health/")
        assert response.status_code == 200
        assert response.content == b"OK"

    @override_settings(HEALTHZ=TOKEN_MODE)
    def test_wrong_token_gets_plain_body(self, client):
        response = client.get("/health/", **bearer("wrong-token"))
        assert response.status_code == 503
        assert response.content == b"NOT READY"

    @override_settings(HEALTHZ=TOKEN_MODE)
    def test_valid_token_gets_detailed_json(self, client):
        response = client.get("/health/", **bearer("s3cret-token"))
        assert response.status_code == 503
        assert response["Content-Type"] == "application/health+json"
        body = json.loads(response.content)
        assert body["checks"]["boom"][0]["output"] == "ProbeError"

    @override_settings(HEALTHZ={**TOKEN_MODE, "TOKEN": None})
    def test_unset_token_never_authorizes(self, client):
        response = client.get("/health/", **bearer(""))
        assert response["Content-Type"].startswith("text/plain")

    @override_settings(HEALTHZ=TOKEN_MODE)
    def test_non_ascii_header_gets_plain_body_not_500(self, client):
        response = client.get("/health/", **bearer("\xa7\xa7"))
        assert response.status_code == 503
        assert response.content == b"NOT READY"
        assert response["Content-Type"].startswith("text/plain")


class TestUnknownExposeFailsClosed:
    @override_settings(HEALTHZ={**TOKEN_MODE, "EXPOSE": "tokn"})
    def test_misspelled_expose_never_serves_anonymous_diagnostics(self, client):
        response = client.get("/health/")
        assert response["Content-Type"].startswith("text/plain")
        assert response.content in (b"OK", b"NOT READY")


class TestUnauthorizedRunsOnlyReadinessChecks:
    @override_settings(HEALTHZ={**TOKEN_MODE, "CHECKS": SPY_CHECKS})
    def test_unauthorized_never_runs_readiness_false_checks(self, client):
        SPY_CALLS["count"] = 0
        response = client.get("/health/")
        assert response.status_code == 200
        assert response.content == b"OK"
        assert SPY_CALLS["count"] == 0

    @override_settings(HEALTHZ={**TOKEN_MODE, "CHECKS": SPY_CHECKS})
    def test_authorized_runs_readiness_false_checks(self, client):
        SPY_CALLS["count"] = 0
        response = client.get("/health/", **bearer("s3cret-token"))
        assert response["Content-Type"] == "application/health+json"
        assert SPY_CALLS["count"] == 1


class StubUser:
    """Duck-typed user so staff mode works without session/auth middleware."""

    is_authenticated = True

    def __init__(self, is_staff: bool):
        self.is_staff = is_staff


def staff_mode_request(user=None):
    request = RequestFactory().get("/health/")
    if user is not None:
        request.user = user
    return request


class TestStaffMode:
    @override_settings(HEALTHZ=STAFF_MODE)
    def test_anonymous_gets_plain_body(self, client):
        response = client.get("/health/")
        assert response.status_code == 503
        assert response.content == b"NOT READY"

    @override_settings(HEALTHZ=STAFF_MODE)
    def test_request_without_user_gets_plain_body(self):
        response = health(staff_mode_request())
        assert response.status_code == 503
        assert response.content == b"NOT READY"

    @override_settings(HEALTHZ=STAFF_MODE)
    def test_non_staff_user_gets_plain_body(self):
        response = health(staff_mode_request(StubUser(is_staff=False)))
        assert response.content == b"NOT READY"

    @override_settings(HEALTHZ=STAFF_MODE)
    def test_staff_user_gets_detailed_json(self):
        response = health(staff_mode_request(StubUser(is_staff=True)))
        assert response["Content-Type"] == "application/health+json"
        body = json.loads(response.content)
        assert body["checks"]["boom"][0]["output"] == "ProbeError"


class TestPublicMode:
    @override_settings(HEALTHZ={"CHECKS": CHECKS})
    def test_public_error_output_is_generic(self, client):
        body = json.loads(client.get("/health/").content)
        assert body["checks"]["boom"][0]["output"] == "check failed"
        assert b"ProbeError" not in client.get("/health/").content


class TestNoLeakRegression:
    @override_settings(HEALTHZ={"CHECKS": DSN_CHECKS})
    def test_dsn_never_in_public_response(self, client):
        response = client.get("/health/")
        assert b"s3cretpass" not in response.content
        assert b"db.internal" not in response.content
        assert json.loads(response.content)["checks"]["leaky"][0]["output"] == "check failed"

    @override_settings(HEALTHZ={"EXPOSE": "token", "TOKEN": "t0k", "CHECKS": DSN_CHECKS})
    def test_dsn_never_in_authorized_response_either(self, client):
        response = client.get("/health/", **bearer("t0k"))
        assert b"s3cretpass" not in response.content
        body = json.loads(response.content)
        assert body["checks"]["leaky"][0]["output"] == "ConnectionError"

    @override_settings(HEALTHZ={"EXPOSE": "token", "TOKEN": "t0k", "CHECKS": DSN_CHECKS})
    def test_dsn_never_in_anonymous_token_mode_response(self, client):
        response = client.get("/health/")
        assert b"s3cretpass" not in response.content
        assert response.content == b"NOT READY"
