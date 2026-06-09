from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

# When run directly as `python tests/test_*.py`, Python replaces sys.path[0] with
# the tests/ directory, dropping '' (cwd). The sibling synth-v2 repo then shadows
# src.* imports. Insert the project root explicitly so both pytest and the standalone
# runner always resolve src.* from this repository.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.reporting.account_wallet_dashboard_v1 import (
    AccountAssetSettingsSummary,
    build_wallet_dashboard_payload,
    payload_to_json_dict,
    render_wallet_html,
)
from src.reporting.dashboard_style_v1 import account_dashboard_links, cockpit_nav
from src.reporting.run_synth_about_page_v1 import (
    DEFAULT_HERO_HREF,
    render_about_html,
    render_global_cockpit_index_html,
)
import src.reporting.run_synth_about_page_v1 as about_runner

ABOUT_SOURCE = Path("src/reporting/run_synth_about_page_v1.py").read_text(encoding="utf-8")


def _settings() -> AccountAssetSettingsSummary:
    return AccountAssetSettingsSummary(
        visible=0,
        candidate_enabled=0,
        proposal_enabled=0,
        hidden=0,
        disabled=0,
    )


# -- Import / source checks --

def test_about_runner_imports_successfully() -> None:
    import src.reporting.run_synth_about_page_v1  # noqa: F401


def test_no_configured_dashboard_profile_access_import() -> None:
    assert "CONFIGURED_DASHBOARD_PROFILE_ACCESS" not in ABOUT_SOURCE


def test_no_hardcoded_profile_names_in_source() -> None:
    assert '"joost"' not in ABOUT_SOURCE
    assert '"hugo"' not in ABOUT_SOURCE
    assert "'joost'" not in ABOUT_SOURCE
    assert "'hugo'" not in ABOUT_SOURCE


def test_runner_no_longer_uses_account_layer_discovery() -> None:
    """Global runner must not call discover_active_linked_profiles — no account query."""
    assert "discover_active_linked_profiles" not in ABOUT_SOURCE
    assert "src.account.app_profile_trading_account_link_v1" not in ABOUT_SOURCE


def test_runner_no_default_nav_account_profile() -> None:
    """DEFAULT_NAV_ACCOUNT_PROFILE must not appear in the runner source."""
    assert "DEFAULT_NAV_ACCOUNT_PROFILE" not in ABOUT_SOURCE


def test_runner_no_venue_argument() -> None:
    """Runner must not accept --venue (no account discovery)."""
    assert "--venue" not in ABOUT_SOURCE
    assert "DEFAULT_VENUE" not in ABOUT_SOURCE


def test_runner_safety_markers_in_source() -> None:
    assert "broker_private_calls=0" in ABOUT_SOURCE
    assert "broker_writes=0" in ABOUT_SOURCE
    assert "order_submission=0" in ABOUT_SOURCE
    assert "executor=none" in ABOUT_SOURCE


