from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

from src.web.run_web_auth_service_v1 import build_service, parse_args
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
        args = parse_args()
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
            args = parse_args()
            args.database = "sqlite"
            args.sqlite_path = str(sqlite_path)
            service = build_service(args)
            assert service.base_url == "https://synth.example"
            assert sqlite_path.exists()
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_public_pages_remain_unchanged_dashboard_routes() -> None:
    register_html = render_register_page()
    login_html = render_login_page()
    for html in (register_html, login_html):
        assert "/synth/accounts/" not in html
        assert "/synth/profit-plan.html" not in html
        assert "/synth/open-orders-monitor.html" not in html


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
    test_public_pages_remain_unchanged_dashboard_routes()
    test_web_auth_modules_have_no_broker_or_execution_imports()
    print("ok")


if __name__ == "__main__":
    main()
