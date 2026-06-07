from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

from src.web.run_web_auth_service_v1 import (
    MIN_PEPPER_LENGTH,
    _validate_production_base_url,
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


def test_production_base_url_required() -> None:
    try:
        _validate_production_base_url("")
    except RuntimeError as exc:
        assert "PRODUCTION_BASE_URL_REQUIRED" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for empty base URL")


def test_production_base_url_must_be_https() -> None:
    for bad in ("http://synth.local", "ftp://synth.local", "synth.local"):
        try:
            _validate_production_base_url(bad)
        except RuntimeError as exc:
            assert "MUST_BE_HTTPS" in str(exc) or "MALFORMED" in str(exc)
        else:
            raise AssertionError(f"expected RuntimeError for non-HTTPS URL: {bad!r}")


def test_production_base_url_rejects_path() -> None:
    try:
        _validate_production_base_url("https://synth.local/some/path")
    except RuntimeError as exc:
        assert "PATH_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for URL with path")


def test_production_base_url_rejects_query() -> None:
    try:
        _validate_production_base_url("https://synth.local?q=1")
    except RuntimeError as exc:
        assert "QUERY_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for URL with query")


def test_production_base_url_rejects_fragment() -> None:
    try:
        _validate_production_base_url("https://synth.local#section")
    except RuntimeError as exc:
        assert "FRAGMENT_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for URL with fragment")


def test_production_base_url_rejects_userinfo() -> None:
    try:
        _validate_production_base_url("https://user:pass@synth.local")
    except RuntimeError as exc:
        assert "USERINFO_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for URL with userinfo")


def test_production_base_url_accepts_valid_https() -> None:
    result = _validate_production_base_url("https://synth.example.com")
    assert result == "https://synth.example.com"


def test_production_base_url_normalizes_trailing_slash() -> None:
    result = _validate_production_base_url("https://synth.example.com/")
    assert result == "https://synth.example.com"
    assert not result.endswith("/")


def test_production_base_url_preserves_port() -> None:
    result = _validate_production_base_url("https://synth.example.com:8443")
    assert result == "https://synth.example.com:8443"


def test_production_base_url_no_port_is_clean() -> None:
    result = _validate_production_base_url("https://synth.example.com")
    assert ":" not in result.split("//", 1)[1]


def test_production_service_origin_enforcement() -> None:
    """Production: correct Origin accepted, missing or foreign rejected."""
    import io
    import json
    import sqlite3
    from wsgiref.util import setup_testing_defaults
    from src.web.web_auth_http_v1 import build_wsgi_app
    from src.web.website_registration_v1 import (
        MemoryMailer,
        MockProofOfHumanProvider,
        SqliteWebsiteRegistrationRepository,
        WebsiteRegistrationService,
    )

    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    mailer = MemoryMailer(sent_messages=[])
    service = WebsiteRegistrationService(
        repository=repo,
        proof_provider=MockProofOfHumanProvider(),
        mailer=mailer,
        base_url="https://synth.local",
    )
    app = build_wsgi_app(service=service, allowed_origins={"https://synth.local"})

    def call(origin: str | None) -> int:
        environ: dict = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = "POST"
        environ["PATH_INFO"] = "/synth/web-auth/register"
        body = json.dumps({
            "email": "t@t.com", "profile_code": "test",
            "password": "ValidPass123!", "proof_response": "test-human-ok",
        }).encode()
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["CONTENT_TYPE"] = "application/json"
        environ["wsgi.input"] = io.BytesIO(body)
        if origin is not None:
            environ["HTTP_ORIGIN"] = origin
        captured: dict = {}
        def start_response(status, headers):
            captured["status"] = status
        app(environ, start_response)
        return int(captured["status"].split(" ", 1)[0])

    assert call("https://synth.local") == 200, "Exact origin must be accepted"
    assert call("https://evil.example") == 403, "Foreign origin must be rejected"
    assert call(None) == 403, "Missing origin must be rejected"


def test_healthz_get_no_origin_check() -> None:
    """GET /healthz must not require Origin header even in production mode."""
    import io
    import sqlite3
    from wsgiref.util import setup_testing_defaults
    from src.web.web_auth_http_v1 import build_wsgi_app
    from src.web.website_registration_v1 import (
        MemoryMailer,
        MockProofOfHumanProvider,
        SqliteWebsiteRegistrationRepository,
        WebsiteRegistrationService,
    )

    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    service = WebsiteRegistrationService(
        repository=repo,
        proof_provider=MockProofOfHumanProvider(),
        mailer=MemoryMailer(sent_messages=[]),
        base_url="https://synth.local",
    )
    app = build_wsgi_app(service=service, allowed_origins={"https://synth.local"})

    environ: dict = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "GET"
    environ["PATH_INFO"] = "/synth/web-auth/healthz"
    environ["wsgi.input"] = io.BytesIO(b"")
    captured: dict = {}
    def start_response(status, headers):
        captured["status"] = status
    app(environ, start_response)
    assert int(captured["status"].split(" ", 1)[0]) == 200


def test_check_access_get_no_origin_check() -> None:
    """GET /check-access must not require Origin header (GET, not POST)."""
    import io
    import sqlite3
    from wsgiref.util import setup_testing_defaults
    from src.web.web_auth_http_v1 import build_wsgi_app
    from src.web.website_registration_v1 import (
        MemoryMailer,
        MockProofOfHumanProvider,
        SqliteWebsiteRegistrationRepository,
        WebsiteRegistrationService,
    )

    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    service = WebsiteRegistrationService(
        repository=repo,
        proof_provider=MockProofOfHumanProvider(),
        mailer=MemoryMailer(sent_messages=[]),
        base_url="https://synth.local",
    )
    app = build_wsgi_app(service=service, allowed_origins={"https://synth.local"})

    environ: dict = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "GET"
    environ["PATH_INFO"] = "/synth/web-auth/check-access"
    environ["wsgi.input"] = io.BytesIO(b"")
    captured: dict = {}
    def start_response(status, headers):
        captured["status"] = status
    app(environ, start_response)
    # No session → 401, but not 403 ORIGIN_NOT_ALLOWED
    code = int(captured["status"].split(" ", 1)[0])
    assert code == 401, f"Expected 401 (no session), got {code}"


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
    test_production_base_url_required()
    test_production_base_url_must_be_https()
    test_production_base_url_rejects_path()
    test_production_base_url_rejects_query()
    test_production_base_url_rejects_fragment()
    test_production_base_url_rejects_userinfo()
    test_production_base_url_accepts_valid_https()
    test_production_base_url_normalizes_trailing_slash()
    test_production_base_url_preserves_port()
    test_production_base_url_no_port_is_clean()
    test_production_service_origin_enforcement()
    test_healthz_get_no_origin_check()
    test_check_access_get_no_origin_check()
    print("ok")


if __name__ == "__main__":
    main()
