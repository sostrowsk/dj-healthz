# dj-healthz

Reusable Django app providing **liveness / readiness / diagnostics** health
endpoints with timeout-bounded, pluggable checks. One package for all
addvendo projects — replaces the hand-rolled `health_checks.py` copies
(see [docs/SURVEY.md](docs/SURVEY.md), design in [docs/SPEC.md](docs/SPEC.md)).

- `/healthz` + `/livez` — liveness: process up, **no dependency checks**, always 200
- `/readyz` — readiness: critical checks, `OK` (200) / `NOT READY` (**503**), no internals in the body
- `/health/` — deep diagnostics: [`application/health+json`](https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06) with per-check status and latency

Every check runs concurrently with a **per-check timeout** and an **overall
budget** — a hung database can no longer stall the probe past the
orchestrator's timeout.

Requires Python ≥ 3.11 and Django ≥ 5.0 (tested on 5.2 and 6.0).
The only hard dependency is Django; redis, kombu/celery etc. are optional.

## Install

```bash
# public GitHub mirror (no ssh key needed, e.g. in Docker builds)
poetry add git+https://github.com/sostrowsk/dj-healthz.git#main

# or via GitLab (addvendo-intern)
poetry add git+ssh://git@gitlab.com/addvendo/dj-healthz.git#main
```

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "healthz",
]
```

```python
# urls.py — OUTSIDE i18n_patterns, no prefix
urlpatterns = [
    path("", include("healthz.urls")),
    # ... i18n_patterns(...) etc.
]
```

That's it — with zero configuration you get liveness endpoints plus
`database` and `cache` checks on `/readyz` and `/health/`.

## Configuration

```python
HEALTHZ = {
    "SERVICE_ID": "leasing",                    # optional, shown in /health/
    "RELEASE_ID": os.environ.get("APP_VERSION"),
    "ENVIRONMENT": os.environ.get("ENVIRONMENT"),  # goes into notes
    "EXPOSE": "public",                         # public | token | staff
    "TOKEN": os.environ.get("HEALTHZ_TOKEN"),   # required for EXPOSE="token"
    "CACHE_SECONDS": 0,                         # cache aggregated results
    "TIMEOUT": 5.0,                             # per-check default (seconds)
    "BUDGET": 10.0,                             # overall wall-clock budget
    "CHECKS": {
        "database":       {},
        "cache":          {"critical": False},
        "broker":         {"timeout": 3},
        "celery_workers": {"critical": False},
        "migrations":     {},
        "staticfiles":    {},
        "storage":        {"critical": False, "readiness": False},
        "milvus":         {"check": "scribe.scribe_milvus.check_milvus_health_static",
                           "critical": False},
    },
}
```

Per-check options:

| Option | Default | Meaning |
|---|---|---|
| `critical` | `True` | Failure flips `/readyz` to 503 and `/health/` to `fail`; non-critical failures only produce `warn` (HTTP 200) |
| `readiness` | `True` | `False` excludes the check from `/readyz` (diagnostics-only, e.g. S3 storage) |
| `timeout` | `HEALTHZ["TIMEOUT"]` | Per-check timeout in seconds |
| `check` | – | Dotted path to a custom check callable |

Misconfiguration (unknown check name, unimportable dotted path, `token`
mode without a token, missing optional dependency or missing URL setting for
an explicitly configured check, invalid `EXPOSE` value) fails loudly at
startup via Django system checks (`healthz.E001`–`E004`, `W001`) — never as
a silently `skipped` check. Unknown `EXPOSE` values additionally fail
closed at request time.

## Built-in checks

| Name | What it verifies |
|---|---|
| `database` | `SELECT 1` per configured alias, with timing |
| `cache` | set/get/compare/delete round-trip (unique key, 10 s TTL) |
| `redis` | raw Redis round-trip via dedicated short-timeout probe client (`redis_url` option or `REDIS_URL`) — for Redis beyond the cache (locks, channels) |
| `broker` | `kombu.Connection(...).ensure_connection(max_retries=1)` against `CELERY_BROKER_URL` — works for Redis **and** RabbitMQ |
| `celery_workers` | reads the heartbeat written by the shipped beat task; a missing or stale entry is an **error**, not silence |
| `filesystem` | tempfile write/read/delete |
| `storage` | `default_storage` save/exists/delete (recommend `critical: False, readiness: False` for S3 — costs a PUT per probe) |
| `migrations` | fails when unapplied migrations exist |
| `staticfiles` | manifest present / staticfiles configured — catches "deployed without collectstatic" |

### Custom checks

Any callable returning the dict contract works (same shape dj-rag-db and
dj-base-project already speak):

```python
def check(**options) -> dict:
    return {"status": "ok",          # ok | error | skipped
            "response_time_ms": 12.3}
