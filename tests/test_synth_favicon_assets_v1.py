from __future__ import annotations

import ast
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

import src.reporting.run_synth_about_page_v1 as about_page
import src.web.run_website_registration_pages_v1 as registration_pages
from src.reporting.account_wallet_dashboard_v1 import (
    AccountAssetSettingsSummary,
    OpenOrderCountRow,
    WalletDashboardPayload,
    render_wallet_html,
)
from src.reporting.dashboard_style_v1 import (
    SYNTH_FAVICON_FILENAMES,
    copy_synth_favicon_assets,
    synth_favicon_head_html,
)


ASSET_ROOT = Path("assets/brand/synth")


def _wallet_payload() -> WalletDashboardPayload:
    return WalletDashboardPayload(
        profile="joost",
        account_code="stable-ref-3",
        trading_account_id=3,
        venue="bitvavo",
        display_timezone="Europe/Amsterdam",
        generated_ts_utc=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        latest_wallet_refresh_ts_utc=None,
        freshness="FRESH",
        latest_balance_snapshot_ts_utc=None,
        latest_order_snapshot_ts_utc=None,
        market_data_warning=None,
        stale_market_data_count=0,
        missing_market_data_count=0,
        balance_count=1,
        open_order_market_count=1,
        total_open_order_count=2,
        total_estimated_portfolio_value_eur=None,
        account_asset_settings=AccountAssetSettingsSummary(
            visible=1,
            candidate_enabled=1,
            proposal_enabled=0,
            hidden=0,
            disabled=0,
        ),
        dashboard_links={
            "about": "/synth/about.html",
            "wallet": "/synth/accounts/joost/wallet.html",
            "profit_plan": "/synth/accounts/joost/profit-plan.html",
            "open_orders_monitor": "/synth/accounts/joost/open-orders-monitor.html",
        },
        balances=(),
        open_order_counts=(OpenOrderCountRow(market="WLD-EUR", order_count=2),),
        management={"visible_markets": [], "hidden_markets": [], "disabled_markets": []},
    )


def test_svg_is_valid_and_has_no_scripts_or_external_refs() -> None:
    svg_text = (ASSET_ROOT / "favicon.svg").read_text(encoding="utf-8")
    lowered = svg_text.lower()
    assert "<svg" in svg_text
    assert "<script" not in lowered
    assert "xlink:href" not in lowered
    assert "href=\"http" not in lowered
    assert "href='http" not in lowered
    assert "src=\"http" not in lowered
    assert "src='http" not in lowered


def test_png_dimensions_and_permissions_are_exact() -> None:
    expected = {
        "favicon-16x16.png": (16, 16),
        "favicon-32x32.png": (32, 32),
        "apple-touch-icon.png": (180, 180),
    }
    for filename, size in expected.items():
        path = ASSET_ROOT / filename
        with Image.open(path) as image:
            assert image.size == size
        assert path.stat().st_mode & 0o777 == 0o644


def test_ico_contains_useful_browser_sizes() -> None:
    path = ASSET_ROOT / "favicon.ico"
    with Image.open(path) as image:
        assert image.format == "ICO"
        assert {(16, 16), (32, 32)}.issubset(set(image.ico.sizes()))
    assert path.stat().st_mode & 0o777 == 0o644


def test_shared_head_helper_contains_canonical_public_hrefs() -> None:
    html = synth_favicon_head_html()
    assert "/synth/assets/brand/synth/favicon.svg" in html
    assert "/synth/assets/brand/synth/favicon-32x32.png" in html
    assert "/synth/assets/brand/synth/favicon-16x16.png" in html
    assert "/synth/assets/brand/synth/apple-touch-icon.png" in html
    assert "/synth/assets/brand/synth/favicon.ico" in html
    assert "/var/www/html/" not in html


def test_representative_pages_include_canonical_favicon_hrefs() -> None:
    about_html = about_page.render_about_html(hero_href="/synth/assets/brand/synth-third-faction-triptych.png")
    wallet_html = render_wallet_html(_wallet_payload())
    register_html = registration_pages.render_register_page()
    for html in (about_html, wallet_html, register_html):
        assert "/synth/assets/brand/synth/favicon.svg" in html
        assert "/synth/assets/brand/synth/favicon-32x32.png" in html
        assert "/synth/assets/brand/synth/favicon-16x16.png" in html
        assert "/synth/assets/brand/synth/apple-touch-icon.png" in html
        assert "/synth/assets/brand/synth/favicon.ico" in html
        assert "/var/www/html/" not in html


def test_representative_modules_use_shared_helper() -> None:
    source_files = [
        Path("src/reporting/run_synth_about_page_v1.py"),
        Path("src/reporting/account_wallet_dashboard_v1.py"),
        Path("src/reporting/manual_short_trader_dashboard_v1.py"),
        Path("src/reporting/manual_short_trader_profit_plan_v1.py"),
        Path("src/reporting/run_entry_candidate_static_dashboard_v1.py"),
        Path("src/reporting/run_paper_advice_static_dashboard_v1.py"),
        Path("src/reporting/run_position_rotation_static_dashboard_v1.py"),
        Path("src/web/run_website_registration_pages_v1.py"),
    ]
    for path in source_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert "synth_favicon_head_html" in source
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "src.reporting.dashboard_style_v1"
            and any(alias.name == "synth_favicon_head_html" for alias in node.names)
            for node in ast.walk(tree)
        )


def test_smoke_render_copies_favicon_assets_to_tmp_root() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "synth-favicon-smoke"
        copied = copy_synth_favicon_assets(output_root=root)
        copied_names = {path.name for path in copied}
        assert copied_names == set(SYNTH_FAVICON_FILENAMES)
        for filename in SYNTH_FAVICON_FILENAMES:
            path = root / "assets" / "brand" / "synth" / filename
            assert path.exists()
            assert path.stat().st_mode & 0o777 == 0o644


def main() -> None:
    tests = [
        test_svg_is_valid_and_has_no_scripts_or_external_refs,
        test_png_dimensions_and_permissions_are_exact,
        test_ico_contains_useful_browser_sizes,
        test_shared_head_helper_contains_canonical_public_hrefs,
        test_representative_pages_include_canonical_favicon_hrefs,
        test_representative_modules_use_shared_helper,
        test_smoke_render_copies_favicon_assets_to_tmp_root,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
