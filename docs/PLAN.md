# dj-healthz — Implementation Plan

Basis: [SPEC.md](SPEC.md). Jeder Task = ein TDD-Zyklus (Test zuerst, RED
bestätigen, minimal implementieren, GREEN, Refactor) = ein atomarer Commit.
Tasks sind sequenziell, außer als **[independent]** markiert.

## Repository-Layout (Ziel)

```
dj-healthz/
├── pyproject.toml            # Poetry, packages = [{include = "healthz"}]
├── LICENSE                   # MIT
├── README.md
├── CLAUDE.md                 # Paket-Regeln (analog dj-progress)
├── docs/{SPEC,PLAN,SURVEY}.md
├── pytest.ini                # DJANGO_SETTINGS_MODULE=healthz.tests.settings
└── healthz/
    ├── __init__.py
    ├── apps.py               # AppConfig + system checks registrieren
    ├── conf.py               # HEALTHZ settings + Defaults + Resolver
    ├── protocol.py           # Check-Dict-Contract, Status-Mapping, CheckResult
    ├── registry.py           # Check-Auflösung (builtin name | dotted path)
    ├── runner.py             # ThreadPool-Engine, Timeouts, Budget, Result-Cache
    ├── views.py              # healthz/livez/readyz/health views
    ├── urls.py
    ├── checks/
    │   ├── __init__.py       # BUILTINS-Mapping
    │   ├── database.py  cache.py  redis.py  broker.py
    │   ├── celery_workers.py  filesystem.py  storage.py
    │   ├── migrations.py  staticfiles.py
    ├── tasks.py              # probe_workers (nur importierbar mit Celery)
    ├── system_checks.py      # healthz.E001ff / W001ff
    ├── deploy/
    │   └── docker-healthcheck.sh
    └── tests/
        ├── __init__.py  settings.py  urls.py
        └── test_*.py
```

## Phase 0 — Gerüst

### T0 Paket-Skelett + Test-Infrastruktur
- `pyproject.toml` (poetry, python `>=3.11,<3.14`, django `>=5,<7`,
  dev-deps: pytest, pytest-django, flake8, isort), `pytest.ini`,
  `healthz/tests/settings.py` (sqlite in-memory, locmem cache, ROOT_URLCONF
  auf `healthz.tests.urls` mit `include("healthz.urls")`).
- **Test (RED zuerst):** `tests/test_imports.py` — `import healthz`,
  App-Config lädt, `healthz.urls` importierbar.
- Commit: `chore: package skeleton with test infrastructure`

## Phase 1 — Kern (sequenziell)

### T1 Protocol & Status-Mapping
- **Tests:** dict-Contract → `CheckResult`; Mapping ok→pass, error→fail,
  skipped→pass(+annotation); non-critical error→warn; Aggregation
  (fail > warn > pass); ungültiger status-Wert → error mit `error_class`.
- Implementierung: `protocol.py` (dataclass `CheckResult`, `aggregate()`).

### T2 Conf & Registry
- **Tests:** Zero-Config ⇒ database+cache auto-enabled; builtin-Name löst auf;
  dotted path löst auf; unbekannter Name/kaputter Pfad ⇒ Fehlerliste für
  system checks; Optionen (`critical`, `timeout`, `readiness`) mit Defaults.
- Implementierung: `conf.py`, `registry.py`.

### T3 Runner (Timeout-Engine)
- **Tests:** Ergebnisse aller Checks; hängender Check (sleep > timeout) ⇒
  `error`/`Timeout` innerhalb Budget, übrige Checks liefern trotzdem;
  per-check timeout override; Exception im Check ⇒ error + `error_class`,
  Exception-Text NICHT im Result-`output` (nur geloggt); Parallel-Ausführung
  (Gesamtdauer ≈ langsamster Check, nicht Summe); Result-Cache
  (`CACHE_SECONDS`) liefert gecachtes Ergebnis.
- Implementierung: `runner.py`.

### T4 Views + URLs
- **Tests:** wie SPEC §8.1–4 — `/healthz`+`/livez` 200 `OK`,
  `assertNumQueries(0)`, 200 selbst wenn alle Checks error; `/readyz`
  200/503 `OK`/`NOT READY` ohne Details; `/health/`
  `application/health+json`, Schema, Statuscode-Mapping, `no-store`;
  POST ⇒ 405; kein Redirect (APPEND_SLASH-Falle) auf `healthz|livez|readyz`;
  Views funktionieren unter i18n-Host-URLconf ohne Locale-Prefix.
- Implementierung: `views.py`, `urls.py`.

### T5 Exposure-Gating
- **Tests:** `EXPOSE="token"`: ohne/mit falschem Token ⇒ plain OK/NOT READY
  ohne checks-Detail, mit Token ⇒ voller Body inkl. error `output`;
  `EXPOSE="staff"` analog via `request.user`; anonym nie Exception-Text
  (Fake-DSN-Regressionstest).
- Implementierung: Gating in `views.py`/`conf.py`.

