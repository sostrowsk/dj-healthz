import tempfile
from pathlib import Path
from unittest import mock

from healthz.checks.filesystem import check


class TestOkPath:
    def test_roundtrip_in_default_tempdir(self):
        result = check(timeout=5.0)
        assert result["status"] == "ok"
        assert isinstance(result["response_time_ms"], float)
        assert result["response_time_ms"] >= 0

    def test_path_option_overrides_tempdir_and_probe_is_deleted(self, tmp_path):
        result = check(path=str(tmp_path))
        assert result["status"] == "ok"
        assert list(tmp_path.iterdir()) == []

    def test_no_probe_file_left_in_default_tempdir(self):
        before = set(Path(tempfile.gettempdir()).iterdir())
        check()
        after = set(Path(tempfile.gettempdir()).iterdir())
        assert after - before == set()


class TestErrorPath:
    def test_unwritable_dir_reports_error_class_only(self, caplog):
        with caplog.at_level("ERROR", logger="healthz"):
            result = check(path="/nonexistent-dir/x")
        assert result["status"] == "error"
        assert result["error_class"] == "FileNotFoundError"
        assert isinstance(result["response_time_ms"], float)
        assert "/nonexistent-dir/x" not in str(result)
        assert "/nonexistent-dir/x" in caplog.text

    def test_content_mismatch_reports_error(self, tmp_path, caplog):
        with caplog.at_level("ERROR", logger="healthz"):
            with mock.patch.object(Path, "read_bytes", return_value=b"corrupted"):
                result = check(path=str(tmp_path))
        assert result["status"] == "error"
        assert result["error_class"] == "ValueError"
        assert list(tmp_path.iterdir()) == []
