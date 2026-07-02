# dj-healthz — Host Migration Plan

Migration der Bestandsprojekte auf `dj-healthz` (Basis: [SURVEY.md](SURVEY.md),
Verhalten: [SPEC.md](SPEC.md), Nutzung: [../README.md](../README.md)).

Wave 1 (dieser Plan): **tinakylau, leasing, jeanmarcel, acceed, lexsource,
arznei-muster-mello**. Später: expertdaq, AI-Bilanz-Scanner, second-brain-v2.

## Grundrezept (jedes Projekt)

1. **Branch** `feat/dj-healthz` vom aktuellen HEAD. Keine fremden dirty
   Files anfassen; nur Migrations-Dateien stagen. **Kein Push.**
2. **Dependency**: `dj-healthz = {git = "git@gitlab.com:addvendo/dj-healthz.git", branch = "main"}`
   in pyproject.toml (poetry lock + install).
3. **Settings**: `"healthz"` in `INSTALLED_APPS`; `HEALTHZ`-Dict nach
   Projektprofil (unten); `ALLOWED_HOSTS` um `localhost`/`127.0.0.1`
   ergänzen (falls fehlt); bei `SECURE_SSL_REDIRECT=True` die
   `SECURE_REDIRECT_EXEMPT`-Patterns aus dem README.
4. **URLs**: `path("", include("healthz.urls"))` **außerhalb**
   `i18n_patterns`. Alte Health-URLs entfernen. Extern konsumierte
   Alt-Pfade, die dj-healthz nicht serviert (z. B. `/health/simple`),
   als Alias auf `healthz.views.healthz` erhalten — niemals einen von
   Monitoren/Dockern konsumierten Pfad stillegen.
5. **Alt-Code entfernen — konservativ**: nur die Health-*Endpoint*-
   Implementierung (health_checks.py / Views) löschen. Hintergrund-Tasks,
   Monitoring-Dashboards und Metrik-Infrastruktur, die andernorts
   konsumiert werden, bleiben (leasing `/monitoring/redis/`, tinakylau
   RabbitMQ-Metriken).
6. **Tests (TDD)**: bestehende Health-Tests auf das neue Verhalten
   portieren (Pfad, Statuscodes 200/503, plain vs. health+json) — erst
   RED gegen den unmigrierten Stand prüfen, dann migrieren, dann GREEN.
   Mindest-Smoke pro Projekt: `/healthz` 200 plain, `/readyz` 200,
   `/health/` `application/health+json`, POST 405, kein Locale-Redirect.
7. **Gate**: Projekt-Lint/Tests (flake8 + isort + pytest bzw.
   Projektstandard) + `codex review --uncommitted`; P1 fixen.
8. **Ein atomarer Commit** auf dem Branch (Migration + Tests).

## Projektprofile

### leasing (Django 5.2) — fable5
- Entfernen: `leasing/health_checks.py`, URL-Einträge `/health/`,
  `/health/simple`, `/healthz`. **Behalten**: `/monitoring/redis/`-Dashboard
  und `leasing/tasks/redis_health.py` (Monitoring-Consumer!).
- Alias: `path("health/simple", healthz_liveness)` (externe Monitore).
- `HEALTHZ`: SERVICE_ID leasing, RELEASE_ID/ENVIRONMENT aus env; CHECKS:
  database, cache, redis (REDIS_URL), broker, celery_workers
  {critical: False} + Beat-Schedule `healthz.tasks.probe_workers`
  (expires 59), filesystem, storage {critical: False, readiness: False},
  milvus als Custom-Check auf den vorhandenen scribe-Helper
  {critical: False} — nur wenn der Helper das dict-Contract liefert.

### tinakylau (Django 6.0) — fable5
- Entfernen: `tinakylau/health_checks.py`, alte `/healthz`- und
  `/health/`-Views. **Behalten**: `tasks/rabbitmq_health.py`
  (Deep-Metrics) und das Docker-Healthcheck-Script (Pfad `/healthz`
  bleibt identisch → Script unverändert lauffähig; verifizieren).
- `HEALTHZ`: database, cache, broker (amqp), celery_workers
  {critical: False} + Beat-Schedule, filesystem, staticfiles,
  storage {critical: False, readiness: False}. E-Mail-Probe: bestehenden
  Beat-Task behalten und als Custom-Check (Cache-Read, dict-Contract)
  anbinden, falls trivial — sonst dokumentieren und weglassen.

### acceed (Django 6) — opus4.8
- Entfernen: `health_check` in `acceed/views.py` + URLs `/healthz`,
  `/health/`. **Behalten**: `/api/core/health/redis-locks/`
  (eigenes Feature) und `tasks/redis_health.py`.
- `HEALTHZ`: database, cache, redis {critical: False}, broker
  {critical: False}. EXPOSE public (wie bisher kompaktes JSON, aber
  jetzt leak-frei).

### lexsource (Django 6.0.5) — opus4.8
- `lexsource/health.py` ersetzen; Pfade `/healthz` + `/readyz` bleiben
  identisch (gleiche Semantik by design). `SECURE_REDIRECT_EXEMPT`
  abgleichen.
- `HEALTHZ`: database, staticfiles, migrations.
- Bestehende Tests in `lexsource/tests.py` (No-Leak, 503, SSL-Exempt)
  weitgehend unverändert übernehmen — sie sind die Referenz-Suite.

### jeanmarcel (Django 6.0.5) — opus4.8
- Entfernen: `health_check` in `jeanmarcel/views.py` + URLs `/health/`,
  `/healthz`.
- `HEALTHZ`: database, cache. i18n-Host: Mount außerhalb
  `i18n_patterns` (Regressionstest).

### arznei-muster-mello (Django 6.0) — sonnet5
- Entfernen: Inline-`health_check` in `arznei_muster_mello/urls.py`.
- Zero-Config (database+cache defaults). `/health/` liefert jetzt
  health+json statt `{"status": "ok"}` — Ansible-HEALTHCHECK und
  `monitor.sh` nutzen `curl -f` → 200 bleibt 200, kompatibel
  (verifizieren, sonst auf `/readyz` umstellen und das im Commit
  dokumentieren). robots.txt-Disallow bleibt.

## Verifikation (pro Projekt, sonnet5)

- `manage.py check` ohne healthz-Errors; `manage.py makemigrations
  --check --dry-run` clean (dj-healthz hat keine Models).
- Projekt-Testsuite grün; Health-Smoke-Tests grün.
- `git diff main..feat/dj-healthz --stat` enthält nur Migrations-Dateien.
- Alte extern konsumierte Pfade antworten weiterhin 200.

## Rollout nach Merge (manuell, später)

- Branch mergen, deployen; externe Monitore auf `/healthz` (Liveness)
  bzw. Container-Healthchecks auf `/readyz` umstellen (Docker/Ansible
  HEALTHCHECK-Snippets im README).
