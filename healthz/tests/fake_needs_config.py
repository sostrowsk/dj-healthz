"""Fake check module with an is_configured hook (E002 missing-configuration fixture)."""


def is_configured(options: dict) -> bool:
    return bool(options.get("url"))


def check(**options):
    return {"status": "ok", "response_time_ms": 0.1}
