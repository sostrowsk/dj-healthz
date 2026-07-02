"""Fake check module declaring a missing optional dependency (E002 fixture)."""

REQUIRES = ("nonexistent_dependency_xyz",)


def check(**options):
    return {"status": "ok", "response_time_ms": 0.1}
