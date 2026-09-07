from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

ACCEPTANCE_SOURCE = Path(
    "scripts/odroid/run_odroid_deployment_acceptance_v1.sh"
).read_text(encoding="utf-8")


# -- Bash syntax --


def test_bash_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", "scripts/odroid/run_odroid_deployment_acceptance_v1.sh"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


# -- Health check: no grep, uses Python JSON --


def test_health_check_does_not_use_grep_for_ok() -> None:
    assert 'grep -q \'"ok":true\'' not in ACCEPTANCE_SOURCE
    assert "grep.*ok.*true" not in ACCEPTANCE_SOURCE
    assert "grep.*'ok'" not in ACCEPTANCE_SOURCE


def test_health_check_uses_json_loads() -> None:
    assert "json.loads" in ACCEPTANCE_SOURCE


def test_health_check_checks_ok_is_true() -> None:
    assert 'data["ok"] is not True' in ACCEPTANCE_SOURCE


def test_health_check_checks_missing_ok_field() -> None:
    assert '"ok" not in data' in ACCEPTANCE_SOURCE


def test_health_check_body_passed_via_env_var_not_inline() -> None:
    # Response body must be passed via env var to avoid shell injection and secret leakage.
    assert "SYNTH_HEALTH_BODY" in ACCEPTANCE_SOURCE
    assert 'os.environ.get("SYNTH_HEALTH_BODY"' in ACCEPTANCE_SOURCE


def test_health_check_curl_failure_is_retried() -> None:
    # curl failure must use `continue`, not abort the retry loop immediately.
    assert "curl_failed" in ACCEPTANCE_SOURCE
    assert "continue" in ACCEPTANCE_SOURCE


def test_health_check_retry_loop_present() -> None:
    assert "WEB_AUTH_HEALTH_RETRIES" in ACCEPTANCE_SOURCE
    assert "WEB_AUTH_HEALTH_INTERVAL" in ACCEPTANCE_SOURCE
    assert "sleep" in ACCEPTANCE_SOURCE


def test_health_check_abort_after_all_retries() -> None:
    assert "web-auth health check failed after" in ACCEPTANCE_SOURCE


# -- Health check: Python inline logic correctness --


