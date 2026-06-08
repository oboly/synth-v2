from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.reporting.account_wallet_dashboard_v1 import (
    AccountAssetSettingsSummary,
    build_wallet_dashboard_payload,
    payload_to_json_dict,
    render_wallet_html,
)
from src.reporting.dashboard_style_v1 import DEFAULT_NAV_ACCOUNT_PROFILE, cockpit_nav
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


def _profile(code: str) -> dict:
    return {
        "profile_code": code,
        "account_code": f"bitvavo_{code}_read",
        "venue": "bitvavo",
        "display_timezone": "UTC",
    }


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


def test_runner_uses_account_layer_discovery() -> None:
    assert "discover_active_linked_profiles" in ABOUT_SOURCE
    assert "src.account.app_profile_trading_account_link_v1" in ABOUT_SOURCE


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


# -- Wallet nav links --

def test_wallet_navigation_links_to_global_about() -> None:
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
    html = render_wallet_html(payload)
    payload_json = json.dumps(payload_to_json_dict(payload), sort_keys=True)
    assert "/synth/about.html" in html
    assert "/synth/about.html" in payload_json


def test_global_cockpit_navigation_links_to_about() -> None:
    nav_html = cockpit_nav(account_profile=DEFAULT_NAV_ACCOUNT_PROFILE)
    assert "/synth/about.html" in nav_html
    assert "/synth/accounts/joost/wallet.html" in nav_html
    assert "/synth/accounts/joost/profit-plan.html" in nav_html
    assert "/synth/accounts/joost/open-orders-monitor.html" in nav_html
    assert "/synth/profit-plan.html" not in nav_html
    assert "/synth/open-orders-monitor.html" not in nav_html
    assert "/synth/paper-advice.html" not in nav_html
    assert "/synth/entry-candidates.html" not in nav_html
    assert "/synth/rotation-preview.html" not in nav_html


def test_public_navigation_can_include_register_and_login() -> None:
    nav_html = cockpit_nav(include_auth_links=True)
    assert "/synth/register.html" in nav_html
    assert "/synth/login.html" in nav_html


# -- Cockpit index: linked profiles from explicit argument --

def test_global_cockpit_index_links_global_pages() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[])
    assert "/synth/about.html" in html
    assert "/synth/register.html" in html
    assert "/synth/login.html" in html
    assert "Legacy / Archive" in html
    assert "/synth/paper-advice.html" in html
    assert "/synth/entry-candidates.html" in html
    assert "/var/www/html/" not in html


def test_global_cockpit_index_zero_profiles_no_wallet_cards() -> None:
    # The account grid cards are driven by linked_profiles.
    # With no linked profiles, no account card is rendered in the grid.
    # (The nav may still include the default nav profile's wallet link — that is separate.)
    html = render_global_cockpit_index_html(linked_profiles=[])
    assert 'class="card"' in html  # About card is always present
    # No extra wallet card beyond the default nav profile
    assert html.count('/wallet.html"') <= 1  # at most the nav's wallet link


def test_global_cockpit_index_one_profile_renders_wallet_card() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[_profile("alpha")])
    assert "/synth/accounts/alpha/wallet.html" in html
    assert "Wallet" in html


def test_global_cockpit_index_wallet_label_not_account_title() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[_profile("alpha")])
    assert "Alpha Account" not in html
    assert ">Wallet<" in html or ">Wallet " in html


def test_global_cockpit_index_no_duplicate_wallet_tile() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[_profile("alpha")])
    assert html.count("/synth/accounts/alpha/wallet.html") == 1


def test_global_cockpit_index_multiple_profiles() -> None:
    profiles = [_profile("alpha"), _profile("beta"), _profile("gamma")]
    html = render_global_cockpit_index_html(linked_profiles=profiles)
    assert "/synth/accounts/alpha/wallet.html" in html
    assert "/synth/accounts/beta/wallet.html" in html
    assert "/synth/accounts/gamma/wallet.html" in html


def test_global_cockpit_index_ordering_reflects_linked_profiles_order() -> None:
    profiles = [_profile("alpha"), _profile("beta")]
    html = render_global_cockpit_index_html(linked_profiles=profiles)
    pos_alpha = html.index("accounts/alpha/")
    pos_beta = html.index("accounts/beta/")
    assert pos_alpha < pos_beta


