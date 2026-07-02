# dj-healthz

Django app package `healthz` (App-Label, Import-Pfad). Host-Projekte pinnen
dieses Repo als Poetry-git-Dependency auf `main` — jeder Push auf main ist
sofort releasebar.

Spec: `docs/SPEC.md` (autoritativ). Plan/Historie: `docs/PLAN.md`,
Fleet-Analyse: `docs/SURVEY.md`.

## TDD-Regeln (Pflicht)

- **Test zuerst, RED bestaetigen, dann implementieren, GREEN bestaetigen.**
- Bugfix = Regressionstest, der den Bug reproduziert und VOR dem Fix failt.
- Suite laeuft standalone (`.venv/bin/pytest` im Repo, Settings unter
  `healthz/tests/settings.py`) und aus Hosts via `pytest --pyargs healthz.tests`.
- Lint-Gate: `flake8 healthz --max-line-length=99` +
  `isort --profile black -l 99 healthz`.

## Architektur-Regeln

- **Nur Django als harte Dependency.** redis/kombu/celery/pymilvus sind
  optional: lazy imports; fehlende Dependency bei explizit konfiguriertem
  Check = System-Check-Error, nie stilles `skipped`.
- Check-Contract (dj-rag-db-kompatibel): `def check(**options) -> dict` mit
  `{"status": "ok"|"error"|"skipped", "response_time_ms": float,
  optional "detail", "error_class"}`. **Nie `str(e)` in den Dict** — Details
  nur in den `healthz`-Logger.
- Liveness (`/healthz`, `/livez`) prueft NIE Dependencies (0 DB-Queries,
  getestet). Readiness-Fehler = **503**, nie 500.
- Keine Models, keine Migrationen (`makemigrations --check` in Hosts bleibt
  clean). Keine Imports aus Host-Apps; Konfiguration nur via
  `settings.HEALTHZ` mit stabilen Defaults.
- Probe-Clients dediziert und kurzlebig — niemals shared Clients/Retry-
  Strategien zur Request-Zeit mutieren.