### T6 System Checks
- **Tests:** kaputte CHECKS-Config ⇒ `healthz.E001`; explizit konfigurierter
  Check mit fehlender Dependency ⇒ `healthz.E002`;
  `SECURE_SSL_REDIRECT=True` ohne Exempt für healthz-Pfade ⇒ `healthz.W001`;
  `EXPOSE="token"` ohne `TOKEN` ⇒ `healthz.E003`.
- Implementierung: `system_checks.py`, Registrierung in `apps.py`.

## Phase 2 — Built-in Checks [independent untereinander, brauchen Phase 1]

Jeder Check: eigener Task, Tests für ok/error/skipped/no-leak, dann Impl.

- **T7 database** — `SELECT 1` je Alias, Timing; Fehlerpfad via gemocktem
  `connections`.
- **T8 cache** — Round-trip (set/get/compare/delete, uuid-Key); Fehlerpfad
  gemockter Cache; Timing.
- **T9 redis** — lazy import; ohne `redis`-Paket/URL ⇒ skipped (auto) bzw.
  E002 (explizit); Round-trip gegen `fakeredis`-ähnlichen Mock;
  eigener Probe-Client mit `socket_timeout`, keine Shared-Client-Mutation.
- **T10 broker** — kombu `ensure_connection(max_retries=1, timeout=…)`,
  gemockt; ohne kombu/`CELery_BROKER_URL` ⇒ skipped.
- **T11 celery_workers** — liest Cache-Key; fehlender/alter Key (`max_age`)
  ⇒ **error** (nicht Absence); plus `tasks.probe_workers` (gemocktes
  `app.control.ping`) schreibt Key.
- **T12 filesystem** — tempfile write/read/delete; Fehlerpfad (unwritable dir).
- **T13 storage** — `default_storage` save/exists/delete, Empfehlung
  non-critical/readiness:False in Doku; Fehlerpfad gemockt.
- **T14 migrations** — `MigrationExecutor`-Plan leer ⇒ ok, ausstehende
  Migration (Test-App mit Migration ohne Apply) ⇒ error.
- **T15 staticfiles** — Manifest/finders-Probe; fehlendes Manifest ⇒ error;
  ohne staticfiles-App ⇒ skipped.

## Phase 3 — Deployment-Artefakte & Doku

### T16 docker-healthcheck.sh
- **Tests:** bash-Syntaxcheck (`bash -n`) + Verhaltenstest via Env-Stubs
  (CONTAINER_ROLE=web/worker/beat wählt korrekten Zweig; unbekannte Rolle ⇒
  exit 1). Script wird ins Wheel gepackt (include-Test).

### T17 README.md
- Install (poetry git dep), Quickstart, Settings-Referenz, alle Checks,
  Exposure, Beat-Schedule-Snippet, Dockerfile/compose/k8s-Snippets,
  `ALLOWED_HOSTS`/`SECURE_REDIRECT_EXEMPT`-Helper, robots.txt-Hinweis,
  Migrationspfad je Bestandsprojekt (leasing/tinakylau/…: alte URLs → include).
- Kein Test nötig (Doku), aber Code-Snippets müssen mit Test-Settings
  smoke-getestet sein (doctest-artiger Test für das HEALTHZ-Beispiel).

## Phase 4 — Fleet-Verifikation (Workflow, parallel)

### T18 Kompatibilitäts-Matrix
Für jedes Zielprojekt (leasing, tinakylau, expertdaq, acceed, lexsource,
jeanmarcel, arznei-muster-mello, AI-Bilanz-Scanner, second-brain-v2):
ein Agent konstruiert die projekt-äquivalente `HEALTHZ`-Config
(aus SURVEY.md) und führt die dj-healthz-Suite mit passenden Settings
(Cache-Backend, Broker-URL vorhanden/fehlt, Django 5.2 vs 6.0) aus —
**ohne die Projekte zu verändern** (Integration in die Hosts ist ein
separates Folgeprojekt pro Repo).
- Zusätzlich: Suite läuft unter Django 5.2 **und** 6.0 (tox-los: zwei
  venvs oder Poetry-Override im Workflow).
- Findings ⇒ Fix-Tasks (je eigener TDD-Zyklus).

### T19 Abschluss-Gate
- `flake8` + `isort .` + `pytest` grün, `codex review --uncommitted` P1-frei,
  Coverage der SPEC-§8-Liste manuell abgehakt.

## Commit-/Push-Plan

- Repo: `git init` auf `main`, Commits pro Task (Phase 2 ggf. gebündelt pro
  Check), am Ende `glab repo create addvendo/dj-healthz` + push.

## Risiken

- **Timeout via Threads** killt keinen hängenden Thread (nur das Warten wird
  begrenzt) — akzeptiert; Doku-Hinweis; Budget schützt die Response-Zeit.
- **Django 6 Deprecations** — Matrix-Lauf in T18 fängt das ab.
- **celery_workers ohne Beat** — Check meldet dann dauerhaft error; Doku:
  nur aktivieren, wenn der Beat-Task eingerichtet ist (System-Check-Warnung
  W002, wenn Check aktiv aber Celery fehlt).
