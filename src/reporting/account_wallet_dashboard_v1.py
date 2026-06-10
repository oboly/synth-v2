from __future__ import annotations

import html
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot, fetch_latest_prices_by_symbol
from src.reporting.account_asset_management_v1 import (
    UI_PREP_REASON,
    build_account_asset_management_payload,
    build_ui_prep_actions,
)
from src.reporting.current_price_snapshot_v1 import (
    DEFAULT_CURRENT_PRICE_FRESH_AFTER,
    classify_current_price_snapshot,
)
from src.reporting.dashboard_style_v1 import synth_favicon_head_html
from src.reporting.dashboard_time_v1 import format_ui_timestamp


REPORT_NAME = "account_wallet_dashboard_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
DEFAULT_FRESH_AFTER = timedelta(minutes=15)
DEFAULT_PRICE_FRESH_AFTER = DEFAULT_CURRENT_PRICE_FRESH_AFTER
QUOTE_CURRENCY = "EUR"


@dataclass(frozen=True)
class BalanceDashboardRow:
    asset: str
    available: Decimal
    in_order: Decimal
    total: Decimal
    estimated_eur_value: Decimal | None
    price_eur: Decimal | None
    price_observed_ts_utc: datetime | None
    price_status: str
    price_age_min: Decimal | None


@dataclass(frozen=True)
class OpenOrderCountRow:
    market: str
    order_count: int


@dataclass(frozen=True)
class AccountAssetSettingsSummary:
    visible: int
    candidate_enabled: int
    proposal_enabled: int
    hidden: int
    disabled: int


@dataclass(frozen=True)
class WalletDashboardPayload:
    profile: str
    account_code: str
    trading_account_id: int
    venue: str
    display_timezone: str
    generated_ts_utc: datetime
    latest_wallet_refresh_ts_utc: datetime | None
    freshness: str
    latest_balance_snapshot_ts_utc: datetime | None
    latest_order_snapshot_ts_utc: datetime | None
    market_data_warning: str | None
    stale_market_data_count: int
    missing_market_data_count: int
    balance_count: int
    open_order_market_count: int
    total_open_order_count: int
    total_estimated_portfolio_value_eur: Decimal | None
    account_asset_settings: AccountAssetSettingsSummary
    dashboard_links: dict[str, str]
    balances: tuple[BalanceDashboardRow, ...]
    open_order_counts: tuple[OpenOrderCountRow, ...]
    management: dict[str, Any]


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def decimal_text(value: Decimal | None, *, places: str = "0.01") -> str:
    if value is None:
        return "—"
    try:
        rendered = str(value.quantize(Decimal(places)))
    except Exception:
        rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered == "-0":
        rendered = "0"
    return rendered


def esc(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return html.escape(value.isoformat(sep=" ", timespec="seconds"))
    return html.escape(str(value))


def classify_wallet_freshness(
    latest_wallet_refresh_ts_utc: datetime | None,
    *,
    now_utc: datetime,
    fresh_after: timedelta = DEFAULT_FRESH_AFTER,
) -> str:
    if latest_wallet_refresh_ts_utc is None:
        return "NEVER_REFRESHED"
    latest = latest_wallet_refresh_ts_utc.replace(tzinfo=None) if latest_wallet_refresh_ts_utc.tzinfo is not None else latest_wallet_refresh_ts_utc
    current = now_utc.replace(tzinfo=None) if now_utc.tzinfo is not None else now_utc
    if current - latest <= fresh_after:
        return "FRESH"
    return "STALE"


def _max_ts(*values: datetime | None) -> datetime | None:
    existing = [value for value in values if value is not None]
    if not existing:
        return None
    return max(existing)


def _account_dashboard_links(profile: str) -> dict[str, str]:
    return {
        "about": "/synth/about.html",
        "wallet": f"/synth/accounts/{profile}/wallet.html",
        "profit_plan": f"/synth/accounts/{profile}/profit-plan.html",
        "open_orders_monitor": f"/synth/accounts/{profile}/open-orders-monitor.html",
    }


def _fetch_trading_account(conn: Any, *, account_code: str, venue: str) -> dict[str, Any]:
    sql = """
    SELECT
        trading_account_id,
        account_code,
        venue
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
    ORDER BY trading_account_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        rows = list(cur.fetchall())
    if not rows:
        raise RuntimeError(f"trading_account not found: account_code={account_code} venue={venue}")
    if len(rows) != 1:
        raise RuntimeError(
            f"trading_account ambiguous: account_code={account_code} venue={venue} matches={len(rows)}"
        )
    return dict(rows[0])


def _fetch_latest_balance_snapshot_ts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> datetime | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        row = cur.fetchone()
    return None if not row else row.get("latest_snapshot_ts_utc")


def _fetch_balance_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    snapshot_ts_utc: datetime | None,
) -> list[dict[str, Any]]:
    if snapshot_ts_utc is None:
        return []
    sql = """
    SELECT
        currency_code,
        available_amount,
        reserved_amount,
        total_amount
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND snapshot_ts_utc = %s
    ORDER BY currency_code
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, snapshot_ts_utc))
        return list(cur.fetchall())


