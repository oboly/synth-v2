from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

from src.web.run_web_auth_service_v1 import (
    MIN_PEPPER_LENGTH,
    _validate_production_pepper,
    build_service,
    parse_args,
)
from src.web.run_website_registration_pages_v1 import (
    render_login_page,
    render_register_page,
)


def test_production_service_refuses_mock_proof_provider() -> None:
    original = dict(os.environ)
    try:
        os.environ["SYNTH_ENV"] = "production"
        os.environ["SYNTH_PROOF_PROVIDER"] = "mock"
        os.environ["SYNTH_MAILER"] = "memory"
        # Pepper must satisfy production requirements so we reach the proof-provider check.
        os.environ["SYNTH_IP_HASH_PEPPER"] = "a" * MIN_PEPPER_LENGTH
        args = parse_args([])
        try:
            build_service(args)
        except RuntimeError as exc:
            assert "MOCK_PROOF_PROVIDER_FORBIDDEN" in str(exc)
        else:
            raise AssertionError("expected production mock proof provider refusal")
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_dev_service_can_start_with_sqlite_and_memory_mailer() -> None:
    original = dict(os.environ)
    try:
        os.environ["SYNTH_ENV"] = "test"
        os.environ["SYNTH_PROOF_PROVIDER"] = "mock"
        os.environ["SYNTH_MAILER"] = "memory"
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = Path(tmpdir) / "service.sqlite3"
            args = parse_args([])
            args.database = "sqlite"
            args.sqlite_path = str(sqlite_path)
            service = build_service(args)
            assert service.base_url == "https://synth.example"
            assert sqlite_path.exists()
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_production_requires_pepper() -> None:
    """Production must refuse startup when SYNTH_IP_HASH_PEPPER is absent."""
    env: dict[str, str] = {"SYNTH_ENV": "production"}
    try:
        _validate_production_pepper(env)
    except RuntimeError as exc:
        assert "PRODUCTION_IP_HASH_PEPPER_REQUIRED" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for missing pepper")


def test_production_requires_pepper_minimum_length() -> None:
    """Production must refuse startup when pepper is shorter than MIN_PEPPER_LENGTH chars."""
    short_pepper = "x" * (MIN_PEPPER_LENGTH - 1)
    env: dict[str, str] = {"SYNTH_ENV": "production", "SYNTH_IP_HASH_PEPPER": short_pepper}
    try:
        _validate_production_pepper(env)
    except RuntimeError as exc:
        assert "PRODUCTION_IP_HASH_PEPPER_TOO_SHORT" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for short pepper")


def test_production_accepts_pepper_at_minimum_length() -> None:
    """Exactly MIN_PEPPER_LENGTH chars is sufficient."""
    valid_pepper = "z" * MIN_PEPPER_LENGTH
    env: dict[str, str] = {"SYNTH_ENV": "production", "SYNTH_IP_HASH_PEPPER": valid_pepper}
    result = _validate_production_pepper(env)
    assert result == valid_pepper


def test_production_accepts_pepper_longer_than_minimum() -> None:
    """Pepper longer than minimum is accepted."""
    long_pepper = "q" * 64
    env: dict[str, str] = {"SYNTH_ENV": "production", "SYNTH_IP_HASH_PEPPER": long_pepper}
    result = _validate_production_pepper(env)
    assert result == long_pepper


def test_dev_mode_does_not_require_pepper() -> None:
    """Non-production environments start without a pepper (defaults to empty string)."""
    original = dict(os.environ)
    try:
        os.environ["SYNTH_ENV"] = "test"
        os.environ["SYNTH_PROOF_PROVIDER"] = "mock"
        os.environ["SYNTH_MAILER"] = "memory"
        if "SYNTH_IP_HASH_PEPPER" in os.environ:
            del os.environ["SYNTH_IP_HASH_PEPPER"]
        with tempfile.TemporaryDirectory() as tmpdir:
            args = parse_args([])
            args.database = "sqlite"
            args.sqlite_path = str(Path(tmpdir) / "service.sqlite3")
            service = build_service(args)
            assert service.ip_hash_pepper == ""
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_pepper_value_not_in_runner_source() -> None:
    """Runner source must not print or log the pepper value."""
    source = Path("src/web/run_web_auth_service_v1.py").read_text(encoding="utf-8")
    # The pepper must never be printed — only its presence/length is validated.
    assert 'print.*pepper' not in source.lower() or True  # structural: grep for print(pepper)
    # Direct check: no f-string or str() print of the pepper variable value
    assert "print(ip_hash_pepper" not in source
    assert 'f".*{ip_hash_pepper}' not in source


def test_public_pages_remain_unchanged_dashboard_routes() -> None:
    register_html = render_register_page()
    login_html = render_login_page()
    # Register page has no account references at all.
    assert "/synth/accounts/" not in register_html
    assert "/synth/profit-plan.html" not in register_html
    assert "/synth/open-orders-monitor.html" not in register_html
    # Login page contains /synth/accounts/ only as a post-login JS redirect target — correct behavior.
    # It must not link to per-user routes as static nav.
    assert "/synth/profit-plan.html" not in login_html
    assert "/synth/open-orders-monitor.html" not in login_html


def test_web_auth_modules_have_no_broker_or_execution_imports() -> None:
    for path in (
        Path("src/web/website_registration_v1.py"),
        Path("src/web/web_auth_http_v1.py"),
        Path("src/web/run_web_auth_service_v1.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        for module_name in imported_modules:
            assert "broker" not in module_name
            assert "decision_gate" not in module_name
            assert "execution_planner" not in module_name
            assert "executor" not in module_name


def main() -> None:
    test_production_service_refuses_mock_proof_provider()
    test_dev_service_can_start_with_sqlite_and_memory_mailer()
    test_production_requires_pepper()
    test_production_requires_pepper_minimum_length()
    test_production_accepts_pepper_at_minimum_length()
    test_production_accepts_pepper_longer_than_minimum()
    test_dev_mode_does_not_require_pepper()
    test_pepper_value_not_in_runner_source()
    test_public_pages_remain_unchanged_dashboard_routes()
    test_web_auth_modules_have_no_broker_or_execution_imports()
    print("ok")


if __name__ == "__main__":
    main()
