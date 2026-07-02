import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "docker-healthcheck.sh"


def make_stub(bin_dir: Path, name: str, exit_code: int = 0) -> Path:
    log = bin_dir / f"{name}.log"
    stub = bin_dir / name
    stub.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\nexit {exit_code}\n')
    stub.chmod(0o755)
    return log


def run_script(bin_dir: Path, **env: str) -> subprocess.CompletedProcess:
    full_env = {"PATH": f"{bin_dir}:/usr/bin:/bin", **env}
    return subprocess.run(
        ["bash", str(SCRIPT)], env=full_env, capture_output=True, text=True, timeout=30
    )


def test_bash_syntax_is_valid():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_web_ok_calls_curl_with_default_url(tmp_path):
    curl_log = make_stub(tmp_path, "curl", exit_code=0)
    proc = run_script(tmp_path, CONTAINER_ROLE="web")
    assert proc.returncode == 0
    assert "http://localhost:8000/readyz" in curl_log.read_text()


def test_web_respects_port_and_path_env(tmp_path):
    curl_log = make_stub(tmp_path, "curl", exit_code=0)
    proc = run_script(tmp_path, CONTAINER_ROLE="web", PORT="9000", HEALTHZ_PATH="/healthz")
    assert proc.returncode == 0
    assert "http://localhost:9000/healthz" in curl_log.read_text()


def test_web_fail_propagates_curl_exit_code(tmp_path):
    make_stub(tmp_path, "curl", exit_code=22)
    proc = run_script(tmp_path, CONTAINER_ROLE="web")
    assert proc.returncode != 0


def test_role_defaults_to_web(tmp_path):
    curl_log = make_stub(tmp_path, "curl", exit_code=0)
    proc = run_script(tmp_path)
    assert proc.returncode == 0
    assert "http://localhost:8000/readyz" in curl_log.read_text()


def test_worker_ok_pings_via_celery(tmp_path):
    celery_log = make_stub(tmp_path, "celery", exit_code=0)
    proc = run_script(tmp_path, CONTAINER_ROLE="worker", CELERY_APP="myproj")
    assert proc.returncode == 0
    logged = celery_log.read_text()
    assert "-A myproj inspect ping" in logged
    assert "--timeout 10" in logged


def test_worker_missing_celery_app_exits_1(tmp_path):
    celery_log = tmp_path / "celery.log"
    make_stub(tmp_path, "celery", exit_code=0)
    proc = run_script(tmp_path, CONTAINER_ROLE="worker")
    assert proc.returncode == 1
    assert "CELERY_APP" in proc.stderr
    assert not celery_log.exists()


def test_beat_ok_with_fresh_pidfile_and_alive_pid(tmp_path):
    pidfile = tmp_path / "celerybeat.pid"
    pidfile.write_text(f"{os.getpid()}\n")
    proc = run_script(tmp_path, CONTAINER_ROLE="beat", BEAT_PIDFILE=str(pidfile))
    assert proc.returncode == 0


def test_beat_missing_pidfile_exits_1(tmp_path):
    proc = run_script(
        tmp_path, CONTAINER_ROLE="beat", BEAT_PIDFILE=str(tmp_path / "missing.pid")
    )
    assert proc.returncode == 1
    assert "pidfile" in proc.stderr


def test_beat_dead_pid_fails(tmp_path):
    pidfile = tmp_path / "celerybeat.pid"
    pidfile.write_text("999999999\n")
    proc = run_script(tmp_path, CONTAINER_ROLE="beat", BEAT_PIDFILE=str(pidfile))
    assert proc.returncode != 0


def test_unknown_role_exits_1_with_message(tmp_path):
    proc = run_script(tmp_path, CONTAINER_ROLE="frobnicator")
    assert proc.returncode == 1
    assert "frobnicator" in proc.stderr
