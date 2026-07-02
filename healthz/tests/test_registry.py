import pytest
from django.test import override_settings

from healthz import registry


def fake_check(**options):
    return {"status": "ok", "response_time_ms": 0.1}


EXPECTED_BUILTINS = {
    "database", "cache", "redis", "broker", "celery_workers",
    "filesystem", "storage", "migrations", "staticfiles",
}


class TestBuiltins:
    def test_builtin_names(self):
        assert set(registry.BUILTINS) == EXPECTED_BUILTINS

    def test_builtin_paths_follow_convention(self):
        for name, path in registry.BUILTINS.items():
            assert path == f"healthz.checks.{name}.check"


class TestBuildChecks:
    @override_settings(HEALTHZ=None)
    def test_zero_config_enables_database_and_cache(self):
        checks = registry.build_checks()
        assert [c.name for c in checks] == ["database", "cache"]
        for check in checks:
            assert check.critical is True
            assert check.readiness is True
            assert check.timeout == 5.0

    @override_settings(HEALTHZ=None)
    def test_builtin_name_resolves_to_builtin_path(self):
        checks = registry.build_checks()
        assert checks[0].path == "healthz.checks.database.check"

    @override_settings(HEALTHZ={
        "CHECKS": {"custom": {"check": "healthz.tests.test_registry.fake_check"}},
    })
    def test_custom_dotted_path(self):
        (check,) = registry.build_checks()
        assert check.path == "healthz.tests.test_registry.fake_check"
        assert check.resolve() is fake_check

    @override_settings(HEALTHZ={
        "TIMEOUT": 4.0,
        "CHECKS": {"database": {"critical": False, "readiness": False, "timeout": 1.5,
                                "aliases": ["default"]}},
    })
    def test_per_check_options(self):
        (check,) = registry.build_checks()
        assert check.critical is False
        assert check.readiness is False
        assert check.timeout == 1.5
        assert check.options["aliases"] == ["default"]
        assert check.options["timeout"] == 1.5

    @override_settings(HEALTHZ={"CHECKS": {"cache": {}}})
    def test_timeout_defaults_to_global_setting(self):
        with override_settings(HEALTHZ={"TIMEOUT": 2.5, "CHECKS": {"cache": {}}}):
            (check,) = registry.build_checks()
            assert check.timeout == 2.5

    @override_settings(HEALTHZ=None)
    def test_building_builtins_does_not_import_check_modules(self):
        # healthz.checks.database does not exist yet — building must stay lazy.
        checks = registry.build_checks()
        assert checks

    @override_settings(HEALTHZ={"CHECKS": {"no_such_builtin": {}}})
    def test_unknown_builtin_has_no_path(self):
        (check,) = registry.build_checks()
        assert check.path is None
        with pytest.raises(registry.UnknownCheck):
            check.resolve()


class TestResolutionErrors:
    @override_settings(HEALTHZ={"CHECKS": {"no_such_builtin": {}}})
    def test_unknown_builtin_reported(self):
        errors = registry.resolution_errors()
        assert len(errors) == 1
        assert "no_such_builtin" in errors[0]

    @override_settings(HEALTHZ={"CHECKS": {"custom": {"check": "nope.does.not.exist"}}})
    def test_unimportable_dotted_path_reported(self):
        errors = registry.resolution_errors()
        assert len(errors) == 1
        assert "nope.does.not.exist" in errors[0]

    @override_settings(HEALTHZ={
        "CHECKS": {"custom": {"check": "healthz.tests.test_registry.fake_check"}},
    })
    def test_importable_custom_check_is_clean(self):
        assert registry.resolution_errors() == []
