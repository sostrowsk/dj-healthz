"""Fake check module whose declared dependency is available (no E002)."""

REQUIRES = ("json",)


def check(**options):
    return {"status": "ok", "response_time_ms": 0.1}
