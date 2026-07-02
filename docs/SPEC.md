# dj-healthz — Specification

Reusable Django app `healthz` that provides state-of-the-art (2026) health-check
endpoints for every addvendo Django project, replacing the hand-rolled
implementations surveyed in [SURVEY.md](SURVEY.md).

## 1. Goals

- One package, zero copy-paste: `pip/poetry add` + `INSTALLED_APPS` + one `include()`.
- Correct **liveness / readiness / diagnostics** separation (the single biggest
  defect across the fleet: DB-touching `/healthz` endpoints get containers
  restarted for dependency outages).
- Every check **timeout-bounded** (no project today has a single timeout).
- **Safe by default**: no internals leaked on public endpoints, deep diagnostics gated.
- All integrations **optional**: works with or without Redis, Celery, kombu,
  Milvus/pgvector, S3 — missing pieces report `skipped`, misconfigured pieces
  fail loudly at startup via Django system checks.

### Non-Goals

- No dashboard/UI (leasing-health-monitoring keeps its own).
- No metrics/alerting pipeline (Prometheus exposition can come later; the JSON
  is machine-readable enough for uptime monitors today).
- No background-probing scheduler of its own — it *consumes* cached results
  that host Celery beat tasks produce (helper task provided).

## 2. Standards Baseline (2026)

- **Kubernetes probe semantics** ([Liveness/Readiness/Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)):
  - *Liveness* answers "is this process stuck?" — must never check external
    dependencies; failure means restart.
  - *Readiness* answers "can this instance take traffic?" — checks critical
    dependencies; failure means drain, therefore **503**, never 500.
  - *Startup* answers "finished initializing?" — covered by the readiness
    endpoint with a startup-probe config pointing at it.
- **Health Check Response Format for HTTP APIs**
  ([draft-inadarei-api-health-check-06](https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06)):
  media type `application/health+json`, root `status` of `pass|warn|fail`,
  per-component `checks` map with `componentType`, `observedValue`,
  `observedUnit`, `status`, `time`, `output`. 2xx for pass, 4xx/5xx for fail.
- **Probe endpoints are boring and cheap**: plain-text bodies for probes,
  JSON only on the diagnostics endpoint; `Cache-Control: no-store` everywhere;
  `GET`/`HEAD` only.

## 3. Endpoints

Mounted via `path("", include("healthz.urls"))` **outside** `i18n_patterns`
(regression-tested — locale 302s break `curl -f` probes).

| Path | Purpose | Checks | Response | Status codes |
|---|---|---|---|---|
| `/healthz` | Liveness (k8s legacy name, fleet convention) | none — process/routing only | `text/plain` `OK` | always 200 |
| `/livez` | Liveness alias (k8s current name) | none | `text/plain` `OK` | always 200 |
| `/readyz` | Readiness / startup probe | all checks with `critical: true` | `text/plain` `OK` / `NOT READY` — **no diagnostics in body** | 200 / **503** |
| `/health/` | Deep diagnostics | all registered checks | `application/health+json` (draft-inadarei) | 200 / 503 |

Rules for all four views:

