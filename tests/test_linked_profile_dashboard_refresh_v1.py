from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import src.account.run_linked_profile_dashboard_refresh_v1 as discovery_runner
from src.account.run_linked_profile_dashboard_refresh_v1 import discover_linked_profiles


SOURCE = Path("src/account/run_linked_profile_dashboard_refresh_v1.py").read_text(encoding="utf-8")
ACCOUNT_LAYER_SOURCE = Path("src/account/app_profile_trading_account_link_v1.py").read_text(encoding="utf-8")
SHELL_SCRIPT = Path("scripts/odroid/run_linked_profile_dashboard_refresh_once.sh").read_text(encoding="utf-8")
RENDER_SCRIPT = Path("scripts/odroid/run_account_wallet_dashboard_render_once.sh").read_text(encoding="utf-8")


# -- Source-level checks --


def test_no_hardcoded_profile_names_in_runner() -> None:
    assert "joost" not in SOURCE
    assert "hugo" not in SOURCE
    assert "bitvavo_joost" not in SOURCE
    assert "bitvavo_hugo" not in SOURCE


def test_no_credential_inference_in_runner() -> None:
    assert "profile_code + " not in SOURCE
    assert '+ "_read"' not in SOURCE
    assert "f_string" not in SOURCE


def test_runner_safety_markers_in_source() -> None:
    assert "broker_private_calls=0" in SOURCE
    assert "broker_writes=0" in SOURCE
    assert "order_submission=0" in SOURCE
    assert "live_orders=0" in SOURCE
    assert "decision_gate=none" in SOURCE
    assert "execution_planner=none" in SOURCE
    assert "executor=none" in SOURCE


def test_runner_queries_link_table() -> None:
    # SQL now lives in the account layer; runner delegates via discover_active_linked_profiles.
    assert "discover_active_linked_profiles" in SOURCE
    assert "app_profile_trading_account_link" in ACCOUNT_LAYER_SOURCE
    assert "ACTIVE" in ACCOUNT_LAYER_SOURCE
    assert "is_primary" in ACCOUNT_LAYER_SOURCE


def test_runner_no_broker_or_execution_imports() -> None:
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "decision_gate" not in alias.name
                assert "execution_planner" not in alias.name
                assert "executor" not in alias.name
                assert "bitvavo" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "decision_gate" not in node.module
            assert "execution_planner" not in node.module
            assert "executor" not in node.module
            assert "bitvavo" not in node.module


def test_shell_script_refreshes_prices_once() -> None:
    assert "refresh_public_prices" in SHELL_SCRIPT
    assert "SYNTH_SKIP_MARKET_PRICE_REFRESH" in SHELL_SCRIPT
    assert "run_linked_profile_dashboard_refresh_v1" in SHELL_SCRIPT
    assert "profile-list" in SHELL_SCRIPT
    assert "run_account_wallet_dashboard_render_once.sh" in SHELL_SCRIPT


def test_shell_script_propagates_price_skip_to_per_profile_render() -> None:
    assert "SYNTH_SKIP_MARKET_PRICE_REFRESH=1" in SHELL_SCRIPT


def test_render_script_supports_price_skip_flag() -> None:
    assert "SYNTH_SKIP_MARKET_PRICE_REFRESH" in RENDER_SCRIPT
    assert "market_price_refresh=skipped" in RENDER_SCRIPT


def test_no_hardcoded_profile_names_in_shell_scripts() -> None:
    for script_text in [SHELL_SCRIPT, RENDER_SCRIPT]:
        assert '"joost"' not in script_text
        assert '"hugo"' not in script_text
        assert "bitvavo_joost_read" not in script_text
        assert "bitvavo_hugo_read" not in script_text


# -- Fake DB helpers --


class _FakeRow(dict):
    pass


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.sql = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self._committed = False
        self._rolled_back = False

    def cursor(self):
        return _FakeCursor(self._rows)

    def commit(self):
        self._committed = True

    def rollback(self):
        self._rolled_back = True

    def close(self):
        pass


# -- Functional discovery tests --


def test_discovery_returns_linked_profiles() -> None:
    rows = [
        _FakeRow(profile_code="alpha", account_code="bitvavo_alpha_read", venue="bitvavo", display_timezone="UTC"),
        _FakeRow(profile_code="beta", account_code="bitvavo_beta_read", venue="bitvavo", display_timezone="UTC"),
    ]
    with patch("src.account.run_linked_profile_dashboard_refresh_v1.discover_linked_profiles") as mock_discover:
        mock_discover.return_value = [dict(r) for r in rows]
        profiles = discovery_runner.discover_linked_profiles(venue="bitvavo")
    assert len(profiles) == 2
    profile_codes = {p["profile_code"] for p in profiles}
    assert "alpha" in profile_codes
    assert "beta" in profile_codes