def _fetch_latest_order_snapshot_ts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> datetime | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM account_open_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue))
            row = cur.fetchone()
    except Exception:
        return None
    return None if not row else row.get("latest_snapshot_ts_utc")


def _fetch_open_order_counts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    snapshot_ts_utc: datetime | None,
) -> list[dict[str, Any]]:
    if snapshot_ts_utc is None:
        return []
    sql = """
    SELECT market, COUNT(*) AS order_count
    FROM account_open_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND snapshot_ts_utc = %s
    GROUP BY market
    ORDER BY market
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, snapshot_ts_utc))
        return list(cur.fetchall())


def _fetch_account_asset_settings(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    now_utc: datetime,
) -> AccountAssetSettingsSummary:
    sql = """
    SELECT
        COALESCE(SUM(CASE WHEN aa.is_visible = 1 THEN 1 ELSE 0 END), 0) AS visible_count,
        COALESCE(SUM(CASE WHEN aa.is_candidate_enabled = 1 THEN 1 ELSE 0 END), 0) AS candidate_enabled_count,
        COALESCE(SUM(CASE WHEN aa.is_order_proposal_enabled = 1 THEN 1 ELSE 0 END), 0) AS proposal_enabled_count,
        COALESCE(SUM(CASE WHEN aa.is_hidden = 1 THEN 1 ELSE 0 END), 0) AS hidden_count,
        COALESCE(
            SUM(
                CASE
                    WHEN aa.disabled_until_utc IS NOT NULL AND aa.disabled_until_utc > %s THEN 1
                    ELSE 0
                END
            ),
            0
        ) AS disabled_count
    FROM account_asset aa
    JOIN venue_market vm
      ON vm.venue_market_id = aa.venue_market_id
    WHERE aa.trading_account_id = %s
      AND vm.venue = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (now_utc.replace(tzinfo=None), trading_account_id, venue))
        row = cur.fetchone() or {}
    return AccountAssetSettingsSummary(
        visible=int(row.get("visible_count") or 0),
        candidate_enabled=int(row.get("candidate_enabled_count") or 0),
        proposal_enabled=int(row.get("proposal_enabled_count") or 0),
        hidden=int(row.get("hidden_count") or 0),
        disabled=int(row.get("disabled_count") or 0),
    )