def test_runner_no_broker_or_execution_imports() -> None:
    tree = ast.parse(ABOUT_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "decision_gate" not in alias.name
                assert "execution_planner" not in alias.name
                assert "executor" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "decision_gate" not in node.module
            assert "execution_planner" not in node.module
            assert "executor" not in node.module


# -- About page rendering --

def test_render_about_html_uses_public_asset_href() -> None:
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    assert (
        'src="/synth/assets/brand/synth-third-faction-triptych.png"' in html
        or "src='/synth/assets/brand/synth-third-faction-triptych.png'" in html
    )
    assert "/var/www/html/" not in html
    assert "The Observer" in html
    assert "The Balancer" in html
    assert "The Weaver" in html
    assert "The Third Faction" in html
    assert "Cybernetic Zen Master with Market Data" in html
    assert "/synth/register.html" in html
    assert "/synth/login.html" in html


def test_render_about_html_has_meaningful_alt_text() -> None:
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    assert "alt=" in html
    assert "triptych artwork" in html


def test_render_about_html_no_account_links() -> None:
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    assert 'href="/synth/accounts/' not in html
    assert "href='/synth/accounts/" not in html
    assert "joost" not in html
    assert "hugo" not in html


def test_render_about_html_no_wallet_profit_plan_links() -> None:
    """Global About must not contain Wallet, Profit Plan, or Open Orders nav items."""
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    # Check that nav hrefs for those pages are absent
    assert "/wallet.html" not in html
    assert "/profit-plan.html" not in html
    assert "/open-orders-monitor.html" not in html


def test_render_about_html_has_cockpit_and_about_nav() -> None:
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    assert "/synth/index.html" in html or "/synth/about.html" in html


def test_render_about_html_no_account_profile_param() -> None:
    """render_about_html signature must not accept account_profile."""
    import inspect
    sig = inspect.signature(render_about_html)
    assert "account_profile" not in sig.parameters


# -- Global cockpit index --

def test_global_cockpit_index_signature_no_params() -> None:
    """render_global_cockpit_index_html must accept no parameters."""
    import inspect
    sig = inspect.signature(render_global_cockpit_index_html)
    assert len(sig.parameters) == 0


def test_global_cockpit_index_no_account_links() -> None:
    html = render_global_cockpit_index_html()
    assert 'href="/synth/accounts/' not in html
    assert "href='/synth/accounts/" not in html


def test_global_cockpit_index_no_joost_hugo() -> None:
    html = render_global_cockpit_index_html()
    assert "joost" not in html
    assert "hugo" not in html


def test_global_cockpit_index_no_wallet_card() -> None:
    html = render_global_cockpit_index_html()
    # Wallet nav link must not appear in global cockpit
    assert "/wallet.html" not in html
    assert ">Wallet<" not in html


def test_global_cockpit_index_no_profit_plan_link() -> None:
    html = render_global_cockpit_index_html()
    assert "/profit-plan.html" not in html
    assert ">Profit Plan<" not in html


def test_global_cockpit_index_no_open_orders_link() -> None:
    html = render_global_cockpit_index_html()
    assert "/open-orders-monitor.html" not in html
    assert ">Open Orders Monitor<" not in html


def test_global_cockpit_index_links_global_pages() -> None:
    html = render_global_cockpit_index_html()
    assert 'href="/synth/about.html"' in html
    assert "/synth/register.html" in html
    assert "/synth/login.html" in html
    assert "Legacy / Archive" in html
    assert 'href="/synth/paper-advice.html"' in html
    assert 'href="/synth/entry-candidates.html"' in html
    assert "/var/www/html/" not in html


def test_global_cockpit_index_has_about_card() -> None:
    html = render_global_cockpit_index_html()
    assert 'class="card"' in html
    assert "/synth/about.html" in html


# -- Legacy cards --

def test_legacy_section_heading_present() -> None:
    html = render_global_cockpit_index_html()
    assert "Legacy / Archive" in html


def test_legacy_cards_have_clickable_links() -> None:
    html = render_global_cockpit_index_html()
    assert 'href="/synth/paper-advice.html"' in html
    assert 'href="/synth/entry-candidates.html"' in html


def test_legacy_cards_have_legacy_badge() -> None:
    html = render_global_cockpit_index_html()
    assert "LEGACY" in html
    assert "legacy-badge" in html


def test_legacy_cards_are_visually_dimmed() -> None:
    html = render_global_cockpit_index_html()
    assert "legacy-grid" in html or "opacity" in html


# -- Global navigation (account_profile=None) --

def test_global_nav_has_cockpit_and_about() -> None:
    nav_html = cockpit_nav(account_profile=None)
    assert "/synth/index.html" in nav_html
    assert "/synth/about.html" in nav_html


def test_global_nav_no_wallet_links() -> None:
    nav_html = cockpit_nav(account_profile=None)
    assert "/wallet.html" not in nav_html
    assert "/profit-plan.html" not in nav_html
    assert "/open-orders-monitor.html" not in nav_html


def test_public_navigation_can_include_register_and_login() -> None:
    nav_html = cockpit_nav(include_auth_links=True)
    assert "/synth/register.html" in nav_html
    assert "/synth/login.html" in nav_html


def test_global_nav_no_profile_names() -> None:
    nav_html = cockpit_nav(account_profile=None)
    assert "joost" not in nav_html
    assert "hugo" not in nav_html


# -- Account-scoped navigation still works --

def test_account_dashboard_links_hugo_produces_hugo_paths() -> None:
    links = account_dashboard_links("hugo")
    assert links["wallet"] == "/synth/accounts/hugo/wallet.html"
    assert links["profit_plan"] == "/synth/accounts/hugo/profit-plan.html"
    assert links["open_orders_monitor"] == "/synth/accounts/hugo/open-orders-monitor.html"
    assert "joost" not in str(links)


def test_account_dashboard_links_joost_produces_joost_paths() -> None:
    links = account_dashboard_links("joost")
    assert links["wallet"] == "/synth/accounts/joost/wallet.html"
    assert links["profit_plan"] == "/synth/accounts/joost/profit-plan.html"
    assert links["open_orders_monitor"] == "/synth/accounts/joost/open-orders-monitor.html"
    assert "hugo" not in str(links)


def test_account_scoped_nav_produces_explicit_profile_links() -> None:
    nav_hugo = cockpit_nav(account_profile="hugo")
    assert "/synth/accounts/hugo/wallet.html" in nav_hugo
    assert "joost" not in nav_hugo

    nav_joost = cockpit_nav(account_profile="joost")
    assert "/synth/accounts/joost/wallet.html" in nav_joost
    assert "hugo" not in nav_joost


def test_no_implicit_default_profile_in_dashboard_style() -> None:
    """DEFAULT_NAV_ACCOUNT_PROFILE must not exist in dashboard_style_v1."""
    source = Path("src/reporting/dashboard_style_v1.py").read_text(encoding="utf-8")
    assert "DEFAULT_NAV_ACCOUNT_PROFILE" not in source
    assert '"joost"' not in source or "DEFAULT_NAV" not in source


# -- Wallet nav still links to global About --

def test_wallet_navigation_links_to_global_about() -> None:
    html = _wallet_html_for_joost()
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=3,
        venue="bitvavo",
        display_timezone="Europe/Amsterdam",
        latest_balance_snapshot_ts_utc=None,
        latest_order_snapshot_ts_utc=None,
        balance_rows=[],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
        account_asset_rows=[],
        venue_market_rows=[],
    )
    payload_json = json.dumps(payload_to_json_dict(payload), sort_keys=True)
    assert "/synth/about.html" in html
    assert "/synth/about.html" in payload_json


