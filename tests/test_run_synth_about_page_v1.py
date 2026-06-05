from __future__ import annotations

import json
import tempfile
from pathlib import Path

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


def _settings() -> AccountAssetSettingsSummary:
    return AccountAssetSettingsSummary(
        visible=0,
        candidate_enabled=0,
        proposal_enabled=0,
        hidden=0,
        disabled=0,
    )


def test_render_about_html_uses_public_asset_href() -> None:
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    assert 'src="/synth/assets/brand/synth-third-faction-triptych.png"' in html or "src='/synth/assets/brand/synth-third-faction-triptych.png'" in html
    assert "/var/www/html/" not in html
    assert "The Observer" in html
    assert "The Balancer" in html
    assert "The Weaver" in html
    assert "The Third Faction" in html
    assert "Cybernetic Zen Master with Market Data" in html


def test_render_about_html_has_meaningful_alt_text() -> None:
    html = render_about_html(hero_href=DEFAULT_HERO_HREF)
    assert "alt=" in html
    assert "triptych artwork" in html


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


def test_global_cockpit_index_links_global_pages_and_configured_account() -> None:
    html = render_global_cockpit_index_html(account_profile=DEFAULT_NAV_ACCOUNT_PROFILE)
    assert "/synth/about.html" in html
    assert "/synth/accounts/joost/wallet.html" in html
    assert "/synth/accounts/joost/profit-plan.html" in html
    assert "/synth/accounts/joost/open-orders-monitor.html" in html
    assert "/synth/profit-plan.html" not in html
    assert "/synth/open-orders-monitor.html" not in html
    assert "/synth/rotation-preview.html" not in html
    assert "Legacy / Archive" in html
    assert "/synth/paper-advice.html" in html
    assert "/synth/entry-candidates.html" in html
    assert "/var/www/html/" not in html


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
            render_global_cockpit_index_html(account_profile=DEFAULT_NAV_ACCOUNT_PROFILE),
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
        test_render_about_html_uses_public_asset_href,
        test_render_about_html_has_meaningful_alt_text,
        test_wallet_navigation_links_to_global_about,
        test_global_cockpit_navigation_links_to_about,
        test_global_cockpit_index_links_global_pages_and_configured_account,
        test_about_runner_writes_html_and_copies_asset,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
