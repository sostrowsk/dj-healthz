# dj-healthz — Host-Migration

Migration der Bestandsprojekte auf `dj-healthz` (Basis: [SURVEY.md](SURVEY.md),
Verhalten: [SPEC.md](SPEC.md), Nutzung: [../README.md](../README.md)).

## Status (2026-07-02: Wave 1 + 2 abgeschlossen)

Alle 7 Projekte migriert, MRs gegen **staging** gemerged, Pipelines grün,
Feature-Branches (lokal + remote) aufgeräumt:

| Projekt | MR | Merge | Checks (HEALTHZ) |
|---|---|---|---|
| leasing | !129 | `48d6136` | database, cache, redis, broker, celery_workers*, filesystem, storage†, milvus* (scribe) |
| tinakylau | !24 | `6f42eb0` | database, cache, broker (amqp), celery_workers*, filesystem, staticfiles, storage† |
| acceed | !180 | FF `fba68b8` | database, cache, redis*, broker* |
| jeanmarcel | !83 | `5eb79c3` | database, cache |
| arznei-muster-mello | !6 | `7e268a7` | Zero-Config (database, cache) |
| lexsource | !2 | FF `f6016bd` | database, staticfiles, migrations |
| expertdaq | !178 | `1f5bc94` | database, cache, redis, broker*, filesystem, storage† — **ohne celery_workers** (s. u.) |

\* non-critical · † non-critical + `readiness: False` · FF = Fast-Forward-Merge

**Noch nicht migriert (Wave 3, optional):** AI-Bilanz-Scanner, second-brain-v2.

## Offene Rollout-Schritte (nach Deploy)

1. **Externe Uptime-Monitore auf `/readyz` umstellen.** Die alten
   Liveness-Pfade (`/healthz`, leasing `/health/simple`) machten `SELECT 1`
   und lieferten bei DB-Ausfall 500 — die neuen Liveness-Endpoints sind per
   Design **immer 200**. Das DB-Ausfall-Signal liegt jetzt auf `/readyz`.
   Container-HEALTHCHECKs ebenfalls auf `/readyz` (insb. tinakylaus
   `docker-healthcheck.sh`, web-Zweig).
2. **`APP_VERSION` / `ENVIRONMENT`** env-Vars in Deploy setzen, damit
   `releaseId`/`notes` in `/health/` gefüllt sind.
3. **expertdaq:** (a) robots.txt `Disallow: /health` committen (lag nur im
   Working Tree); (b) beim debian13→staging-Merge braucht dessen
   Playwright-`test_e2e.py` die 200/503-Anpassung (fertig im
   debian13-basierten Commit `5c334335`); (c) `celery_workers`-Check
   reaktivieren, sobald der Heartbeat einen web/worker-geteilten Store hat —
   der Django-Default-Cache ist dort per-Container-memcached, der Check wäre
   permanent `StaleProbe` (Begründung als Kommentar in settings.py; Paket-
   Backlog: Cache-Alias-Option für `celery_workers`/`probe_workers`).

## Grundrezept (für Wave 3 / neue Projekte)

1. **Branch** `feat/dj-healthz` vom aktuellen HEAD. Keine fremden dirty
   Files stagen. Kein Push vor grünem Gate; **MR immer gegen `staging`** —
   nie production. Zweigt die Arbeit von einem anderen Branch ab
   (production, debian13, …), den Migration-Commit vor dem MR per
   Cherry-Pick auf `origin/staging` umsetzen, damit der Diff nur die
   Migration enthält.
2. **Dependency**: `dj-healthz = {git = "https://github.com/sostrowsk/dj-healthz.git", branch = "main"}`
   in pyproject.toml (poetry lock + install). **Öffentliche GitHub-HTTPS-URL,
   nicht GitLab-SSH** — Docker-/CI-Builds haben keinen SSH-Key; eine
   ssh-Dependency bricht `poetry install` in jedem Image-Build.
3. **Settings**: `"healthz"` in `INSTALLED_APPS`; `HEALTHZ`-Dict nach
   Projektbedarf (Criticality-Flags explizit setzen — Registry-Default ist
   `critical: True`!); `ALLOWED_HOSTS` um `localhost`/`127.0.0.1` ergänzen;
   bei `SECURE_SSL_REDIRECT=True` die `SECURE_REDIRECT_EXEMPT`-Patterns aus
   dem README.
4. **URLs**: `path("", include("healthz.urls"))` **außerhalb**
   `i18n_patterns`. Alte Health-URLs entfernen. Extern konsumierte
   Alt-Pfade, die dj-healthz nicht serviert, als Alias auf
   `healthz.views.healthz` erhalten — niemals einen von Monitoren/Dockern
   konsumierten Pfad stilllegen (vorher Dockerfile/compose/Ansible/nginx/
   cron/Frontend greppen).
5. **Alt-Code entfernen — konservativ**: nur die Health-*Endpoint*-
   Implementierung löschen. Hintergrund-Tasks, Monitoring-Dashboards und
   Metrik-Infrastruktur, die andernorts konsumiert werden, bleiben.
6. **Tests (TDD)**: bestehende Health-Tests auf das neue Verhalten
   portieren (RED gegen unmigrierten Stand, dann GREEN). Mindest-Smoke:
   `/healthz` 200 plain, `/readyz` 200/503, `/health/`
   `application/health+json`, POST 405, kein Locale-/Slash-Redirect.
   Migrationsdateien durch die **aktuelle** Lint-Config des Projekts
   schicken (black/isort seit dem CI-Rollout 2026-07).
7. **Gate**: Projekt-Lint/Tests + `codex review --uncommitted`; P1 fixen
   und **alle Findings offenlegen**. `manage.py check` clean,
   `makemigrations --check --dry-run` clean.
8. **Ein atomarer Commit**, dann MR gegen staging; Auto-Merge nutzen, wo
   Pipeline-Pflicht besteht; Branch-Cleanup via `--remove-source-branch`.

## Lessons Learned (Wave 1+2)

- **Parallel laufende Rollouts einplanen:** Der CI-Templates-Rollout
  (repo-weites black/isort-Reformat) landete mitten in der Migration auf
  staging — alle Branches mussten einmal rebased werden. Vor dem Merge
  `git fetch` + Konfliktcheck.
- **Runner-Kapazität:** Beide CI-Runner haben 38 GB Disk. Mehrere parallele
  `build-base`-Jobs (leasing: texlive, 6-GB-Image) füllen sie transient →
  Kaskadenfehler ("no space left", initdb-Fail, exit 127). Bei CI-Rot immer
  das `runner`-Feld des Jobs prüfen (es gibt ci-runner1 **und** ci-runner2)
  und `docker volume prune -af` (benannte Volumes!) + alte
  Content-Hash-Base-Images aufräumen.
- **Semantik-Änderungen dokumentieren:** 500→503 bei Dependency-Ausfall und
  health+json statt Ad-hoc-JSON sind für Konsumenten Breaking Changes — im
  MR benennen, Konsumenten vorher greppen (investorselects 307-Falle und
  jeanmarcels JSON-Parser waren die Lehrstücke aus SURVEY/Review).