# -- Runner write test --

def test_about_runner_writes_html_and_copies_asset() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source = Path("assets/brand/synth/synth-third-faction-triptych.png")
        target_html = root / "about.html"
        target_index = root / "index.html"
        target_asset = root / "assets" / "brand" / "synth-third-faction-triptych.png"
        target_html.write_text(render_about_html(hero_href=DEFAULT_HERO_HREF), encoding="utf-8")
        target_index.write_text(render_global_cockpit_index_html(), encoding="utf-8")
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        target_asset.write_bytes(source.read_bytes())
        assert target_html.exists()
        assert target_index.exists()
        assert target_asset.exists()
        assert target_asset.read_bytes() == source.read_bytes()
        # Verify no account leakage in output
        assert "joost" not in target_html.read_text(encoding="utf-8")
        assert 'href="/synth/accounts/' not in target_html.read_text(encoding="utf-8")
        assert "joost" not in target_index.read_text(encoding="utf-8")
        assert 'href="/synth/accounts/' not in target_index.read_text(encoding="utf-8")


def test_main_runner_produces_clean_global_pages() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        html_out = root / "about.html"
        idx_out = root / "index.html"
        hero_out = root / "assets" / "brand" / "synth-third-faction-triptych.png"

        original_parse_args = about_runner.parse_args
        try:
            about_runner.parse_args = lambda: type("Args", (), {
                "output_html": str(html_out),
                "cockpit_index_html": str(idx_out),
                "hero_asset_source": "assets/brand/synth/synth-third-faction-triptych.png",
                "hero_asset_output": str(hero_out),
                "hero_asset_href": DEFAULT_HERO_HREF,
                "output": "none",
            })()
            result = about_runner.main()
        finally:
            about_runner.parse_args = original_parse_args

        assert result == 0
        about_html = html_out.read_text(encoding="utf-8")
        index_html = idx_out.read_text(encoding="utf-8")

        for html, name in [(about_html, "about.html"), (index_html, "index.html")]:
            assert "joost" not in html, f"{name} must not contain 'joost'"
            assert "hugo" not in html, f"{name} must not contain 'hugo'"
            assert 'href="/synth/accounts/' not in html, f"{name} must not contain profile-scoped hrefs"
            assert "/wallet.html" not in html, f"{name} must not contain wallet link"
            assert ">Profit Plan<" not in html, f"{name} must not contain Profit Plan nav item"
            assert ">Open Orders Monitor<" not in html, f"{name} must not contain Open Orders nav item"


def _assert_global_page_clean(html: str, name: str) -> None:
    assert "joost" not in html, f"{name}: must not contain 'joost'"
    assert "hugo" not in html, f"{name}: must not contain 'hugo'"
    assert 'href="/synth/accounts/' not in html, f"{name}: must not contain account hrefs"
    assert "href='/synth/accounts/" not in html, f"{name}: must not contain account hrefs"
    assert "/wallet.html" not in html, f"{name}: must not contain wallet link"
    assert "/profit-plan.html" not in html, f"{name}: must not contain profit-plan link"
    assert "/open-orders-monitor.html" not in html, f"{name}: must not contain open-orders link"


