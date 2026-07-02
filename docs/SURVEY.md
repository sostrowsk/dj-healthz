# dj-healthz — Synthesis of Health-Check Implementations Across Projects

## 1. Comparison Table

| Project | Framework | Endpoint path(s) | Checks | Response format | Auth | Deployment consumer |
|---|---|---|---|---|---|---|
| **leasing** | Django 5.2.10 (Poetry), hand-rolled | `/health/`, `/health/simple`, `/healthz`, `/monitoring/redis/` (staff) | DB, Redis (deep round-trip), cache, filesystem, Milvus*, media storage* (+ celery-beat Redis probing) | Deep JSON (components, timings, system_info, version) 200/500; plain `OK`/`ERROR` for simple | Public (staff-only for dashboard) | External Docker HEALTHCHECK (`curl -f`, off-repo); uptime monitors |
| **leasing-health-monitoring** | Django 5 (fork of leasing) | Same as leasing + `/monitoring/redis/metrics` API | Same as leasing; + celery-cached metrics API (30s cache, 504 on timeout) | Same as leasing; metrics JSON | Public; dashboard login+staff | External (off-repo); regression tests pin non-i18n routing |
| **tinakylau** | Django 6.0, hand-rolled | `/healthz`, `/health/` | DB, broker (kombu, agnostic), cache, filesystem, Milvus*, media storage*, email* (bg), celery workers* (bg), RabbitMQ deep metrics (bg-only) | Plain `OK`/`ERROR`; deep JSON 200/500 | Public | **In-repo Docker HEALTHCHECK** with role-aware script (web/worker/beat) |
| **expertdaq** | Django 5.2, hand-rolled | `/health/` only (`simple_health_check` is dead code, unrouted) | DB, Redis, cache (memcached), filesystem, Milvus (permanently dead — missing import), media storage*; bg Redis probing | Deep JSON 200/500 | Public | None visible in repo (no HEALTHCHECK, no compose) |
| **acceed** | Django 6, hand-rolled | `/healthz` + `/health/` (same view), `/api/core/health/redis-locks/` | DB, Redis cache round-trip; separate lock-health endpoint; bg Redis probing (not surfaced) | Compact JSON (services + ms) 200/**503**; lock endpoint 200/207/503 | Public | External (curl installed "for healthcheck", no HEALTHCHECK instruction) |
| **lexsource** | Django 6.0.5, hand-rolled (~65 lines) | `/healthz` (liveness), `/readyz` (readiness) | Liveness: none by design; readiness: DB + staticfiles manifest | Plain text `OK` 200 / `NOT READY` **503**; no diagnostics leaked | Public; SSL-redirect-exempt | None in repo (aspirational, well-tested) |
| **jeanmarcel** | Django 6.0.5, hand-rolled | `/health/`, `/healthz` (alias) | DB, Redis cache round-trip (uuid key) | JSON (services + ms, total_ms) 200/**503** | Public | External (curl in image, no HEALTHCHECK) |
| **arznei-muster-mello** | Django 6.0, 3-line inline view | `/health/` | None — static `{"status": "ok"}`, always 200 | Static JSON 200 | Public (robots-disallowed) | **In-repo**: Ansible Docker HEALTHCHECK + cron watchdog (`monitor.sh` auto-restart) + pytest |
| **AI-Bilanz-Scanner** | Django 5.2.10, **django-health-check 3.20.8** | `/health/` (package MainView) | DB (write/read/delete), cache, Redis (misconfigured — pings localhost fallback), Celery task round-trip | HTML table or JSON (`?format=json`) 200/500 | Public | **In-repo Dockerfile HEALTHCHECK** (urllib) + compose pg_isready/redis-cli gates |
| **second-brain-v2** | Django 6, DRF, uv | **None** | Container/provisioning-level only; "lint_health_check" is content quality, not infra | n/a | n/a | compose pg_isready; Ansible one-shot Milvus/Unstructured gates |
| **dj-base-project** (library) | Django 5 package | **None** | Redis client resilience primitives (pybreaker, retry, `get_metrics()`), DB reconnect middleware — no endpoint | n/a | n/a | None — host projects must wire their own |
| **dj-rag-db** (library) | Django 5 package | **None** — ships callables | `MilvusBackend.health_check()` dict (ok/error/skipped + ms), `is_ready()` bool, pgvector `is_ready()` | Dict building block for host endpoints | n/a | Host project's responsibility |
| investorselect (FastAPI, reference) | FastAPI | `/api/v1/health/`, `/ready`, `/live` | DB only (in `/ready`); `/ready` always returns 200 even when not ready | JSON | Public | compose curl — hits the no-op endpoint via a 307 redirect (broken) |
| E-Rechnung (FastAPI, reference) | FastAPI, stateless | `/api/v1/health` | None (defensible — no dependencies) | Static `{"status":"ok"}` | Public | Tests + README curl only |

\* = non-critical / informational component (does not flip the HTTP status).

## 2. Union of Checks dj-healthz Must Support

| Check | Needed by | Notes |
|---|---|---|
| **Database (`SELECT 1`)** | leasing, leasing-hm, tinakylau, expertdaq, acceed, lexsource, jeanmarcel, AI-Bilanz-Scanner — effectively all | The universal critical check; must gain a timeout (no project has one) |
| **Cache round-trip (set/get/compare/delete)** | leasing, leasing-hm, tinakylau, expertdaq, acceed, jeanmarcel, AI-Bilanz-Scanner | Backend-agnostic via Django cache framework (Redis, memcached both in use); unique host+pid/uuid keys, ~10s TTL |
| **Raw Redis round-trip** (distinct from cache) | leasing, leasing-hm, expertdaq | Only needed where Redis is used beyond the cache (broker, channels, locks) |
| **Broker connectivity (kombu, broker-agnostic)** | tinakylau (explicit), implicitly expertdaq/acceed/jeanmarcel/leasing (all run Celery with unchecked brokers) | tinakylau's kombu `ensure_connection(max_retries=1, timeout=5)` is the right primitive — works for Redis and RabbitMQ |
| **Celery worker liveness** | tinakylau (bg ping), AI-Bilanz-Scanner (task round-trip); flagged as a *missing* check in leasing, expertdaq, acceed, jeanmarcel, second-brain-v2 | Highest-value gap across the fleet — dead workers everywhere leave health green |
| **Celery beat liveness** | tinakylau (pidfile check in healthcheck script), arznei (pgrep) | Container-role concern; needs a beat heartbeat pattern |
| **Filesystem (tempfile write/read)** | leasing, leasing-hm, tinakylau, expertdaq | |
| **Media storage (default_storage save/exists/delete)** | leasing, leasing-hm, tinakylau, expertdaq | Non-critical; must be skippable, timeout-bounded, and cost-aware (S3 PUT per probe) |
| **Milvus / vector DB** | leasing, leasing-hm, tinakylau, expertdaq (broken), acceed (unwired), second-brain-v2 (unwired) | Should consume dj-rag-db's `health_check()` dict contract (ok/error/skipped + ms); must respect the active backend (pgvector vs Milvus) |
| **Staticfiles manifest** | lexsource | Cheap, catches "deployed without collectstatic"; readiness-only |
| **Email backend (OAuth token probe)** | tinakylau | Background-probed with cached result — the model for any external SaaS check |
| **Pending migrations** | **No project has it**; flagged as missing in leasing, tinakylau, expertdaq, jeanmarcel, lexsource surveys | Readiness-only check dj-healthz should add |
| **Pure liveness (no dependencies)** | lexsource (`/healthz`), arznei, E-Rechnung | Must exist as a zero-dependency endpoint |
| **Version/environment stamping** | leasing, leasing-hm, tinakylau, expertdaq (APP_VERSION/ENVIRONMENT); missing and missed in jeanmarcel | For deploy verification |

## 3. Best Patterns Worth Keeping

1. **Liveness/readiness split with correct status semantics** (lexsource): `/healthz` checks nothing (a DB outage must not restart containers); `/readyz` returns **503** so the LB drains instead of restarting. acceed/jeanmarcel's 503-over-500 choice agrees. This is the single most important design decision.
2. **Non-i18n URL registration with regression tests** (leasing, acceed, jeanmarcel, tinakylau): health URLs outside `i18n_patterns` because `curl -f` treats the locale 302 as failure-masking. dj-healthz's `urls.py` must mount prefix-free, and ship tests pinning it.
3. **Critical vs. non-critical component split** (leasing, tinakylau): only core components gate the status code; optional ones (Milvus, storage, email) are informational or `skipped`. Make the critical set configurable.
4. **Two-tier design** (leasing, tinakylau): cheap plain-text probe endpoint + deep JSON diagnostics endpoint.
5. **Background probing with cached results** (tinakylau): slow/external checks (OAuth email, celery ping, deep broker metrics) run in celery beat, write to cache, and the view only reads — keeps the endpoint fast and stops probing SaaS per request. Fix: a missing cache key must count as *stale/error*, not silently disappear.
6. **Role-aware container healthcheck script** (tinakylau `docker-healthcheck.sh`): one script, `CONTAINER_ROLE` selects curl (web) / `celery inspect ping` (worker) / pidfile (beat). Ship this with dj-healthz.
7. **Write-path probes, not pings** (all hand-rolled projects): set/get/compare/delete with uuid or host+pid keys and 10s TTLs; storage save/exists/delete. Detects silent write failures and self-cleans.
8. **Per-check + overall `response_time_ms`** via `time.monotonic()` (leasing, acceed, jeanmarcel).
9. **No-leak error posture with regression test** (lexsource): `logger.exception` for details, generic body; test asserts the DSN string never appears in the response.
10. **`SECURE_REDIRECT_EXEMPT` for health paths** (lexsource) — otherwise `SSL_REDIRECT` 301s the in-container probe and `curl -f` treats 3xx as success. Also pair with the **ALLOWED_HOSTS localhost extension** (leasing, acceed, jeanmarcel, arznei) so in-container probes don't 400.
11. **Health-path retry clamping** (leasing): bound the check's latency (max_retries=1, short delay) instead of inheriting production backoff — but do it on a *copy/parameter*, never by mutating a shared client.
12. **Library building-block contract** (dj-rag-db): checks as plain callables returning `{status: ok|error|skipped, response_time_ms, ...}`; the host owns routing/auth. dj-healthz's plugin interface should adopt this dict shape.
13. **`@never_cache` + `@require_safe`** on every health view (universal).
14. **Kubernetes-convention aliases** (`/healthz`, `/readyz`, no trailing slash) alongside `/health/`.
15. **Content negotiation** (AI-Bilanz-Scanner via django-health-check): HTML for humans, JSON for machines from the same endpoint — nice-to-have.
16. **Beat task `expires` just under interval** (leasing/expertdaq/acceed: 59s/299s) to prevent queue pile-up during outages.
17. **Reserved-path hygiene** (arznei): `robots.txt Disallow`, reserved alias so catch-all routes can't shadow the health path.

## 4. Common Weaknesses dj-healthz Must Fix

1. **No timeouts anywhere** (every project): no per-check or overall budget; a hung DB/S3/Milvus stalls the endpoint past the orchestrator's probe timeout. dj-healthz needs a per-check timeout and a total request budget (and ideally concurrent check execution).
2. **Public deep endpoints leaking internals** (leasing, tinakylau, expertdaq, acceed locks): hostname, OS, Python/Django versions, storage backend class, raw `str(e)` (can contain DSNs), Redis metrics. Fix: diagnostics gated by token/IP/staff or opt-in; generic bodies by default (lexsource model); details to logs.
3. **No caching/rate limiting → DoS and cost amplification**: every unauthenticated GET does live DB+Redis+S3-PUT+Milvus round-trips. Fix: short result caching (a few seconds), background probing for expensive checks.
4. **Missing liveness/readiness distinction** (all except lexsource/investorselect): DB-touching `/healthz` gets containers *restarted* for dependency outages. dj-healthz must ship `/livez` (no deps), `/readyz` (503 semantics), `/health/` (deep).
5. **Celery worker/beat/queue never checked over HTTP** (leasing, expertdaq, acceed, jeanmarcel, second-brain-v2): dead workers = green health. Also: AI-Bilanz-Scanner's celery check only exercises the default queue, not the named ones.
6. **No pending-migrations check in any project.**
7. **Probe wiring drift**: Dockerfiles install curl "for healthcheck" but contain no `HEALTHCHECK`; the actual consumer lives off-repo and can silently break (leasing, expertdaq, acceed, jeanmarcel). Counter-examples of *broken* in-repo wiring: investorselect's trailing-slash 307 that `curl -f` counts as success; AI-Bilanz-Scanner's HEALTHCHECK inherited by worker/beat containers (always unhealthy) and defeated by `SECURE_SSL_REDIRECT`. dj-healthz should ship reference HEALTHCHECK/compose/k8s snippets + the role-aware script + config tests.
8. **Shared-client mutation at request time** (leasing/expertdaq `check_redis` mutating `retry_strategy`; acceed's `connection_params` side-channel): fragile; health checks also pollute per-process circuit-breaker state for real traffic. Use dedicated, short-timeout probe clients.
9. **In-memory per-process metrics** (leasing/expertdaq/acceed beat tasks — all self-acknowledged in comments): fragment across prefork workers, lost on restart, sometimes never exposed at all (expertdaq, acceed) or fetched via blocking `.delay().get()` in a request. Store probe results in cache/DB.
10. **Dead/misconfigured checks that report healthy**: expertdaq's Milvus check imports a nonexistent module (permanently `skipped`); AI-Bilanz-Scanner's Redis check pings a fallback `redis://localhost/1`; dj-rag-db's static helper reports Milvus while pgvector is active; `skipped` states can mask typos (e.g. `MILVUS_HOST` misspelled). Fix: fail loudly on misconfiguration (Django system checks at startup), distinguish "intentionally disabled" from "unconfigured".
11. **Silent-disappearance of cached components** (tinakylau): expired cache entry for a dead worker fleet just drops the component from the payload. Absence must be reported as stale/unknown.
12. **Bugs in check logic**: leasing's beat task treats `None` get() as success; check error paths reporting `response_time_ms: 0`; broad `except Exception` hiding error class from the JSON entirely (jeanmarcel).
13. **Host-header gap** (lexsource, AI-Bilanz-Scanner): SSL-redirect handled but `Host: localhost` 400s when `ALLOWED_HOSTS` is strict. dj-healthz docs/settings helper must cover both exemptions together.
14. **Wrong criticality assignments**: cache failure 503-ing a liveness consumer (acceed, jeanmarcel); expertdaq's in-container memcached as a "critical" near-tautological check. Criticality must be per-check configurable.

## 5. Constraints on dj-healthz Design

- **Django versions in active use: 5.0 → 6.0** (5.2.x: leasing, expertdaq, AI-Bilanz-Scanner; 6.0.x: tinakylau, acceed, lexsource, jeanmarcel, arznei, second-brain-v2; libraries pin `^5`). dj-healthz must support **Django >= 5.0 including 6.x**.
- **Python: 3.11 → 3.13** (acceed pyproject targets 3.11+, 3.13-slim in Docker; most others pin ^3.13; investorselect image is 3.11). Target **>= 3.11**, test on 3.13.
- **Packaging: Poetry dominates**; second-brain-v2 uses uv. Ship as a standard wheel installable by both (dj-base-project/dj-rag-db set the precedent: Poetry-built reusable Django app packages consumed as git dependencies).
- **All dependencies must be optional**: fleet variance covers Redis and memcached caches, Redis and RabbitMQ brokers, Celery present/absent, Milvus/pgvector/none, S3/local storage, Channels/Daphne ASGI everywhere. Checks need lazy imports and graceful `skipped` (kombu for broker, no hard redis/pymilvus/boto3 deps) — the leasing "optional import → skipped" and dj-rag-db lazy-client patterns are the model.
- **ASGI/Daphne is the standard runtime** — synchronous sequential checks tie up workers; design checks to be budget-bounded (and preferably parallelizable).
- **Must interoperate with the existing library ecosystem**: dj-base-project (RedisClient with pybreaker/retry/`get_metrics()`, DB reconnect middleware) and dj-rag-db (`health_check()` dict contract with `ok|error|skipped` + `response_time_ms`). Adopting that dict shape as the plugin protocol gives free integration.
- **i18n is pervasive** (i18n_patterns in leasing, tinakylau, acceed, jeanmarcel) — URLs must mount outside locale prefixing, with shipped regression tests.
- **Deployment targets are plain Docker + Ansible + nginx and external orchestrators, not k8s (yet)** — but `/healthz`/`/readyz` naming and 503 readiness semantics should be k8s-compatible from day one. Reference artifacts to ship: Dockerfile `HEALTHCHECK`, role-aware healthcheck script (web/worker/beat), compose snippet, settings helpers for `ALLOWED_HOSTS` + `SECURE_REDIRECT_EXEMPT`.
- **django-health-check (3.20.x) is a known quantity** (AI-Bilanz-Scanner) — its plugin-via-INSTALLED_APPS and content-negotiation patterns are worth borrowing, but its weaknesses there (no liveness/readiness split, no result caching, fragile settings coupling like the `REDIS_URL` fallback) are part of what dj-healthz replaces.
- **TDD is mandatory per the developer's global rules** — every check, URL-routing guarantee (non-i18n, no-leak, SSL-exemption), and config artifact needs tests; lexsource's test suite is the template.