- `@require_safe` (GET/HEAD only) + `@never_cache` + `Cache-Control: no-store`.
- No trailing-slash redirects for `healthz/livez/readyz` (`curl -f` treats 3xx
  as success — investorselect's broken probe is the cautionary tale).
- Exempt from SSL redirect via documented `SECURE_REDIRECT_EXEMPT` helper and
  from strict `ALLOWED_HOSTS` via documented settings snippet (both covered in
  README; a system check warns when `SECURE_SSL_REDIRECT=True` without the
  exemption).

### `/health/` response body (draft-inadarei)

```json
{
  "status": "pass",
  "version": "1",
  "releaseId": "<settings.HEALTHZ['RELEASE_ID'] or unset>",
  "serviceId": "<settings.HEALTHZ['SERVICE_ID'] or unset>",
  "notes": ["environment: staging"],
  "checks": {
    "database": [{"componentType": "datastore", "status": "pass",
                   "observedValue": 3.2, "observedUnit": "ms",
                   "time": "2026-07-02T05:21:00Z"}],
    "celery:workers": [{"componentType": "component", "status": "warn",
                         "output": "check failed", "time": "..."}]
  }
}
```

- Overall `status`: `fail` if any **critical** check fails (→ HTTP 503),
  `warn` if only non-critical checks fail (→ HTTP 200), else `pass` (200).
- `output` on failure is a **generic message by default** ("check failed",
  error *class* name at most). Full exception text goes to the
  `healthz` logger (`logger.exception`), never into an unauthenticated
  response body. Regression test: a fake DSN in an exception message must not
  appear in the response.

### Exposure

- `healthz`, `livez`, `readyz`: public (they leak nothing).
- `/health/`: public but generic by default. With `HEALTHZ["EXPOSE"]`:
  - `"public"` (default) — health+json with generic outputs.
  - `"token"` — requires `Authorization: Bearer <HEALTHZ['TOKEN']>` (or
    `?token=`… disabled by default); otherwise the view behaves like `readyz`
    (plain OK/NOT READY, no body detail).
  - `"staff"` — request.user.is_staff required for detail, plain otherwise.
  - Any other value fails closed (plain readyz behaviour) and is rejected at
    startup via system check `healthz.E004`.
- Detailed error output (`output` = exception text) only when the request is
  authorized (token/staff) — never for anonymous callers.

## 4. Check Protocol

A check is a callable (dotted path) returning the **dj-rag-db dict contract**,
which the fleet's libraries already speak:

```python
def check(**options) -> dict:
    return {
        "status": "ok" | "error" | "skipped",   # skipped = dependency not configured
        "response_time_ms": 12.3,                # measured with time.monotonic()
        # optional extras: "detail", "error_class", ...
    }
```

Mapping to health+json: `ok→pass`, `skipped→pass` (annotated), `error→fail`
(or `warn` when the check is non-critical).

### Execution engine

- Checks run through a `ThreadPoolExecutor` with a **per-check timeout**
  (default 5 s, per-check override) and an **overall budget**
  (default 10 s). A timed-out check reports `error` with
  `error_class: "Timeout"`; remaining checks still report.
- Concurrent execution keeps `/health/` latency ≈ slowest check, not the sum
  (the fleet runs ASGI/Daphne — a slow sequential health view ties up workers).
- Optional short **result cache** (`CACHE_SECONDS`, default 0 = off) via
  Django cache with `locmem` fallback, keyed per endpoint — bounds the DoS /
  cost amplification of unauthenticated probes (S3 PUT per probe etc.).
- Each check gets a fresh, short-timeout probe client where applicable —
  never mutate shared clients/retry strategies at request time (leasing's
  `retry_strategy` mutation bug).

### Configuration

```python
HEALTHZ = {
    "SERVICE_ID": "leasing",            # optional
    "RELEASE_ID": env("APP_VERSION"),   # optional
    "ENVIRONMENT": env("ENVIRONMENT"),  # optional, goes into notes
    "EXPOSE": "public",                 # public | token | staff
    "TOKEN": env("HEALTHZ_TOKEN", None),
    "CACHE_SECONDS": 0,
    "TIMEOUT": 5.0,                     # per-check default
    "BUDGET": 10.0,                     # overall wall-clock budget
    "CHECKS": {
        "database":   {},                                        # built-in by name
        "cache":      {"critical": False},
        "broker":     {"critical": True, "timeout": 3},
        "storage":    {"critical": False, "readiness": False},   # diagnostics-only
        "milvus":     {"check": "scribe.scribe_milvus.check_milvus_health_static",
                        "critical": False},
        "my-custom":  {"check": "myapp.checks.whatever", "critical": True},
    },
}
```

- `critical` (default `True`): failing check flips `readyz` to 503 and
  `/health/` to `fail`; non-critical failures only produce `warn`.
- `readiness` (default `True`): set `False` to exclude a check from `/readyz`
  (expensive diagnostics like storage/S3 belong only in `/health/`).
- `timeout`: per-check override.
- Unknown built-in name or non-importable dotted path → **Django system check
  error at startup** (`healthz.E001`…), not a silent `skipped` (expertdaq's
  permanently-dead Milvus check is the cautionary tale).

## 5. Built-in Checks

All lazy-import their dependency; a missing *package* or absent *setting*
yields `skipped` **only** when the check was auto-enabled — an explicitly
configured check whose dependency is missing is a system-check error.

| Name | What it does | Notes |
|---|---|---|
| `database` | `SELECT 1` on every entry in `settings.DATABASES` (or `aliases` option) | timing per alias |
| `cache` | set/get/compare/delete round-trip, `uuid4` key + host+pid suffix, TTL 10 s | backend-agnostic (Redis, memcached, locmem) |
| `redis` | raw Redis round-trip against `redis_url` option or `REDIS_URL` setting/env | for Redis-beyond-cache users (locks, channels); distinct probe client, `socket_timeout` = check timeout |
| `broker` | `kombu.Connection(...).ensure_connection(max_retries=1, timeout=…)` against `CELERY_BROKER_URL` | broker-agnostic (Redis & RabbitMQ) — tinakylau's pattern |
| `celery_workers` | reads a cached heartbeat written by the shipped beat task; missing/stale key = **error, not silent absence** | avoids blocking `inspect ping` in request path; `max_age` option (default 120 s) |
| `filesystem` | tempfile write/read/delete in `MEDIA_ROOT`-adjacent tmp | |
| `storage` | `default_storage` save/exists/delete of a tiny probe file | non-critical + `readiness: False` recommended (S3 cost) |
| `migrations` | `MigrationExecutor` plan check — pending migrations = error | readiness-only gap no project covers today |
| `staticfiles` | manifest loadable / `static()` resolves a probe asset | catches "deployed without collectstatic" (lexsource) |

**Shipped Celery helpers** (imported only if Celery installed):

- `healthz.tasks.probe_workers` — beat task pinging workers via
  `app.control.ping(timeout=…)`, writing `{"status", "workers", "time"}` to
  cache with `expires` just under its interval (fleet convention: 59 s/299 s).
- Documented beat schedule snippet.

**Shipped deployment artifacts** (in `healthz/deploy/`, installed with the wheel):

- `docker-healthcheck.sh` — role-aware (`CONTAINER_ROLE=web|worker|beat`):
  web → `curl -fsS http://localhost:$PORT/readyz`, worker → celery inspect
  ping, beat → pidfile freshness (tinakylau's pattern, generalized).
- Reference `HEALTHCHECK` Dockerfile lines, compose snippet, k8s probe YAML
  (in README).

## 6. Security Requirements

1. Generic bodies by default; exception text only to logs and authorized callers.
2. Regression test: DSN/password strings never in anonymous responses.
3. `robots.txt` guidance (`Disallow: /health`) in README.
4. No new attack surface: no state-changing methods, no template rendering on
   probe endpoints, deep endpoint optionally token/staff-gated.
5. System check warns when `EXPOSE="public"` and `DEBUG=False` and detailed
   output would include component latencies only (allowed) — internals like
   hostname/OS/versions are **never** emitted (drop leasing's `system_info`).

## 7. Compatibility Matrix

- **Python** ≥ 3.11 (fleet: 3.11–3.13; CI target 3.13).
- **Django** ≥ 5.0, < 7 (fleet: 5.2.x and 6.0.x).
- Hard dependency: **Django only**. Everything else (redis, kombu/celery,
  pymilvus via dj-rag-db, boto3 via storages) optional/lazy.
- Packaging: Poetry (`packages = [{include = "healthz"}]`), consumed as git
  dependency pinned to `main` — same model as dj-progress/dj-rag-db.
- **No models, no migrations** — byte-stable `makemigrations --check` in hosts.
- No imports from host apps; configuration only via `settings.HEALTHZ` with
  stable defaults (works with **zero configuration**: database+cache checks
  auto-enabled, everything else opt-in).

## 8. Testing Requirements (TDD)

Suite runs standalone (`pytest` in repo, bundled minimal settings) **and**
from hosts via
`DJANGO_SETTINGS_MODULE=healthz.tests.settings pytest --pyargs healthz.tests`
(pytest-django must be installed in the host; the env var is mandatory
because the host's pytest config wins otherwise). Mandatory coverage:

1. Routing: paths resolve outside i18n, no trailing-slash redirect on probe
   endpoints, `require_safe` (POST → 405).
2. Liveness never touches the DB (assert zero queries) and returns 200 even
   when every check errors.
3. Readiness: 503 + `NOT READY` when a critical check fails; 200 when only
   non-critical fail; `readiness: False` checks excluded.
4. `/health/`: health+json media type & schema, status aggregation
   (pass/warn/fail), HTTP mapping, `no-store` header.
5. Timeout engine: hung check → `Timeout` error within budget; other checks
   still reported.
6. Each built-in check: ok path, error path, skipped path (dependency absent),
   and the no-leak guarantee.
7. Config validation: unknown check name / bad dotted path → system check error.
8. Exposure modes: token/staff gating incl. wrong-token behavior.
9. Cached-worker-probe staleness: missing cache key reports error.
10. `celery_workers`/`broker` tests use fakes — no live broker in CI.
