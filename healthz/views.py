"""Liveness, readiness and diagnostics endpoints (SPEC §3)."""

import hmac
from datetime import datetime, timezone

from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from healthz import conf, registry
from healthz.protocol import CheckResult, aggregate
from healthz.runner import run_checks

DATASTORE_CHECKS = {"database", "cache", "redis"}


@require_safe
@never_cache
def healthz(request) -> HttpResponse:
    return HttpResponse("OK", content_type="text/plain")


@require_safe
@never_cache
def livez(request) -> HttpResponse:
    return HttpResponse("OK", content_type="text/plain")


@require_safe
@never_cache
def readyz(request) -> HttpResponse:
    return _plain_readiness_response(_readiness_results())


@require_safe
@never_cache
def health(request) -> HttpResponse:
    expose = conf.get("EXPOSE")
    authorized = _is_authorized(request, expose)
    # Unknown EXPOSE values fail closed (like readyz), never open.
    if expose != "public" and not authorized:
        return _plain_readiness_response(_readiness_results())
    results = run_checks(registry.build_checks(), cache_key="health")
    status = aggregate(results)
    payload = _build_payload(status, results, detailed=authorized and expose != "public")
    return JsonResponse(payload, status=503 if status == "fail" else 200,
                        content_type="application/health+json")


def _readiness_results():
    checks = [check for check in registry.build_checks()
              if check.readiness and check.critical]
    return run_checks(checks, cache_key="readyz")


def _plain_readiness_response(results) -> HttpResponse:
    if aggregate(results) == "fail":
        return HttpResponse("NOT READY", status=503, content_type="text/plain")
    return HttpResponse("OK", content_type="text/plain")


def _is_authorized(request, expose: str) -> bool:
    if expose == "token":
        token = conf.get("TOKEN")
        header = request.headers.get("Authorization", "")
        if not token or not header.startswith("Bearer "):
            return False
        provided = header.removeprefix("Bearer ").encode("latin-1", "surrogateescape")
        return hmac.compare_digest(provided, token.encode("utf-8"))
    if expose == "staff":
        user = getattr(request, "user", None)
        return bool(user is not None and user.is_authenticated and user.is_staff)
    return False


def _build_payload(status: str, results, detailed: bool) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {"status": status, "version": "1"}
    if conf.get("SERVICE_ID"):
        payload["serviceId"] = conf.get("SERVICE_ID")
    if conf.get("RELEASE_ID"):
        payload["releaseId"] = conf.get("RELEASE_ID")
    if conf.get("ENVIRONMENT"):
        payload["notes"] = [f"environment: {conf.get('ENVIRONMENT')}"]
    payload["checks"] = {
        result.name: [_check_entry(result, now, detailed)] for result in results
    }
    return payload


def _check_entry(result: CheckResult, now: str, detailed: bool) -> dict:
    entry = {
        "componentType": "datastore" if result.name in DATASTORE_CHECKS else "component",
        "status": result.health_status,
        "observedValue": round(result.response_time_ms, 2),
        "observedUnit": "ms",
        "time": now,
    }
    output = _output_for(result, detailed)
    if output:
        entry["output"] = output
    return entry


def _output_for(result: CheckResult, detailed: bool) -> str | None:
    if result.status == "skipped":
        return "skipped"
    if result.status != "error":
        return None
    if detailed:
        parts = [part for part in (result.error_class, result.detail) if part]
        return ": ".join(parts) or "check failed"
    return "check failed"
