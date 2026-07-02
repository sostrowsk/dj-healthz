#!/usr/bin/env bash
# Role-aware container healthcheck (CONTAINER_ROLE=web|worker|beat).
# Usage in Dockerfile: HEALTHCHECK CMD ["bash", "/app/docker-healthcheck.sh"]
set -euo pipefail

role="${CONTAINER_ROLE:-web}"

case "$role" in
    web)
        url="http://localhost:${PORT:-8000}${HEALTHZ_PATH:-/readyz}"
        if command -v curl > /dev/null 2>&1; then
            exec curl -fsS "$url" > /dev/null
        fi
        exec wget --spider -q "$url"
        ;;
    worker)
        if [ -z "${CELERY_APP:-}" ]; then
            echo "healthcheck: CELERY_APP must be set for CONTAINER_ROLE=worker" >&2
            exit 1
        fi
        exec celery -A "$CELERY_APP" inspect ping \
            -d "celery@${HOSTNAME:-$(hostname)}" --timeout "${TIMEOUT:-10}"
        ;;
    beat)
        pidfile="${BEAT_PIDFILE:-/tmp/celerybeat.pid}"
        if [ ! -f "$pidfile" ]; then
            echo "healthcheck: beat pidfile not found: $pidfile" >&2
            exit 1
        fi
        kill -0 "$(cat "$pidfile")"
        ;;
    *)
        echo "healthcheck: unknown CONTAINER_ROLE: $role" >&2
        exit 1
        ;;
esac
