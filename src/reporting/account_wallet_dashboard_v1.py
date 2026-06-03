from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot, fetch_latest_prices_by_symbol


REPORT_NAME = "account_wallet_dashboard_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
DEFAULT_FRESH_AFTER = timedelta(minutes=15)
DEFAULT_PRICE_FRESH_AFTER = timedelta(minutes=15)
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
    balances: tuple[BalanceDashboardRow, ...]
    open_order_counts: tuple[OpenOrderCountRow, ...]


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


def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def classify_wallet_freshness(
    latest_wallet_refresh_ts_utc: datetime | None,
    *,
    now_utc: datetime,
    fresh_after: timedelta = DEFAULT_FRESH_AFTER,
) -> str:
    if latest_wallet_refresh_ts_utc is None:
        return "NEVER_REFRESHED"
    if _naive_utc(now_utc) - _naive_utc(latest_wallet_refresh_ts_utc) <= fresh_after:
        return "FRESH"
    return "STALE"


def classify_price_status(
    snapshot: MarketPriceSnapshot | None,
    *,
    now_utc: datetime,
    fresh_after: timedelta = DEFAULT_PRICE_FRESH_AFTER,
) -> str:
    if snapshot is None:
        return "MISSING"
    if _naive_utc(now_utc) - _naive_utc(snapshot.observed_ts_utc) <= fresh_after:
        return "FRESH"
    return "STALE"


def _max_ts(*values: datetime | None) -> datetime | None:
    existing = [value for value in values if value is not None]
    if not existing:
        return None
    return max(existing)


def _fetch_trading_account(conn: Any, *, account_code: str, venue: str) -> dict[str, Any]:
    sql = """
    SELECT
        trading_account_id,
        account_code,
        venue
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"trading_account not found: account_code={account_code} venue={venue}")
    return dict(row)


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


def build_wallet_dashboard_payload(
    *,
    profile: str,
    account_code: str,
    trading_account_id: int,
    venue: str,
    latest_balance_snapshot_ts_utc: datetime | None,
    latest_order_snapshot_ts_utc: datetime | None,
    balance_rows: list[dict[str, Any]],
    open_order_count_rows: list[dict[str, Any]],
    account_asset_settings: AccountAssetSettingsSummary,
    price_by_symbol: dict[str, MarketPriceSnapshot],
    now_utc: datetime | None = None,
    fresh_after: timedelta = DEFAULT_FRESH_AFTER,
    price_fresh_after: timedelta = DEFAULT_PRICE_FRESH_AFTER,
) -> WalletDashboardPayload:
    now_utc = now_utc or datetime.now(UTC)
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

        if asset == QUOTE_CURRENCY:
            estimated_eur_value = total
            price_eur = Decimal("1")
            total_estimated_portfolio_value += total
            any_estimated_value = True
        elif asset:
            snapshot = price_by_symbol.get(asset)
            price_status = classify_price_status(
                snapshot,
                now_utc=now_utc,
                fresh_after=price_fresh_after,
            )
            if snapshot is None:
                missing_market_data_count += 1
            else:
                price_eur = snapshot.price
                price_observed_ts_utc = snapshot.observed_ts_utc
                estimated_eur_value = total * snapshot.price
                total_estimated_portfolio_value += estimated_eur_value
                any_estimated_value = True
                if price_status == "STALE":
                    stale_market_data_count += 1

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

    return WalletDashboardPayload(
        profile=profile,
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
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
        balances=tuple(balances),
        open_order_counts=order_counts,
    )


def load_wallet_dashboard_payload(
    conn: Any,
    *,
    profile: str,
    account_code: str,
    venue: str,
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
        latest_balance_snapshot_ts_utc=latest_balance_snapshot_ts_utc,
        latest_order_snapshot_ts_utc=latest_order_snapshot_ts_utc,
        balance_rows=balance_rows,
        open_order_count_rows=open_order_count_rows,
        account_asset_settings=account_asset_settings,
        price_by_symbol=price_by_symbol,
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

    balances_html = "".join(
        (
            "<tr>"
            f"<td>{esc(row.asset)}</td>"
            f"<td>{esc(decimal_text(row.available, places='0.000000'))}</td>"
            f"<td>{esc(decimal_text(row.in_order, places='0.000000'))}</td>"
            f"<td>{esc(decimal_text(row.estimated_eur_value))}</td>"
            f"<td>{esc(row.price_status)}</td>"
            "</tr>"
        )
        for row in payload.balances
    )
    if not balances_html:
        balances_html = (
            "<tr><td colspan='5' class='muted'>No wallet balances found for the latest snapshot.</td></tr>"
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

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Wallet · {esc(payload.profile)}</title>
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
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 18px; }}
    .card {{ background: white; border: 1px solid #d9cfbb; border-radius: 14px; padding: 16px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: white; border-radius: 14px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #eee7d9; }}
    th {{ background: #f3ecde; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .section {{ margin-top: 22px; }}
    button[disabled] {{ border: 1px solid #bbb; background: #eee; color: #666; border-radius: 10px; padding: 10px 14px; cursor: not-allowed; }}
    .footnote {{ margin-top: 18px; font-size: 12px; color: #555; }}
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
        latest wallet refresh: {esc(payload.latest_wallet_refresh_ts_utc or "never")} ·
        latest balance snapshot: {esc(payload.latest_balance_snapshot_ts_utc or "none")} ·
        latest order snapshot: {esc(payload.latest_order_snapshot_ts_utc or "none")}
      </div>
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
            <th>Available</th>
            <th>In Order</th>
            <th>Estimated EUR Value</th>
            <th>Market Data</th>
          </tr>
        </thead>
        <tbody>
          {balances_html}
        </tbody>
      </table>
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
            fresh_after=fresh_after,
            price_fresh_after=price_fresh_after,
        )
    finally:
        conn.close()
    html_path, json_path = write_wallet_dashboard(payload, output_root=output_root)
    return payload, html_path, json_path
