"""Built-in check: tempfile write/read/delete round-trip."""

import logging
import tempfile
import time
import uuid
from pathlib import Path

logger = logging.getLogger("healthz")


def check(**options) -> dict:
    start = time.monotonic()
    directory = Path(options.get("path") or tempfile.gettempdir())
    probe = directory / f"healthz-probe-{uuid.uuid4().hex}.tmp"
    content = uuid.uuid4().hex.encode()
    try:
        probe.write_bytes(content)
        read_back = probe.read_bytes()
        probe.unlink()
        if read_back != content:
            raise ValueError("content mismatch after write/read round-trip")
    except Exception as exc:
        probe.unlink(missing_ok=True)
        logger.exception("healthz filesystem check failed in %s", directory)
        return {
            "status": "error",
            "response_time_ms": (time.monotonic() - start) * 1000,
            "error_class": type(exc).__name__,
        }
    return {"status": "ok", "response_time_ms": (time.monotonic() - start) * 1000}