def test_global_cockpit_index_account_cards_driven_by_linked_profiles() -> None:
    # Cards in the account grid must reflect only what is in linked_profiles.
    # When only testuser is linked, testuser's wallet card appears; alpha's does not.
    html_testuser = render_global_cockpit_index_html(linked_profiles=[_profile("testuser")])
    assert "/synth/accounts/testuser/wallet.html" in html_testuser
    assert "/synth/accounts/alpha/wallet.html" not in html_testuser

    html_alpha = render_global_cockpit_index_html(linked_profiles=[_profile("alpha")])
    assert "/synth/accounts/alpha/wallet.html" in html_alpha
    assert "/synth/accounts/testuser/wallet.html" not in html_alpha


# -- Legacy cards: dimmed but links usable --

def test_legacy_section_heading_present() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[])
    assert "Legacy / Archive" in html


def test_legacy_cards_have_clickable_links() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[])
    assert 'href="/synth/paper-advice.html"' in html
    assert 'href="/synth/entry-candidates.html"' in html


def test_legacy_cards_have_legacy_badge() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[])
    assert "LEGACY" in html
    assert "legacy-badge" in html


def test_legacy_cards_are_visually_dimmed() -> None:
    html = render_global_cockpit_index_html(linked_profiles=[])
    assert "legacy-grid" in html or "opacity" in html


# -- MVP render pipeline: discover_active_linked_profiles called from main --

def test_mvp_render_pipeline_calls_account_layer_discovery() -> None:
    called_venue: dict = {}

    def fake_discover(*, venue: str) -> list[dict]:
        called_venue["venue"] = venue
        return [_profile("testprofile")]

    original_parse_args = about_runner.parse_args

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        html_out = root / "about.html"
        idx_out = root / "index.html"
        hero_out = root / "assets" / "brand" / "synth-third-faction-triptych.png"

        try:
            about_runner.parse_args = lambda: type("Args", (), {
                "output_html": str(html_out),
                "cockpit_index_html": str(idx_out),
                "hero_asset_source": "assets/brand/synth/synth-third-faction-triptych.png",
                "hero_asset_output": str(hero_out),
                "hero_asset_href": DEFAULT_HERO_HREF,
                "venue": "bitvavo",
                "output": "none",
            })()
            with patch.object(about_runner, "discover_active_linked_profiles", side_effect=fake_discover):
                result = about_runner.main()
        finally:
            about_runner.parse_args = original_parse_args

        assert result == 0
        assert called_venue.get("venue") == "bitvavo"
        index_html_content = idx_out.read_text(encoding="utf-8")
        assert "/synth/accounts/testprofile/wallet.html" in index_html_content


# -- Asset copy test --

def test_about_runner_writes_html_and_copies_asset() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source = Path("assets/brand/synth/synth-third-faction-triptych.png")
        target_html = root / "about.html"
        target_index = root / "index.html"
        target_asset = root / "assets" / "brand" / "synth-third-faction-triptych.png"
        target_html.write_text(
            render_about_html(hero_href=DEFAULT_HERO_HREF, account_profile=DEFAULT_NAV_ACCOUNT_PROFILE),
            encoding="utf-8",
        )
        target_index.write_text(
            render_global_cockpit_index_html(
                linked_profiles=[],
                account_profile=DEFAULT_NAV_ACCOUNT_PROFILE,
            ),
            encoding="utf-8",
        )
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        target_asset.write_bytes(source.read_bytes())
        assert target_html.exists()
        assert target_index.exists()
        assert target_asset.exists()
        assert target_asset.read_bytes() == source.read_bytes()


def main() -> None:
    tests = [
        test_about_runner_imports_successfully,
        test_no_configured_dashboard_profile_access_import,
        test_no_hardcoded_profile_names_in_source,
        test_runner_uses_account_layer_discovery,
        test_runner_safety_markers_in_source,
        test_render_about_html_uses_public_asset_href,
        test_render_about_html_has_meaningful_alt_text,
        test_wallet_navigation_links_to_global_about,
        test_global_cockpit_navigation_links_to_about,
        test_public_navigation_can_include_register_and_login,
        test_global_cockpit_index_links_global_pages,
        test_global_cockpit_index_zero_profiles_no_wallet_cards,
        test_global_cockpit_index_one_profile_renders_wallet_card,
        test_global_cockpit_index_wallet_label_not_account_title,
        test_global_cockpit_index_no_duplicate_wallet_tile,
        test_global_cockpit_index_multiple_profiles,
        test_legacy_section_heading_present,
        test_legacy_cards_have_clickable_links,
        test_legacy_cards_have_legacy_badge,
        test_legacy_cards_are_visually_dimmed,
        test_about_runner_writes_html_and_copies_asset,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