def _fetch_account_asset_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    balance_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    balance_by_market: dict[str, bool] = {}
    for row in balance_rows:
        currency_code = str(row.get("currency_code") or "").upper()
        if not currency_code or currency_code == QUOTE_CURRENCY:
            continue
        total_amount = to_decimal(row.get("total_amount")) or Decimal("0")
        if total_amount > Decimal("0"):
            balance_by_market[f"{currency_code}-{QUOTE_CURRENCY}"] = True
    sql = """
    SELECT
        vm.market,
        vm.quote_currency,
        a.symbol AS asset_symbol,
        aa.source,
        aa.is_visible,
        aa.is_candidate_enabled,
        aa.is_order_proposal_enabled,
        aa.is_hidden,
        aa.disabled_until_utc
    FROM account_asset aa
    JOIN venue_market vm
      ON vm.venue_market_id = aa.venue_market_id
    JOIN asset a
      ON a.asset_id = vm.base_asset_id
    WHERE aa.trading_account_id = %s
      AND vm.venue = %s
    ORDER BY vm.market
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        rows = list(cur.fetchall())
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        market = str(item.get("market") or "").upper()
        item["market"] = market
        item["has_wallet_balance"] = bool(balance_by_market.get(market, False))
        out.append(item)
    return out


def _fetch_venue_market_rows(
    conn: Any,
    *,
    venue: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        vm.market,
        vm.quote_currency,
        vm.is_tradeable,
        a.symbol AS asset_symbol
    FROM venue_market vm
    JOIN asset a
      ON a.asset_id = vm.base_asset_id
    WHERE vm.venue = %s
    ORDER BY vm.market
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        return [dict(row) for row in cur.fetchall()]


def build_wallet_dashboard_payload(
    *,
    profile: str,
    account_code: str,
    trading_account_id: int,
    venue: str,
    display_timezone: str,
    latest_balance_snapshot_ts_utc: datetime | None,
    latest_order_snapshot_ts_utc: datetime | None,
    balance_rows: list[dict[str, Any]],
    open_order_count_rows: list[dict[str, Any]],
    account_asset_settings: AccountAssetSettingsSummary,
    price_by_symbol: dict[str, MarketPriceSnapshot],
    account_asset_rows: list[dict[str, Any]] | None = None,
    venue_market_rows: list[dict[str, Any]] | None = None,
    now_utc: datetime | None = None,
    fresh_after: timedelta = DEFAULT_FRESH_AFTER,
    price_fresh_after: timedelta = DEFAULT_PRICE_FRESH_AFTER,
) -> WalletDashboardPayload:
    now_utc = now_utc or datetime.now(UTC)
    account_asset_rows = account_asset_rows or []
    venue_market_rows = venue_market_rows or []
    latest_wallet_refresh_ts_utc = _max_ts(latest_balance_snapshot_ts_utc, latest_order_snapshot_ts_utc)
    freshness = classify_wallet_freshness(
        latest_wallet_refresh_ts_utc,
        now_utc=now_utc,
        fresh_after=fresh_after,
    )

    balances: list[BalanceDashboardRow] = []
    stale_market_data_count = 0
    missing_market_data_count = 0
    total_estimated_portfolio_value = Decimal("0")
    any_estimated_value = False

    for row in balance_rows:
        asset = str(row.get("currency_code") or "").upper()
        available = to_decimal(row.get("available_amount")) or Decimal("0")
        in_order = to_decimal(row.get("reserved_amount")) or Decimal("0")
        total = to_decimal(row.get("total_amount")) or (available + in_order)
        estimated_eur_value: Decimal | None = None
        price_eur: Decimal | None = None
        price_observed_ts_utc: datetime | None = None
        price_status = "NOT_NEEDED"
        price_age_min: Decimal | None = None

        if asset == QUOTE_CURRENCY:
            estimated_eur_value = total
            price_eur = Decimal("1")
            price_age_min = Decimal("0")
            total_estimated_portfolio_value += total
            any_estimated_value = True
        elif asset:
            snapshot = price_by_symbol.get(asset)
            price_display = classify_current_price_snapshot(
                snapshot,
                now_utc=now_utc,
                fresh_after=price_fresh_after,
            )
            price_status = price_display.status
            price_observed_ts_utc = price_display.observed_ts_utc
            price_age_min = price_display.age_min
            if price_status == "MISSING_CURRENT_PRICE":
                missing_market_data_count += 1
            elif price_status == "STALE_CURRENT_PRICE":
                stale_market_data_count += 1
                price_eur = snapshot.price if snapshot is not None else None
            else:
                price_eur = price_display.safe_price
                estimated_eur_value = total * price_display.safe_price
                total_estimated_portfolio_value += estimated_eur_value
                any_estimated_value = True

        balances.append(
            BalanceDashboardRow(
                asset=asset or "UNKNOWN",
                available=available,
                in_order=in_order,
                total=total,
                estimated_eur_value=estimated_eur_value,
                price_eur=price_eur,
                price_observed_ts_utc=price_observed_ts_utc,
                price_status=price_status,
                price_age_min=price_age_min,
            )
        )

    order_counts = tuple(
        OpenOrderCountRow(
            market=str(row.get("market") or ""),
            order_count=int(row.get("order_count") or 0),
        )
        for row in open_order_count_rows
    )
    total_open_order_count = sum(row.order_count for row in order_counts)

    market_data_warning: str | None = None
    if missing_market_data_count > 0 or stale_market_data_count > 0:
        market_data_warning = (
            f"Market data warning: missing_prices={missing_market_data_count} "
            f"stale_prices={stale_market_data_count}"
        )
    open_order_count_by_market = {
        row.market: row.order_count
        for row in order_counts
    }
    management = build_account_asset_management_payload(
        profile=profile,
        venue_market_rows=venue_market_rows,
        account_asset_rows=account_asset_rows,
        open_order_count_by_market=open_order_count_by_market,
    )
    management["relevant_assets"] = management.pop("relevant_rows")
    management["all_assets"] = management.pop("settings_rows")
    management["addable_markets"] = management.pop("manual_add_rows")
    management["open_orders_monitor"] = management.pop("open_order_rows")
    management["actions"] = build_ui_prep_actions(profile=profile, market="*")

    return WalletDashboardPayload(
        profile=profile,
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        display_timezone=display_timezone,
        generated_ts_utc=now_utc.replace(tzinfo=None),
        latest_wallet_refresh_ts_utc=latest_wallet_refresh_ts_utc,
        freshness=freshness,
        latest_balance_snapshot_ts_utc=latest_balance_snapshot_ts_utc,
        latest_order_snapshot_ts_utc=latest_order_snapshot_ts_utc,
        market_data_warning=market_data_warning,
        stale_market_data_count=stale_market_data_count,
        missing_market_data_count=missing_market_data_count,
        balance_count=len(balances),
        open_order_market_count=len(order_counts),
        total_open_order_count=total_open_order_count,
        total_estimated_portfolio_value_eur=(
            total_estimated_portfolio_value if any_estimated_value else None
        ),
        account_asset_settings=account_asset_settings,
        dashboard_links=_account_dashboard_links(profile),
        balances=tuple(balances),
        open_order_counts=order_counts,
        management=management,
    )


def load_wallet_dashboard_payload(
    conn: Any,
    *,
    profile: str,
    account_code: str,
    venue: str,
    display_timezone: str,
    now_utc: datetime | None = None,
    fresh_after: timedelta = DEFAULT_FRESH_AFTER,
    price_fresh_after: timedelta = DEFAULT_PRICE_FRESH_AFTER,
) -> WalletDashboardPayload:
    now_utc = now_utc or datetime.now(UTC)
    account = _fetch_trading_account(conn, account_code=account_code, venue=venue)
    trading_account_id = int(account["trading_account_id"])
    latest_balance_snapshot_ts_utc = _fetch_latest_balance_snapshot_ts(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
    )
    latest_order_snapshot_ts_utc = _fetch_latest_order_snapshot_ts(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
    )
    balance_rows = _fetch_balance_rows(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        snapshot_ts_utc=latest_balance_snapshot_ts_utc,
    )
    open_order_count_rows = _fetch_open_order_counts(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        snapshot_ts_utc=latest_order_snapshot_ts_utc,
    )
    account_asset_settings = _fetch_account_asset_settings(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        now_utc=now_utc,
    )
    account_asset_rows = _fetch_account_asset_rows(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        balance_rows=balance_rows,
    )
    venue_market_rows = _fetch_venue_market_rows(conn, venue=venue)
    price_symbols = [
        str(row.get("currency_code") or "").upper()
        for row in balance_rows
        if str(row.get("currency_code") or "").upper() not in {"", QUOTE_CURRENCY}
    ]
    price_by_symbol = fetch_latest_prices_by_symbol(
        conn,
        venue=venue,
        quote_currency=QUOTE_CURRENCY,
        symbols=price_symbols,
    )
    return build_wallet_dashboard_payload(
        profile=profile,
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        display_timezone=display_timezone,
        latest_balance_snapshot_ts_utc=latest_balance_snapshot_ts_utc,
        latest_order_snapshot_ts_utc=latest_order_snapshot_ts_utc,
        balance_rows=balance_rows,
        open_order_count_rows=open_order_count_rows,
        account_asset_settings=account_asset_settings,
        price_by_symbol=price_by_symbol,
        account_asset_rows=account_asset_rows,
        venue_market_rows=venue_market_rows,
        now_utc=now_utc,
        fresh_after=fresh_after,
        price_fresh_after=price_fresh_after,
    )


def payload_to_json_dict(payload: WalletDashboardPayload) -> dict[str, Any]:
    return {
        "profile": payload.profile,
        "account_code": payload.account_code,
        "trading_account_id": payload.trading_account_id,
        "venue": payload.venue,
        "display_timezone": payload.display_timezone,
        "generated_ts_utc": payload.generated_ts_utc.isoformat(sep=" "),
        "latest_wallet_refresh_ts_utc": (
            None
            if payload.latest_wallet_refresh_ts_utc is None
            else payload.latest_wallet_refresh_ts_utc.isoformat(sep=" ")
        ),
        "latest_balance_snapshot_ts_utc": (
            None
            if payload.latest_balance_snapshot_ts_utc is None
            else payload.latest_balance_snapshot_ts_utc.isoformat(sep=" ")
        ),
        "latest_order_snapshot_ts_utc": (
            None
            if payload.latest_order_snapshot_ts_utc is None
            else payload.latest_order_snapshot_ts_utc.isoformat(sep=" ")
        ),
        "freshness": payload.freshness,
        "market_data_warning": payload.market_data_warning,
        "stale_market_data_count": payload.stale_market_data_count,
        "missing_market_data_count": payload.missing_market_data_count,
        "balance_count": payload.balance_count,
        "open_order_market_count": payload.open_order_market_count,
        "total_open_order_count": payload.total_open_order_count,
        "total_estimated_portfolio_value_eur": (
            None
            if payload.total_estimated_portfolio_value_eur is None
            else str(payload.total_estimated_portfolio_value_eur)
        ),
        "account_asset_settings": asdict(payload.account_asset_settings),
        "dashboard_links": payload.dashboard_links,
        "management": payload.management,
        "balances": [
            {
                "asset": row.asset,
                "available": str(row.available),
                "in_order": str(row.in_order),
                "total": str(row.total),
                "estimated_eur_value": None if row.estimated_eur_value is None else str(row.estimated_eur_value),
                "price_eur": None if row.price_eur is None else str(row.price_eur),
                "price_observed_ts_utc": (
                    None if row.price_observed_ts_utc is None else row.price_observed_ts_utc.isoformat(sep=" ")
                ),
                "price_status": row.price_status,
                "price_age_min": None if row.price_age_min is None else str(row.price_age_min),
            }
            for row in payload.balances
        ],
        "open_order_counts": [asdict(row) for row in payload.open_order_counts],
        "safety_markers": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }


def render_wallet_html(payload: WalletDashboardPayload) -> str:
    fresh_class = {
        "FRESH": "ok",
        "STALE": "warn",
        "NEVER_REFRESHED": "bad",
    }.get(payload.freshness, "muted")
    warning_html = ""
    if payload.market_data_warning:
        warning_html = (
            f"<div class='warning'><strong>warning</strong>: {esc(payload.market_data_warning)}. "
            "Estimated EUR values may be incomplete or stale.</div>"
        )

    def _price_status_label(status: str) -> str:
        if status == "NOT_NEEDED":
            return "No conversion needed"
        return status

    balances_html = "".join(
        (
            "<tr>"
            f"<td>{esc(row.asset)}</td>"
            f"<td>{esc(decimal_text(row.available, places='0.000000'))}</td>"
            f"<td>{esc(decimal_text(row.in_order, places='0.000000'))}</td>"
            f"<td>{esc(decimal_text(row.total, places='0.000000'))}</td>"
            f"<td>{esc(decimal_text(row.estimated_eur_value))}</td>"
            f"<td>{esc(_price_status_label(row.price_status))}</td>"
            f"<td>{esc(decimal_text(row.price_age_min, places='0.1'))}</td>"
            "</tr>"
        )
        for row in payload.balances
    )
    if not balances_html:
        balances_html = (
            "<tr><td colspan='7' class='muted'>No wallet balances found for the latest snapshot.</td></tr>"
        )

    order_counts_html = "".join(
        (
            "<tr>"
            f"<td>{esc(row.market)}</td>"
            f"<td>{esc(row.order_count)}</td>"
            "</tr>"
        )
        for row in payload.open_order_counts
    )
    if not order_counts_html:
        order_counts_html = (
            "<tr><td colspan='2' class='muted'>No open orders found for the latest snapshot.</td></tr>"
        )
    addable_rows = payload.management.get("addable_markets", [])
    relevant_rows = payload.management.get("relevant_assets", [])
    all_rows = payload.management.get("all_assets", [])
    top_actions = payload.management.get("actions", [])
    action_bar_html = "".join(
        (
            f"<button type='button' disabled title='{esc(action.get('reason'))}'>"
            f"{esc(action.get('label'))}</button>"
        )
        for action in top_actions
    )
    addable_html = "".join(
        (
            "<tr>"
            f"<td>{esc(row.get('market'))}</td>"
            f"<td>{esc(row.get('asset_symbol') or '')}</td>"
            f"<td>{esc(row.get('source') or 'NOT_ADDED')}</td>"
            f"<td>{'YES' if row.get('already_added') else 'NO'}</td>"
            f"<td>{'YES' if row.get('is_account_active') else 'NO'}</td>"
            f"<td>{esc(row.get('actions', [{}])[0].get('reason') or UI_PREP_REASON)}</td>"
            "</tr>"
        )
        for row in addable_rows
    )
    if not addable_html:
        addable_html = "<tr><td colspan='6' class='muted'>No addable markets available for this account.</td></tr>"
    relevant_html = "".join(
        (
            "<tr>"
            f"<td>{esc(row.get('market'))}</td>"
            f"<td>{esc(row.get('source') or '')}</td>"
            f"<td>{'YES' if row.get('is_candidate_enabled') else 'NO'}</td>"
            f"<td>{esc(row.get('open_order_count') or 0)}</td>"
            f"<td>{esc(row.get('actions', [{}])[1].get('reason') or UI_PREP_REASON)}</td>"
            "</tr>"
        )
        for row in relevant_rows
    )
    if not relevant_html:
        relevant_html = "<tr><td colspan='5' class='muted'>No relevant account assets available.</td></tr>"
    all_assets_html = "".join(
        (
            "<tr>"
            f"<td>{esc(row.get('market'))}</td>"
            f"<td>{esc(row.get('source') or 'NOT_ADDED')}</td>"
            f"<td>{'YES' if row.get('is_hidden') else 'NO'}</td>"
            f"<td>{'YES' if row.get('is_candidate_enabled') else 'NO'}</td>"
            f"<td>{'YES' if row.get('already_added') else 'NO'}</td>"
            f"<td>{esc(row.get('actions', [{}])[-1].get('reason') or UI_PREP_REASON)}</td>"
            "</tr>"
        )
        for row in all_rows
    )
    if not all_assets_html:
        all_assets_html = "<tr><td colspan='6' class='muted'>No settings rows available.</td></tr>"
    dashboard_nav_html = "".join(
        (
            f"<a href='{esc(payload.dashboard_links['about'])}'>About</a>",
            f"<a href='{esc(payload.dashboard_links['wallet'])}'>Wallet</a>",
            f"<a href='{esc(payload.dashboard_links['profit_plan'])}'>Profit Plan</a>",
            f"<a href='{esc(payload.dashboard_links['open_orders_monitor'])}'>Open Orders Monitor</a>",
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Wallet · {esc(payload.profile)}</title>
  {synth_favicon_head_html().rstrip()}
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f5f1e8; color: #1a1a1a; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    .hero {{ background: linear-gradient(135deg, #f9f5ec, #e2ecdf); border: 1px solid #cbbfa7; border-radius: 16px; padding: 20px; }}
    .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .ok {{ background: #d9f3df; color: #0a5c2a; }}
    .warn {{ background: #fff1c2; color: #7c5a00; }}
    .bad {{ background: #ffd9d4; color: #8b1e12; }}
    .muted {{ color: #666; }}
    .warning {{ margin-top: 16px; padding: 12px; border-radius: 12px; background: #fff4d6; border: 1px solid #e0c36b; }}
    .navlinks {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; }}
    .navlinks a {{ color: #1d5f8c; text-decoration: none; font-weight: 600; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 18px; }}
    .card {{ background: white; border: 1px solid #d9cfbb; border-radius: 14px; padding: 16px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: white; border-radius: 14px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #eee7d9; }}
    th {{ background: #f3ecde; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .section {{ margin-top: 22px; }}
    button[disabled] {{ border: 1px solid #bbb; background: #eee; color: #666; border-radius: 10px; padding: 10px 14px; cursor: not-allowed; }}
    .footnote {{ margin-top: 18px; font-size: 12px; color: #555; }}
    .actionbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="muted">Synth account wallet dashboard v1</div>
      <h1>{esc(payload.profile)} wallet</h1>
      <div>account_code={esc(payload.account_code)} · trading_account_id={esc(payload.trading_account_id)} · venue={esc(payload.venue)}</div>
      <div style="margin-top:10px;">
        <span class="pill {fresh_class}">{esc(payload.freshness)}</span>
      </div>
      <div class="footnote">
        latest wallet refresh: {esc(format_ui_timestamp(payload.latest_wallet_refresh_ts_utc, timezone=payload.display_timezone, missing_text="never"))} ·
        latest balance snapshot: {esc(format_ui_timestamp(payload.latest_balance_snapshot_ts_utc, timezone=payload.display_timezone, missing_text="none"))} ·
        latest order snapshot: {esc(format_ui_timestamp(payload.latest_order_snapshot_ts_utc, timezone=payload.display_timezone, missing_text="none"))}
      </div>
      <div class="navlinks">{dashboard_nav_html}</div>
      {warning_html}
      <div style="margin-top:16px;">
        <button type="button" disabled>Manual refresh requires authenticated account action.</button>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="muted">Total estimated portfolio value</div>
        <div><strong>{esc(decimal_text(payload.total_estimated_portfolio_value_eur))} EUR</strong></div>
      </div>
      <div class="card">
        <div class="muted">Open order markets</div>
        <div><strong>{esc(payload.open_order_market_count)}</strong> markets · {esc(payload.total_open_order_count)} orders</div>
      </div>
      <div class="card">
        <div class="muted">Account asset settings</div>
        <div>visible={esc(payload.account_asset_settings.visible)} · candidate_enabled={esc(payload.account_asset_settings.candidate_enabled)}</div>
        <div>proposal_enabled={esc(payload.account_asset_settings.proposal_enabled)} · hidden={esc(payload.account_asset_settings.hidden)} · disabled={esc(payload.account_asset_settings.disabled)}</div>
      </div>
      <div class="card">
        <div class="muted">Safety</div>
        <div>broker_writes=0 · order_submission=0 · executor=none</div>
      </div>
    </div>

    <div class="section">
      <h2>Balances</h2>
      <table>
        <thead>
          <tr>
            <th>Asset</th>
            <th>Available now</th>
            <th>Reserved in open orders</th>
            <th>Total balance</th>
            <th>Estimated EUR value</th>
            <th>Market-data status</th>
            <th>Price age (min)</th>
          </tr>
        </thead>
        <tbody>
          {balances_html}
        </tbody>
      </table>
      <div class="footnote">
        <strong>Available now</strong> = immediately spendable &nbsp;&middot;&nbsp;
        <strong>Reserved in open orders</strong> = locked by active orders &nbsp;&middot;&nbsp;
        <strong>Total balance</strong> = available + reserved
      </div>
    </div>

    <div class="section">
      <h2>Open Order Count By Market</h2>
      <table>
        <thead>
          <tr>
            <th>Market</th>
            <th>Open Orders</th>
          </tr>
        </thead>
        <tbody>
          {order_counts_html}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>Management</h2>
      <div class="muted">UI-prep only. No public mutation endpoint. All actions remain disabled until an authenticated account mutation layer exists.</div>
      <div class="actionbar">{action_bar_html}</div>
    </div>

    <div class="section">
      <h2>Addable Markets</h2>
      <table>
        <thead>
          <tr>
            <th>Market</th>
            <th>Asset</th>
            <th>Source</th>
            <th>Already Added</th>
            <th>Active Coin</th>
            <th>Action State</th>
          </tr>
        </thead>
        <tbody>
          {addable_html}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>Relevant Assets</h2>
      <table>
        <thead>
          <tr>
            <th>Market</th>
            <th>Source</th>
            <th>Candidate Enabled</th>
            <th>Open Orders</th>
            <th>Action State</th>
          </tr>
        </thead>
        <tbody>
          {relevant_html}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>All / Settings</h2>
      <table>
        <thead>
          <tr>
            <th>Market</th>
            <th>Source</th>
            <th>Hidden</th>
            <th>Candidate Enabled</th>
            <th>Already Added</th>
            <th>Action State</th>
          </tr>
        </thead>
        <tbody>
          {all_assets_html}
        </tbody>
      </table>
    </div>

    <div class="footnote">
      DB is source of truth. This page is static render output only. No credentials are stored in webroot.
    </div>
  </div>
</body>
</html>"""


def write_wallet_dashboard(
    payload: WalletDashboardPayload,
    *,
    output_root: Path,
) -> tuple[Path, Path]:
    profile_dir = output_root / "accounts" / payload.profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o755)
    html_path = profile_dir / "wallet.html"
    json_path = profile_dir / "wallet.json"
    html_path.write_text(render_wallet_html(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload_to_json_dict(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return html_path, json_path


def load_and_write_wallet_dashboard(
    *,
    profile: str,
    account_code: str,
    venue: str,
    display_timezone: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    fresh_after: timedelta = DEFAULT_FRESH_AFTER,
    price_fresh_after: timedelta = DEFAULT_PRICE_FRESH_AFTER,
) -> tuple[WalletDashboardPayload, Path, Path]:
    conn = get_connection()
    try:
        payload = load_wallet_dashboard_payload(
            conn,
            profile=profile,
            account_code=account_code,
            venue=venue,
            display_timezone=display_timezone,
            fresh_after=fresh_after,
            price_fresh_after=price_fresh_after,
        )
    finally:
        conn.close()
    html_path, json_path = write_wallet_dashboard(payload, output_root=output_root)
    return payload, html_path, json_path
