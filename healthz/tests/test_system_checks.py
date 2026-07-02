from django.test import override_settings

from healthz.checks import broker, cache, redis
from healthz.system_checks import check_healthz_config, check_ssl_redirect_exemption


def ok_check(**options):
    return {"status": "ok", "response_time_ms": 0.1}


GOOD_CHECKS = {"custom": {"check": "healthz.tests.test_system_checks.ok_check"}}


def ids(messages):
    return [message.id for message in messages]


class TestE001:
    @override_settings(HEALTHZ={"CHECKS": {"no_such_builtin": {}}})
    def test_unknown_builtin_name(self):
        assert ids(check_healthz_config(None)) == ["healthz.E001"]

    @override_settings(HEALTHZ={"CHECKS": {"custom": {"check": "nope.missing.check"}}})
    def test_unimportable_dotted_path(self):
        assert ids(check_healthz_config(None)) == ["healthz.E001"]

    @override_settings(HEALTHZ={"CHECKS": GOOD_CHECKS})
    def test_clean_config_has_no_messages(self):
        assert check_healthz_config(None) == []


class TestE002:
    @override_settings(HEALTHZ={"CHECKS": {
        "needy": {"check": "healthz.tests.fake_requires.check"},
    }})
    def test_explicit_check_with_missing_dependency(self):
        assert ids(check_healthz_config(None)) == ["healthz.E002"]

    @override_settings(HEALTHZ={"CHECKS": {
        "satisfied": {"check": "healthz.tests.fake_requires_ok.check"},
    }})
    def test_available_dependency_is_clean(self):
        assert check_healthz_config(None) == []

    @override_settings(HEALTHZ={"CHECKS": {
        "needy": {"check": "healthz.tests.fake_requires.check"},
    }})
    def test_missing_package_message_names_the_dependency(self):
        (message,) = check_healthz_config(None)
        assert "dependency" in message.msg

    @override_settings(HEALTHZ={"CHECKS": {
        "unconfigured": {"check": "healthz.tests.fake_needs_config.check"},
    }})
    def test_explicit_check_with_missing_configuration(self):
        messages = check_healthz_config(None)
        assert ids(messages) == ["healthz.E002"]
        assert "configuration" in messages[0].msg

    @override_settings(HEALTHZ={"CHECKS": {
        "configured": {"check": "healthz.tests.fake_needs_config.check", "url": "redis://x"},
    }})
    def test_explicit_check_with_configuration_is_clean(self):
        assert check_healthz_config(None) == []


class TestIsConfiguredHooks:
    @override_settings(CELERY_BROKER_URL=None)
    def test_broker_unconfigured_without_url(self):
        assert broker.is_configured({"timeout": 5.0}) is False

    @override_settings(CELERY_BROKER_URL=None)
    def test_broker_configured_via_option(self):
        assert broker.is_configured({"broker_url": "redis://localhost:6379/0"}) is True

    @override_settings(CELERY_BROKER_URL="amqp://guest@rabbit:5672//")
    def test_broker_configured_via_setting(self):
        assert broker.is_configured({}) is True

    def test_redis_unconfigured_without_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert redis.is_configured({"timeout": 5.0}) is False

    def test_redis_configured_via_option(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert redis.is_configured({"redis_url": "redis://localhost:6379/0"}) is True

    @override_settings(REDIS_URL="redis://setting:6379/0")
    def test_redis_configured_via_setting(self):
        assert redis.is_configured({}) is True

    def test_redis_configured_via_env(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://env:6379/0")
        assert redis.is_configured({}) is True


class TestHealthzNone:
    @override_settings(HEALTHZ=None)
    def test_none_setting_is_treated_like_absent(self):
        assert check_healthz_config(None) == []
        assert check_ssl_redirect_exemption(None) == []


class TestE004:
    @override_settings(HEALTHZ={"EXPOSE": "tokn", "TOKEN": "t0k", "CHECKS": GOOD_CHECKS})
    def test_invalid_expose_value(self):
        assert ids(check_healthz_config(None)) == ["healthz.E004"]

    @override_settings(HEALTHZ={"EXPOSE": "staff", "CHECKS": GOOD_CHECKS})
    def test_valid_expose_values_are_clean(self):
        assert check_healthz_config(None) == []


class TestCacheAliasConfigured:
    @override_settings(HEALTHZ={"CHECKS": {"cache": {"alias": "no-such-alias"}}})
    def test_explicit_cache_with_unknown_alias_is_e002(self):
        assert ids(check_healthz_config(None)) == ["healthz.E002"]

    def test_default_alias_is_configured(self):
        assert cache.is_configured({}) is True

    def test_unknown_alias_is_not_configured(self):
        assert cache.is_configured({"alias": "no-such-alias"}) is False


class TestE003:
    @override_settings(HEALTHZ={"EXPOSE": "token", "CHECKS": GOOD_CHECKS})
    def test_token_mode_without_token(self):
        assert "healthz.E003" in ids(check_healthz_config(None))

    @override_settings(HEALTHZ={"EXPOSE": "token", "TOKEN": "x", "CHECKS": GOOD_CHECKS})
    def test_token_mode_with_token_is_clean(self):
        assert check_healthz_config(None) == []


class TestW001:
    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[])
    def test_ssl_redirect_without_exemption_warns(self):
        assert ids(check_ssl_redirect_exemption(None)) == ["healthz.W001"]

    @override_settings(
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^(healthz|livez|readyz|health/)$"],
    )
    def test_exempted_paths_are_clean(self):
        assert check_ssl_redirect_exemption(None) == []

    @override_settings(SECURE_SSL_REDIRECT=False, SECURE_REDIRECT_EXEMPT=[])
    def test_no_ssl_redirect_is_clean(self):
        assert check_ssl_redirect_exemption(None) == []


class TestRegistration:
    def test_checks_are_registered(self):
        from django.core.checks.registry import registry as django_registry

        registered = {func.__name__ for func in django_registry.registered_checks}
        assert "check_healthz_config" in registered
        assert "check_ssl_redirect_exemption" in registered