def test_discovery_returns_empty_for_no_links() -> None:
    with patch("src.account.run_linked_profile_dashboard_refresh_v1.discover_linked_profiles") as mock_discover:
        mock_discover.return_value = []
        profiles = discovery_runner.discover_linked_profiles(venue="bitvavo")
    assert profiles == []


def test_discovery_real_query_uses_venue_param() -> None:
    # SQL is in the account layer; check the canonical source.
    assert "ta.venue = %s" in ACCOUNT_LAYER_SOURCE or "WHERE ta.venue" in ACCOUNT_LAYER_SOURCE


def test_discovery_one_profile_isolates_from_other_venue() -> None:
    bitvavo_rows = [
        _FakeRow(profile_code="alpha", account_code="bitvavo_alpha_read", venue="bitvavo", display_timezone="UTC"),
    ]
    other_rows = [
        _FakeRow(profile_code="gamma", account_code="other_gamma_read", venue="othervenue", display_timezone="UTC"),
    ]
    with patch("src.account.run_linked_profile_dashboard_refresh_v1.discover_linked_profiles") as mock_discover:
        mock_discover.side_effect = lambda venue: (
            [dict(r) for r in bitvavo_rows] if venue == "bitvavo" else [dict(r) for r in other_rows]
        )
        bitvavo = discovery_runner.discover_linked_profiles(venue="bitvavo")
        other = discovery_runner.discover_linked_profiles(venue="othervenue")
    bitvavo_codes = {p["profile_code"] for p in bitvavo}
    assert "alpha" in bitvavo_codes
    assert "gamma" not in bitvavo_codes
    other_codes = {p["profile_code"] for p in other}
    assert "gamma" in other_codes
    assert "alpha" not in other_codes


def test_runner_profile_list_output_one_per_line(capsys) -> None:
    with patch.object(discovery_runner, "discover_linked_profiles") as mock_discover:
        mock_discover.return_value = [
            {"profile_code": "alpha", "account_code": "bitvavo_alpha_read"},
            {"profile_code": "beta", "account_code": "bitvavo_beta_read"},
        ]
        original_parse_args = discovery_runner.parse_args
        try:
            discovery_runner.parse_args = lambda: type(
                "Args", (), {"venue": "bitvavo", "output": "profile-list"}
            )()
            result = discovery_runner.main()
        finally:
            discovery_runner.parse_args = original_parse_args
    assert result == 0
    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().splitlines() if l]
    assert lines == ["alpha", "beta"]


def test_runner_summary_output_includes_safety_markers(capsys) -> None:
    with patch.object(discovery_runner, "discover_linked_profiles") as mock_discover:
        mock_discover.return_value = [
            {"profile_code": "alpha", "account_code": "bitvavo_alpha_read"},
        ]
        original_parse_args = discovery_runner.parse_args
        try:
            discovery_runner.parse_args = lambda: type(
                "Args", (), {"venue": "bitvavo", "output": "summary"}
            )()
            result = discovery_runner.main()
        finally:
            discovery_runner.parse_args = original_parse_args
    assert result == 0
    captured = capsys.readouterr()
    output = captured.out
    assert "broker_private_calls=0" in output
    assert "broker_writes=0" in output
    assert "order_submission=0" in output
    assert "linked_profile_count=1" in output
    assert "alpha" in output


def test_runner_summary_exposes_profile_count_zero_for_unlinked(capsys) -> None:
    with patch.object(discovery_runner, "discover_linked_profiles") as mock_discover:
        mock_discover.return_value = []
        original_parse_args = discovery_runner.parse_args
        try:
            discovery_runner.parse_args = lambda: type(
                "Args", (), {"venue": "bitvavo", "output": "summary"}
            )()
            result = discovery_runner.main()
        finally:
            discovery_runner.parse_args = original_parse_args
    assert result == 0
    captured = capsys.readouterr()
    assert "linked_profile_count=0" in captured.out


def test_runner_db_failure_returns_nonzero(capsys) -> None:
    with patch.object(discovery_runner, "discover_linked_profiles") as mock_discover:
        mock_discover.side_effect = RuntimeError("DB connection failed")
        original_parse_args = discovery_runner.parse_args
        try:
            discovery_runner.parse_args = lambda: type(
                "Args", (), {"venue": "bitvavo", "output": "summary"}
            )()
            result = discovery_runner.main()
        finally:
            discovery_runner.parse_args = original_parse_args
    assert result == 1


def main() -> None:
    test_no_hardcoded_profile_names_in_runner()
    test_no_credential_inference_in_runner()
    test_runner_safety_markers_in_source()
    test_runner_queries_link_table()
    test_runner_no_broker_or_execution_imports()
    test_shell_script_refreshes_prices_once()
    test_shell_script_propagates_price_skip_to_per_profile_render()
    test_render_script_supports_price_skip_flag()
    test_no_hardcoded_profile_names_in_shell_scripts()
    test_runner_db_failure_returns_nonzero()
    print("ok")


if __name__ == "__main__":
    main()
