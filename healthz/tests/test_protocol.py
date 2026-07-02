from healthz.protocol import CheckResult, aggregate


def make_result(status="ok", critical=True, **kwargs):
    return CheckResult(name="probe", status=status, response_time_ms=1.0,
                       critical=critical, **kwargs)


class TestFromOutput:
    def test_valid_dict_maps_fields(self):
        result = CheckResult.from_output(
            "database",
            {"status": "ok", "response_time_ms": 3.2, "detail": "3 aliases"},
            critical=True,
            elapsed_ms=9.9,
        )
        assert result.name == "database"
        assert result.status == "ok"
        assert result.response_time_ms == 3.2
        assert result.detail == "3 aliases"
        assert result.critical is True

    def test_error_class_carried_over(self):
        result = CheckResult.from_output(
            "redis",
            {"status": "error", "response_time_ms": 1.0, "error_class": "ConnectionError"},
            critical=True,
            elapsed_ms=2.0,
        )
        assert result.error_class == "ConnectionError"

    def test_missing_response_time_falls_back_to_elapsed(self):
        result = CheckResult.from_output("c", {"status": "ok"}, critical=True, elapsed_ms=7.5)
        assert result.response_time_ms == 7.5

    def test_non_dict_return_becomes_error(self):
        result = CheckResult.from_output("c", "broken", critical=True, elapsed_ms=1.0)
        assert result.status == "error"
        assert result.error_class == "InvalidCheckResult"

    def test_invalid_status_value_becomes_error(self):
        result = CheckResult.from_output(
            "c", {"status": "green"}, critical=True, elapsed_ms=1.0
        )
        assert result.status == "error"
        assert result.error_class == "InvalidCheckResult"


class TestHealthStatusMapping:
    def test_ok_maps_to_pass(self):
        assert make_result("ok").health_status == "pass"

    def test_skipped_maps_to_pass(self):
        assert make_result("skipped").health_status == "pass"

    def test_critical_error_maps_to_fail(self):
        assert make_result("error", critical=True).health_status == "fail"

    def test_non_critical_error_maps_to_warn(self):
        assert make_result("error", critical=False).health_status == "warn"


class TestAggregate:
    def test_all_ok_is_pass(self):
        assert aggregate([make_result("ok"), make_result("skipped")]) == "pass"

    def test_non_critical_error_is_warn(self):
        assert aggregate([make_result("ok"), make_result("error", critical=False)]) == "warn"

    def test_critical_error_wins_over_warn(self):
        results = [
            make_result("error", critical=False),
            make_result("error", critical=True),
            make_result("ok"),
        ]
        assert aggregate(results) == "fail"

    def test_empty_is_pass(self):
        assert aggregate([]) == "pass"
