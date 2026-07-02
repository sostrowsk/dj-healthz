"""Fake check module whose dependency is imported but exposes no __spec__.

Models kombu 5.x, which replaces its module object with a lazy subclass whose
``__spec__`` is ``None`` — ``importlib.util.find_spec`` then raises ValueError.
"""

REQUIRES = ("fake_specless_dep",)


def check(**options):
    return {"status": "ok", "response_time_ms": 0.1}