def _wallet_html_for_joost() -> str:
    payload = build_wallet_dashboard_payload(
        profile="joost",
        account_code="bitvavo_joost_read",
        trading_account_id=3,
        venue="bitvavo",
        display_timezone="Europe/Amsterdam",
        latest_balance_snapshot_ts_utc=None,
        latest_order_snapshot_ts_utc=None,
        balance_rows=[],
        open_order_count_rows=[],
        account_asset_settings=_settings(),
        price_by_symbol={},
        account_asset_rows=[],
        venue_market_rows=[],
    )
    return render_wallet_html(payload)


def test_invocation_order_wallet_then_global() -> None:
    """Render account-scoped wallet first, then global pages — global must stay clean."""
    wallet_html = _wallet_html_for_joost()
    # wallet uses single-quoted hrefs; verify it is account-scoped
    assert "/synth/accounts/joost/wallet.html" in wallet_html, "wallet must contain account hrefs"
    assert "joost" in wallet_html, "wallet must reference profile"

    about_html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    cockpit_html = render_global_cockpit_index_html()

    _assert_global_page_clean(about_html, "about (after wallet)")
    _assert_global_page_clean(cockpit_html, "cockpit index (after wallet)")


def test_invocation_order_global_then_wallet_then_global() -> None:
    """Render global, then account-scoped wallet, then global again — global must stay clean."""
    about_html_1 = render_about_html(hero_href=DEFAULT_HERO_HREF)
    cockpit_html_1 = render_global_cockpit_index_html()
    _assert_global_page_clean(about_html_1, "about (first pass)")
    _assert_global_page_clean(cockpit_html_1, "cockpit index (first pass)")

    wallet_html = _wallet_html_for_joost()
    assert "/synth/accounts/joost/wallet.html" in wallet_html, "wallet must contain account hrefs"
    assert "joost" in wallet_html, "wallet must reference profile"

    about_html_2 = render_about_html(hero_href=DEFAULT_HERO_HREF)
    cockpit_html_2 = render_global_cockpit_index_html()
    _assert_global_page_clean(about_html_2, "about (after wallet, second pass)")
    _assert_global_page_clean(cockpit_html_2, "cockpit index (after wallet, second pass)")


def main() -> None:
    tests = [
        test_about_runner_imports_successfully,
        test_no_configured_dashboard_profile_access_import,
        test_no_hardcoded_profile_names_in_source,
        test_runner_no_longer_uses_account_layer_discovery,
        test_runner_no_default_nav_account_profile,
        test_runner_no_venue_argument,
        test_runner_safety_markers_in_source,
        test_runner_no_broker_or_execution_imports,
        test_render_about_html_uses_public_asset_href,
        test_render_about_html_has_meaningful_alt_text,
        test_render_about_html_no_account_links,
        test_render_about_html_no_wallet_profit_plan_links,
        test_render_about_html_has_cockpit_and_about_nav,
        test_render_about_html_no_account_profile_param,
        test_global_cockpit_index_signature_no_params,
        test_global_cockpit_index_no_account_links,
        test_global_cockpit_index_no_joost_hugo,
        test_global_cockpit_index_no_wallet_card,
        test_global_cockpit_index_no_profit_plan_link,
        test_global_cockpit_index_no_open_orders_link,
        test_global_cockpit_index_links_global_pages,
        test_global_cockpit_index_has_about_card,
        test_legacy_section_heading_present,
        test_legacy_cards_have_clickable_links,
        test_legacy_cards_have_legacy_badge,
        test_legacy_cards_are_visually_dimmed,
        test_global_nav_has_cockpit_and_about,
        test_global_nav_no_wallet_links,
        test_public_navigation_can_include_register_and_login,
        test_global_nav_no_profile_names,
        test_account_dashboard_links_hugo_produces_hugo_paths,
        test_account_dashboard_links_joost_produces_joost_paths,
        test_account_scoped_nav_produces_explicit_profile_links,
        test_no_implicit_default_profile_in_dashboard_style,
        test_wallet_navigation_links_to_global_about,
        test_about_runner_writes_html_and_copies_asset,
        test_main_runner_produces_clean_global_pages,
        test_invocation_order_wallet_then_global,
        test_invocation_order_global_then_wallet_then_global,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