def _run_health_check_python(body: str) -> tuple[int, str, str]:
    """Run the embedded Python health check logic with the given response body."""
    code = """
import json, os, sys
body = os.environ.get("SYNTH_HEALTH_BODY", "")
try:
    data = json.loads(body)
except Exception as exc:
    print(f"health_check=invalid_json detail={exc}", file=sys.stderr)
    sys.exit(1)
if "ok" not in data:
    print("health_check=missing_ok_field", file=sys.stderr)
    sys.exit(1)
if data["ok"] is not True:
    print(f"health_check=not_ok value={data['ok']!r}", file=sys.stderr)
    sys.exit(1)
"""
    result = subprocess.run(
        ["python3", "-c", code],
        env={"SYNTH_HEALTH_BODY": body, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def test_health_python_ok_true_passes() -> None:
    rc, _, _ = _run_health_check_python('{"ok": true}')
    assert rc == 0


def test_health_python_ok_true_with_extra_fields_passes() -> None:
    rc, _, _ = _run_health_check_python('{"ok": true, "uptime": 123, "version": "1.0"}')
    assert rc == 0


def test_health_python_ok_true_with_whitespace_passes() -> None:
    rc, _, _ = _run_health_check_python('{\n  "ok":\n  true\n}')
    assert rc == 0


def test_health_python_ok_false_fails() -> None:
    rc, _, stderr = _run_health_check_python('{"ok": false}')
    assert rc != 0
    assert "not_ok" in stderr


def test_health_python_ok_string_true_fails() -> None:
    rc, _, stderr = _run_health_check_python('{"ok": "true"}')
    assert rc != 0
    assert "not_ok" in stderr


def test_health_python_ok_one_fails() -> None:
    rc, _, stderr = _run_health_check_python('{"ok": 1}')
    assert rc != 0
    assert "not_ok" in stderr


def test_health_python_missing_ok_field_fails() -> None:
    rc, _, stderr = _run_health_check_python('{"status": "up"}')
    assert rc != 0
    assert "missing_ok_field" in stderr


def test_health_python_invalid_json_fails() -> None:
    rc, _, stderr = _run_health_check_python("not json at all")
    assert rc != 0
    assert "invalid_json" in stderr


def test_health_python_empty_body_fails() -> None:
    rc, _, stderr = _run_health_check_python("")
    assert rc != 0
    assert "invalid_json" in stderr


def test_health_python_does_not_print_body_to_stdout() -> None:
    secret_body = '{"ok": false, "secret_token": "abc123"}'
    _, stdout, _ = _run_health_check_python(secret_body)
    assert "abc123" not in stdout
    assert "secret_token" not in stdout


# -- File freshness verification --


def test_freshness_check_records_acceptance_start_epoch() -> None:
    assert "ACCEPTANCE_START_EPOCH" in ACCEPTANCE_SOURCE


def test_freshness_check_uses_getmtime() -> None:
    assert "getmtime" in ACCEPTANCE_SOURCE


def test_freshness_check_uses_env_var_for_path_and_start() -> None:
    assert "SYNTH_FILE_PATH" in ACCEPTANCE_SOURCE
    assert "SYNTH_ACCEPTANCE_START" in ACCEPTANCE_SOURCE


def test_freshness_check_rejects_file_older_than_start() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        old_file = Path(tmpdir) / "wallet.html"
        old_file.write_text("<html>old</html>")
        # backdate the file by 60 seconds
        old_mtime = time.time() - 60
        import os
        os.utime(str(old_file), (old_mtime, old_mtime))

        acceptance_start = int(time.time())

        code = """
import os, sys
fpath = os.environ["SYNTH_FILE_PATH"]
acceptance_start = int(os.environ["SYNTH_ACCEPTANCE_START"])
try:
    mtime = os.path.getmtime(fpath)
except OSError as exc:
    print(f"verify=mtime_error file={fpath} {exc}", file=sys.stderr)
    sys.exit(1)
if mtime < acceptance_start:
    age_sec = acceptance_start - int(mtime)
    print(f"verify=STALE file={fpath} file_age_sec={age_sec}", file=sys.stderr)
    sys.exit(1)
"""
        result = subprocess.run(
            ["python3", "-c", code],
            env={
                "SYNTH_FILE_PATH": str(old_file),
                "SYNTH_ACCEPTANCE_START": str(acceptance_start),
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "STALE" in result.stderr


def test_freshness_check_accepts_file_written_after_start() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        acceptance_start = int(time.time()) - 5

        new_file = Path(tmpdir) / "wallet.html"
        new_file.write_text("<html>fresh</html>")

        code = """
import os, sys
fpath = os.environ["SYNTH_FILE_PATH"]
acceptance_start = int(os.environ["SYNTH_ACCEPTANCE_START"])
try:
    mtime = os.path.getmtime(fpath)
except OSError as exc:
    print(f"verify=mtime_error file={fpath} {exc}", file=sys.stderr)
    sys.exit(1)
if mtime < acceptance_start:
    age_sec = acceptance_start - int(mtime)
    print(f"verify=STALE file={fpath} file_age_sec={age_sec}", file=sys.stderr)
    sys.exit(1)
"""
        result = subprocess.run(
            ["python3", "-c", code],
            env={
                "SYNTH_FILE_PATH": str(new_file),
                "SYNTH_ACCEPTANCE_START": str(acceptance_start),
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_freshness_check_fails_on_missing_file() -> None:
    code = """
import os, sys
fpath = os.environ["SYNTH_FILE_PATH"]
acceptance_start = int(os.environ["SYNTH_ACCEPTANCE_START"])
try:
    mtime = os.path.getmtime(fpath)
except OSError as exc:
    print(f"verify=mtime_error file={fpath} {exc}", file=sys.stderr)
    sys.exit(1)
if mtime < acceptance_start:
    age_sec = acceptance_start - int(mtime)
    print(f"verify=STALE file={fpath} file_age_sec={age_sec}", file=sys.stderr)
    sys.exit(1)
"""
    result = subprocess.run(
        ["python3", "-c", code],
        env={
            "SYNTH_FILE_PATH": "/tmp/synth-test-nonexistent-file-abc123.html",
            "SYNTH_ACCEPTANCE_START": "9999999999",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "mtime_error" in result.stderr


# -- Script-level structural checks --


def test_acceptance_start_epoch_recorded_before_refresh() -> None:
    # ACCEPTANCE_START_EPOCH must appear before run_linked_profile_dashboard_refresh_once.sh call.
    start_pos = ACCEPTANCE_SOURCE.find("ACCEPTANCE_START_EPOCH")
    refresh_pos = ACCEPTANCE_SOURCE.find("run_linked_profile_dashboard_refresh_once.sh")
    assert start_pos != -1, "ACCEPTANCE_START_EPOCH not found in script"
    assert refresh_pos != -1, "refresh script call not found"
    assert start_pos < refresh_pos, (
        "ACCEPTANCE_START_EPOCH must be recorded before the refresh call"
    )



def test_refresh_failure_aborts_before_freshness_attribution() -> None:
    refresh_pos = ACCEPTANCE_SOURCE.find('bash "${SCRIPT_DIR}/run_linked_profile_dashboard_refresh_once.sh"')
    abort_pos = ACCEPTANCE_SOURCE.find('[abort] linked-profile dashboard refresh did not run successfully')
    verify_pos = ACCEPTANCE_SOURCE.find('verify_file_fresh()')
    assert refresh_pos != -1
    assert abort_pos != -1
    assert verify_pos != -1
    assert 'if ! SYNTH_REPO_DIR=' in ACCEPTANCE_SOURCE
    assert refresh_pos < abort_pos < verify_pos


def test_verify_uses_verify_file_fresh_function() -> None:
    assert "verify_file_fresh" in ACCEPTANCE_SOURCE


def test_no_secrets_printed_in_script() -> None:
    assert "echo.*SYNTH_HEALTH_BODY" not in ACCEPTANCE_SOURCE
    assert "print.*health_body" not in ACCEPTANCE_SOURCE


def test_safety_markers_present() -> None:
    assert "broker_private_calls=0" in ACCEPTANCE_SOURCE
    assert "broker_writes=0" in ACCEPTANCE_SOURCE
    assert "order_submission=0" in ACCEPTANCE_SOURCE


def main() -> None:
    test_bash_syntax_valid()
    test_health_check_does_not_use_grep_for_ok()
    test_health_check_uses_json_loads()
    test_health_check_checks_ok_is_true()
    test_health_check_checks_missing_ok_field()
    test_health_check_body_passed_via_env_var_not_inline()
    test_health_check_curl_failure_is_retried()
    test_health_check_retry_loop_present()
    test_health_check_abort_after_all_retries()
    test_health_python_ok_true_passes()
    test_health_python_ok_true_with_extra_fields_passes()
    test_health_python_ok_true_with_whitespace_passes()
    test_health_python_ok_false_fails()
    test_health_python_ok_string_true_fails()
    test_health_python_ok_one_fails()
    test_health_python_missing_ok_field_fails()
    test_health_python_invalid_json_fails()
    test_health_python_empty_body_fails()
    test_health_python_does_not_print_body_to_stdout()
    test_freshness_check_records_acceptance_start_epoch()
    test_freshness_check_uses_getmtime()
    test_freshness_check_uses_env_var_for_path_and_start()
    test_freshness_check_rejects_file_older_than_start()
    test_freshness_check_accepts_file_written_after_start()
    test_freshness_check_fails_on_missing_file()
    test_acceptance_start_epoch_recorded_before_refresh()
    test_refresh_failure_aborts_before_freshness_attribution()
    test_verify_uses_verify_file_fresh_function()
    test_no_secrets_printed_in_script()
    test_safety_markers_present()
    print("ok")


if __name__ == "__main__":
    main()
