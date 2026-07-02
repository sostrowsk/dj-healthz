import re
from unittest import mock

from django.test import override_settings

from healthz.checks.storage import check

INMEMORY = "django.core.files.storage.InMemoryStorage"


def _fake_storage() -> mock.Mock:
    storage = mock.Mock()
    storage.save.side_effect = lambda name, content: name
    storage.exists.return_value = True
    return storage


class TestOkPath:
    @override_settings(STORAGES={"default": {"BACKEND": INMEMORY}})
    def test_roundtrip_with_default_storage(self):
        result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0

    def test_no_probe_file_left_behind(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        result = check()
        assert result["status"] == "ok"
        assert [path for path in tmp_path.rglob("*") if path.is_file()] == []

    def test_storage_option_overrides_default_storage(self):
        with mock.patch("healthz.checks.storage.default_storage") as unused_default:
            result = check(storage=INMEMORY)
        assert result["status"] == "ok"
        unused_default.save.assert_not_called()

    def test_probe_name_matches_spec_pattern(self):
        storage = _fake_storage()
        with mock.patch("healthz.checks.storage.default_storage", storage):
            result = check()
        assert result["status"] == "ok"
        saved_name = storage.save.call_args[0][0]
        assert re.fullmatch(r"healthz/probe-[0-9a-f]{32}\.txt", saved_name)
        storage.delete.assert_called_once_with(saved_name)


class TestErrorPath:
    def test_save_failure_reports_error_class_only(self, caplog):
        storage = _fake_storage()
        storage.save.side_effect = OSError("s3://user:secret@bucket unreachable")
        with caplog.at_level("ERROR", logger="healthz"):
            with mock.patch("healthz.checks.storage.default_storage", storage):
                result = check()
        assert result["status"] == "error"
        assert result["error_class"] == "OSError"
        assert isinstance(result["response_time_ms"], float)
        assert "secret" not in str(result)
        assert "s3://user:secret@bucket unreachable" in caplog.text

    def test_missing_after_save_reports_error_and_cleans_up(self, caplog):
        storage = _fake_storage()
        storage.exists.return_value = False
        with caplog.at_level("ERROR", logger="healthz"):
            with mock.patch("healthz.checks.storage.default_storage", storage):
                result = check()
        assert result["status"] == "error"
        assert result["error_class"] == "FileNotFoundError"
        storage.delete.assert_called_once()

    def test_bad_storage_dotted_path_reports_error(self, caplog):
        with caplog.at_level("ERROR", logger="healthz"):
            result = check(storage="nonexistent.module.Storage")
        assert result["status"] == "error"
        assert result["error_class"] == "ModuleNotFoundError"