```

Register it via `"my-thing": {"check": "myapp.checks.check"}`. Never put raw
exception text into the dict — log it and set `error_class` instead.

## Celery worker heartbeat

The `celery_workers` check needs the shipped beat task:

```python
CELERY_BEAT_SCHEDULE = {
    "healthz-probe-workers": {
        "task": "healthz.tasks.probe_workers",
        "schedule": 60.0,
        "options": {"expires": 59},  # never let probes pile up
    },
}
```

## Exposure & security

- `healthz` / `livez` / `readyz` are public and leak nothing.
- `/health/` with `EXPOSE="public"` returns per-check status and latency but
  **generic error messages only** — exception text goes to the `healthz`
  logger, never into an anonymous response.
- `EXPOSE="token"`: send `Authorization: Bearer <HEALTHZ_TOKEN>` to get error
  details; anonymous callers get the plain `OK`/`NOT READY` behaviour.
- `EXPOSE="staff"`: same, gated on `request.user.is_staff`.
- Add `Disallow: /health` to `robots.txt`.

## Deployment wiring

Required settings for in-container probes:

```python
# Host header of in-container curl probes
ALLOWED_HOSTS = [..., "localhost", "127.0.0.1"]

# Health endpoints must not 301 to https for the in-container probe
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^livez$", r"^readyz$", r"^health/$"]
```

(`healthz.W001` warns at startup when `SECURE_SSL_REDIRECT=True` without the
exemption — `curl -f` treats the 301 as success and your probe silently
degrades to a port check.)

### Docker

The wheel ships a role-aware healthcheck script:

```dockerfile
COPY --from=app /app/.venv/lib/python3.13/site-packages/healthz/deploy/docker-healthcheck.sh /usr/local/bin/docker-healthcheck
RUN chmod +x /usr/local/bin/docker-healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["docker-healthcheck"]
```

`CONTAINER_ROLE` selects the probe: `web` (default) → `curl -fsS
http://localhost:$PORT/readyz`, `worker` → `celery inspect ping` (needs
`CELERY_APP`), `beat` → pidfile freshness (`BEAT_PIDFILE`).

### docker-compose

```yaml
services:
  web:
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/readyz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
  worker:
    environment: { CONTAINER_ROLE: worker, CELERY_APP: myproject }
    healthcheck:
      test: ["CMD", "docker-healthcheck"]
      interval: 60s
      timeout: 15s
```

### Kubernetes

```yaml
livenessProbe:
  httpGet: { path: /livez, port: 8000 }
  periodSeconds: 10
  failureThreshold: 6        # generous — restarts are expensive
readinessProbe:
  httpGet: { path: /readyz, port: 8000 }
  periodSeconds: 10
  failureThreshold: 3
startupProbe:
  httpGet: { path: /readyz, port: 8000 }
  periodSeconds: 5
  failureThreshold: 60       # up to 5 min to boot
```

## Response format (`/health/`)

```json
{
  "status": "pass",
  "version": "1",
  "releaseId": "1.4.2",
  "serviceId": "leasing",
  "notes": ["environment: staging"],
  "checks": {
    "database": [{"componentType": "datastore", "status": "pass",
                   "observedValue": 3.2, "observedUnit": "ms",
                   "time": "2026-07-02T05:21:00Z"}]
  }
}
```

`fail` → HTTP 503 (only critical checks can cause it), `warn`/`pass` → 200.
All endpoints send `Cache-Control: no-store` and accept only GET/HEAD.

## Known limitations

- The per-check timeout bounds how long the *response* waits, not the worker
  thread itself — a truly hung check thread lingers until its client times out.
  Give probe clients their own socket timeouts where possible.
- With `CACHE_SECONDS > 0` the result-cache get/set itself is not bounded by
  `BUDGET`. Cache *errors* fall back to live execution, but a stalled cache
  backend without socket timeouts can delay probes — only enable the result
  cache on backends with short socket timeouts (locmem, Redis with
  `SOCKET_TIMEOUT`).

## Migrating an existing project

1. Remove the project's `health_checks.py` / inline health view and its URL
   entries (keep the paths: dj-healthz serves `/healthz` and `/health/` too).
2. `poetry add git+ssh://git@gitlab.com/addvendo/dj-healthz.git#main`,
   add `"healthz"` to `INSTALLED_APPS`, include `healthz.urls` outside
   `i18n_patterns`.
3. Translate the old checks into `HEALTHZ["CHECKS"]` (see table above;
   Milvus/pgvector via a custom `check` dotted path to dj-rag-db).
4. Keep external monitors on `/healthz` (liveness) and container
   healthchecks on `/readyz`.
5. Run the project's tests — dj-healthz's own suite can be run from the host
   (requires `pytest-django` as a dev dependency of the host):

   ```bash
   DJANGO_SETTINGS_MODULE=healthz.tests.settings pytest --pyargs healthz.tests
   ```

   The env var is required: the host's pytest config wins otherwise, and the
   suite must run against dj-healthz's bundled settings.

## Development

```bash
uv venv .venv && uv pip install -e . --group dev  # or poetry install
.venv/bin/pytest -q
.venv/bin/flake8 healthz --max-line-length=99
.venv/bin/isort --profile black -l 99 healthz
```

From a host project (pytest-django installed), run the packaged suite with:

```bash
DJANGO_SETTINGS_MODULE=healthz.tests.settings pytest --pyargs healthz.tests
```

TDD is mandatory — see `CLAUDE.md` and [docs/PLAN.md](docs/PLAN.md).
