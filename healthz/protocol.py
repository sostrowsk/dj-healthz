"""Check dict contract (dj-rag-db compatible) and health+json status mapping."""

from dataclasses import dataclass

VALID_STATUSES = frozenset({"ok", "error", "skipped"})


@dataclass
class CheckResult:
    name: str
    status: str
    response_time_ms: float
    critical: bool = True
    detail: str | None = None
    error_class: str | None = None

    @classmethod
    def from_output(cls, name: str, output, critical: bool, elapsed_ms: float) -> "CheckResult":
        if not isinstance(output, dict) or output.get("status") not in VALID_STATUSES:
            return cls(name=name, status="error", response_time_ms=elapsed_ms,
                       critical=critical, error_class="InvalidCheckResult")
        response_time = output.get("response_time_ms")
        if not isinstance(response_time, (int, float)):
            response_time = elapsed_ms
        return cls(
            name=name,
            status=output["status"],
            response_time_ms=float(response_time),
            critical=critical,
            detail=output.get("detail"),
            error_class=output.get("error_class"),
        )

    @property
    def health_status(self) -> str:
        if self.status == "error":
            return "fail" if self.critical else "warn"
        return "pass"


def aggregate(results) -> str:
    statuses = {result.health_status for result in results}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"
