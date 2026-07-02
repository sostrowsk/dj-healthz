from django.test import modify_settings, override_settings

from healthz.checks.staticfiles import check

MANIFEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}
PLAIN_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class TestOkPath:
    @override_settings(STORAGES=PLAIN_STORAGES, STATIC_URL="/static/")
    def test_plain_storage_resolves_probe_url(self):
        result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0

    def test_manifest_storage_with_manifest_present(self, tmp_path):
        (tmp_path / "staticfiles.json").write_text('{"version": "1.1", "paths": {}}')
        with override_settings(STORAGES=MANIFEST_STORAGES, STATIC_ROOT=str(tmp_path)):
            result = check()
        assert result["status"] == "ok"


class TestErrorPath:
    def test_manifest_storage_with_missing_manifest(self, tmp_path, caplog):
        with caplog.at_level("ERROR", logger="healthz"):
            with override_settings(STORAGES=MANIFEST_STORAGES, STATIC_ROOT=str(tmp_path)):
                result = check()
        assert result["status"] == "error"
        assert result["error_class"] == "FileNotFoundError"
        assert isinstance(result["response_time_ms"], float)
        assert str(tmp_path) not in str(result)
        assert caplog.text != ""

    def test_unresolvable_static_url_reports_error_class_only(self, caplog):
        with caplog.at_level("ERROR", logger="healthz"):
            with override_settings(STORAGES=PLAIN_STORAGES, STATIC_URL=None):
                result = check()
        assert result["status"] == "error"
        assert result["error_class"] == "ImproperlyConfigured"
        assert "STATIC_URL" not in str(result)
        assert "STATIC_URL" in caplog.text


class TestSkippedPath:
    def test_skipped_without_staticfiles_app(self):
        with modify_settings(INSTALLED_APPS={"remove": "django.contrib.staticfiles"}):
            result = check()
        assert result["status"] == "skipped"
        assert isinstance(result["response_time_ms"], float)
