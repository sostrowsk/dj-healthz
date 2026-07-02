from django.test import override_settings

from healthz import conf


# HEALTHZ=None must behave exactly like an absent HEALTHZ setting; overriding
# to None also makes these tests independent of any host project's settings.
class TestDefaults:
    @override_settings(HEALTHZ=None)
    def test_none_healthz_behaves_like_absent(self):
        assert conf.get("CHECKS") == conf.DEFAULTS["CHECKS"]
        assert conf.get("EXPOSE") == conf.DEFAULTS["EXPOSE"]

    @override_settings(HEALTHZ=None)
    def test_zero_config_checks_are_database_and_cache(self):
        assert conf.get("CHECKS") == {"database": {}, "cache": {}}

    @override_settings(HEALTHZ=None)
    def test_scalar_defaults(self):
        assert conf.get("EXPOSE") == "public"
        assert conf.get("TOKEN") is None
        assert conf.get("CACHE_SECONDS") == 0
        assert conf.get("TIMEOUT") == 5.0
        assert conf.get("BUDGET") == 10.0
        assert conf.get("SERVICE_ID") is None
        assert conf.get("RELEASE_ID") is None
        assert conf.get("ENVIRONMENT") is None


class TestOverrides:
    @override_settings(HEALTHZ={"TIMEOUT": 2.0})
    def test_partial_override_keeps_other_defaults(self):
        assert conf.get("TIMEOUT") == 2.0
        assert conf.get("CHECKS") == {"database": {}, "cache": {}}
        assert conf.get("BUDGET") == 10.0

    @override_settings(HEALTHZ={"CHECKS": {"database": {"critical": False}}})
    def test_explicit_checks_replace_defaults(self):
        assert conf.get("CHECKS") == {"database": {"critical": False}}
