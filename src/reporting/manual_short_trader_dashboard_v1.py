from __future__ import annotations

import html as _html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


REPORT_NAME = "manual_short_trader_dashboard_v1"
REPORT_VERSION = "0.1"

NEAR_SELL_THRESHOLD_PCT = Decimal("2")
NEAR_BUY_THRESHOLD_PCT = Decimal("2")


# ---------------------------------------------------------------------------
# Normalised broker data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BrokerOrderRow:
    order_id: str
    market: str
    side: str           # "buy" | "sell"
    order_type: str     # "limit" | "market"
    limit_price: Decimal
    amount: Decimal     # base currency
    filled_amount: Decimal
    remaining_amount: Decimal
    status: str
    created_at_ms: int | None


@dataclass(frozen=True)
class BrokerBalanceRow:
    symbol: str
    available: Decimal
    in_order: Decimal


# ---------------------------------------------------------------------------
# Enriched / computed rows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LadderOrderRow:
    order_id: str
    market: str
    side: str
    limit_price: Decimal
    amount: Decimal
    filled_amount: Decimal
    quote_value: Decimal        # limit_price × amount
    distance_pct: Decimal | None  # (limit_price − current) / current × 100
    status: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class LadderSymbolSection:
    symbol: str
    market: str
    quote_currency: str
    current_price: Decimal | None
    buy_orders: tuple[LadderOrderRow, ...]
    sell_orders: tuple[LadderOrderRow, ...]
    balance_available: Decimal | None
    balance_in_order: Decimal | None
    fib_context: dict[str, Any]   # from fib_target_map CSV, if available
    section_labels: tuple[str, ...]


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------

def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal(default)


def parse_market(market: str) -> tuple[str, str]:
    """Split "WLD-EUR" → ("WLD", "EUR"). Unknown format → (market.upper(), "")."""
    parts = market.upper().split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return market.upper(), ""


def normalize_broker_order(raw: dict[str, Any]) -> BrokerOrderRow:
    """Normalise a raw Bitvavo open-order dict into a typed BrokerOrderRow."""
    return BrokerOrderRow(
        order_id=str(raw.get("orderId") or raw.get("order_id") or ""),
        market=str(raw.get("market") or ""),
        side=str(raw.get("side") or "").lower(),
        order_type=str(raw.get("orderType") or raw.get("order_type") or "limit").lower(),
        limit_price=_to_decimal(raw.get("price")),
        amount=_to_decimal(raw.get("amount")),
        filled_amount=_to_decimal(raw.get("filledAmount")),
        remaining_amount=_to_decimal(raw.get("amountRemaining")),
        status=str(raw.get("status") or ""),
        created_at_ms=int(raw["created"]) if raw.get("created") is not None else None,
    )


def normalize_broker_balance(raw: dict[str, Any]) -> BrokerBalanceRow:
    """Normalise a raw Bitvavo balance entry."""
    return BrokerBalanceRow(
        symbol=str(raw.get("symbol") or "").upper(),
        available=_to_decimal(raw.get("available")),
        in_order=_to_decimal(raw.get("inOrder")),
    )


def compute_distance_pct(limit_price: Decimal, current_price: Decimal) -> Decimal | None:
    """Distance from current price as percentage. Positive = order above current."""
    if current_price <= 0:
        return None
    return (limit_price - current_price) / current_price * Decimal("100")


def compute_quote_value(limit_price: Decimal, amount: Decimal) -> Decimal:
    """Quote-currency notional: limit_price × base_amount."""
    return limit_price * amount


def assign_order_labels(
    *,
    side: str,
    limit_price: Decimal,
    filled_amount: Decimal,
    amount: Decimal,
    current_price: Decimal | None,
    near_sell_threshold_pct: Decimal = NEAR_SELL_THRESHOLD_PCT,
    near_buy_threshold_pct: Decimal = NEAR_BUY_THRESHOLD_PCT,
) -> tuple[str, ...]:
    """
    Return an ordered, deduplicated tuple of labels for one open order.

    Labels:
      NEAR_SELL   — sell order within threshold % above current price
      NEAR_BUY    — buy order within threshold % below current price
      FILLED_REVIEW_NEEDED — partial fill detected (0 < filled < amount)
      MANUAL_ONLY — always present; marks that orders are placed manually
    """
    labels: list[str] = []

    if current_price is not None and current_price > 0:
        dist = compute_distance_pct(limit_price, current_price)
        if dist is not None:
            if side == "sell" and Decimal("0") <= dist <= near_sell_threshold_pct:
                labels.append("NEAR_SELL")
            elif side == "buy" and -near_buy_threshold_pct <= dist <= Decimal("0"):
                labels.append("NEAR_BUY")

    if amount > 0 and Decimal("0") < filled_amount < amount:
        labels.append("FILLED_REVIEW_NEEDED")

    labels.append("MANUAL_ONLY")
    return tuple(labels)


def _build_ladder_order_row(
    broker_order: BrokerOrderRow,
    current_price: Decimal | None,
) -> LadderOrderRow:
    distance = (
        compute_distance_pct(broker_order.limit_price, current_price)
        if current_price is not None and current_price > 0
        else None
    )
    return LadderOrderRow(
        order_id=broker_order.order_id,
        market=broker_order.market,
        side=broker_order.side,
        limit_price=broker_order.limit_price,
        amount=broker_order.amount,
        filled_amount=broker_order.filled_amount,
        quote_value=compute_quote_value(broker_order.limit_price, broker_order.amount),
        distance_pct=distance,
        status=broker_order.status,
        labels=assign_order_labels(
            side=broker_order.side,
            limit_price=broker_order.limit_price,
            filled_amount=broker_order.filled_amount,
            amount=broker_order.amount,
            current_price=current_price,
        ),
    )


def collect_unpriced_markets(
    orders: list[BrokerOrderRow],
    prices: dict[str, Decimal],
) -> list[str]:
    """Return sorted list of markets present in orders but absent from prices."""
    return sorted({o.market for o in orders} - set(prices.keys()))


def build_all_sections(
    orders: list[BrokerOrderRow],
    balances: list[BrokerBalanceRow],
    prices: dict[str, Decimal],
    *,
    fib_rows: dict[str, dict[str, Any]] | None = None,
) -> list[LadderSymbolSection]:
    """
    Group open orders by market, enrich with current price distance and labels,
    merge optional fib map context.

    prices keys must match Bitvavo market codes, e.g. "WLD-EUR".
    fib_rows keys are base symbols, e.g. "WLD".
    """
    fib_rows = fib_rows or {}
    balance_by_symbol: dict[str, BrokerBalanceRow] = {b.symbol: b for b in balances}
    markets = sorted({o.market for o in orders})

    sections: list[LadderSymbolSection] = []
    for market in markets:
        symbol, quote = parse_market(market)
        current_price = prices.get(market)
        market_orders = [o for o in orders if o.market == market]

        buy_rows = tuple(
            _build_ladder_order_row(o, current_price)
            for o in sorted(market_orders, key=lambda o: o.limit_price, reverse=True)
            if o.side == "buy"
        )
        sell_rows = tuple(
            _build_ladder_order_row(o, current_price)
            for o in sorted(market_orders, key=lambda o: o.limit_price)
            if o.side == "sell"
        )

        balance = balance_by_symbol.get(symbol)
        fib_ctx = fib_rows.get(symbol, {})

        seen: set[str] = set()
        section_labels: list[str] = []
        for row in buy_rows + sell_rows:
            for label in row.labels:
                if label not in seen:
                    seen.add(label)
                    section_labels.append(label)

        sections.append(
            LadderSymbolSection(
                symbol=symbol,
                market=market,
                quote_currency=quote,
                current_price=current_price,
                buy_orders=buy_rows,
                sell_orders=sell_rows,
                balance_available=balance.available if balance else None,
                balance_in_order=balance.in_order if balance else None,
                fib_context=fib_ctx,
                section_labels=tuple(section_labels),
            )
        )

    return sections


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_CSS = """
    :root {
      --bg: #080d18; --panel: #111a2e; --panel2: #17223b;
      --text: #ecf2ff; --muted: #93a4c2; --line: #293957;
      --bad: #ff7171; --warn: #ffd166; --ok: #66dfb2; --blue: #8fb3ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at top left, #172345, var(--bg) 45%);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      font-size: 14px;
    }
    header {
      padding: 20px 24px; border-bottom: 1px solid var(--line);
      background: rgba(8,13,24,.88); position: sticky; top: 0;
      z-index: 10; backdrop-filter: blur(10px);
    }
    h1 { margin: 0 0 8px; font-size: 24px; }
    h2 { margin: 0 0 8px; font-size: 20px; }
    h3 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase;
         letter-spacing: .07em; color: var(--blue); }
    main { padding: 16px; display: grid; gap: 16px; }
    .muted { color: var(--muted); } .small { font-size: 12px; }
    .ok { color: var(--ok); } .warn { color: var(--warn); } .bad { color: var(--bad); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .card {
      background: rgba(17,26,46,.94); border: 1px solid var(--line);
      border-radius: 16px; padding: 16px;
      box-shadow: 0 14px 38px rgba(0,0,0,.24);
    }
    .card-head {
      display: flex; justify-content: space-between; align-items: flex-start;
      gap: 12px; border-bottom: 1px solid var(--line);
      padding-bottom: 10px; margin-bottom: 12px;
    }
    .state { text-align: right; }
    .pill {
      display: inline-block; border-radius: 999px; padding: 3px 8px; margin: 2px;
      font-size: 12px; border: 1px solid var(--line);
      background: rgba(255,255,255,.04); white-space: nowrap;
    }
    .pill.ok  { color: var(--ok);   border-color: rgba(102,223,178,.45); }
    .pill.warn{ color: var(--warn); border-color: rgba(255,209,102,.45); }
    .pill.bad { color: var(--bad);  border-color: rgba(255,113,113,.45); }
    .pill.muted { color: var(--muted); }
    .orders-split {
      display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 12px;
    }
    @media (max-width: 900px) { .orders-split { grid-template-columns: 1fr; } }
    .table-wrap { overflow-x: auto; }
    .order-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .order-table th, .order-table td {
      padding: 7px 8px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap;
    }
    .order-table th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
    .order-table tbody tr:hover td { background: rgba(143,179,255,.06); }
    .empty { font-size: 13px; color: var(--muted); padding: 6px 0; }
    .fib-context {
      margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line);
    }
    .summary-line { margin-top: 8px; font-size: 13px; }
"""


def esc(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value))


def fmt_price(value: Decimal | None, *, places: int | None = None) -> str:
    if value is None:
        return "—"
    if places is None:
        places = 6 if abs(value) < Decimal("1") else 2
    try:
        return str(value.quantize(Decimal(10) ** -places))
    except Exception:
        return str(value)


def fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    try:
        return f"{sign}{value.quantize(Decimal('0.01'))}%"
    except Exception:
        return f"{sign}{value}%"


def _distance_class(distance_pct: Decimal | None, side: str) -> str:
    if distance_pct is None:
        return "muted"
    if side == "sell" and Decimal("0") <= distance_pct <= Decimal("2"):
        return "ok"
    if side == "buy" and Decimal("-2") <= distance_pct <= Decimal("0"):
        return "warn"
    return "muted"


def _pill_class(label: str) -> str:
    if label in {"NEAR_SELL", "NEAR_BUY"}:
        return "ok"
    if label == "FILLED_REVIEW_NEEDED":
        return "warn"
    return "muted"


def _pill(label: str) -> str:
    return f"<span class='pill {_pill_class(label)}'>{esc(label)}</span>"


def _order_table_html(rows: tuple[LadderOrderRow, ...], side: str) -> str:
    if not rows:
        return "<div class='empty'>No open orders.</div>"
    body_parts: list[str] = []
    for row in rows:
        dist_cls = _distance_class(row.distance_pct, side)
        short_id = (row.order_id[:14] + "…") if len(row.order_id) > 14 else row.order_id
        labels_html = " ".join(_pill(label) for label in row.labels)
        body_parts.append(
            f"<tr>"
            f"<td class='mono small'>{esc(short_id)}</td>"
            f"<td class='num mono'>{esc(fmt_price(row.limit_price))}</td>"
            f"<td class='num mono'>{esc(fmt_price(row.amount, places=4))}</td>"
            f"<td class='num mono'>{esc(fmt_price(row.quote_value))}</td>"
            f"<td class='num mono'>{esc(fmt_price(row.filled_amount, places=4))}</td>"
            f"<td class='num mono {dist_cls}'>{esc(fmt_pct(row.distance_pct))}</td>"
            f"<td class='muted small'>{esc(row.status)}</td>"
            f"<td>{labels_html}</td>"
            f"</tr>"
        )
    return (
        "<div class='table-wrap'>"
        "<table class='order-table'>"
        "<thead><tr>"
        "<th>Order ID</th>"
        "<th class='num'>Price</th>"
        "<th class='num'>Amount</th>"
        "<th class='num'>Quote Value</th>"
        "<th class='num'>Filled</th>"
        "<th class='num'>Distance</th>"
        "<th>Status</th>"
        "<th>Labels</th>"
        "</tr></thead>"
        "<tbody>" + "".join(body_parts) + "</tbody>"
        "</table></div>"
    )


def _fib_context_html(fib_ctx: dict[str, Any]) -> str:
    if not fib_ctx:
        return ""

    def _fv(key: str) -> str:
        val = fib_ctx.get(key)
        if val is None:
            return "—"
        try:
            return fmt_price(Decimal(str(val)))
        except Exception:
            return str(val)

    return (
        "<div class='fib-context'>"
        "<span class='muted small'>"
        f"Fib map — T1: {esc(_fv('fib_map_local_reaction_price'))} · "
        f"Next: {esc(_fv('fib_map_next_extension_target_price'))} · "
        f"Reload: {esc(_fv('fib_map_next_fibo_support_price'))}"
        "</span></div>"
    )


def render_symbol_section(section: LadderSymbolSection) -> str:
    price_str = fmt_price(section.current_price) if section.current_price else "—"
    labels_html = " ".join(_pill(label) for label in section.section_labels)

    balance_html = ""
    if section.balance_available is not None or section.balance_in_order is not None:
        avail = fmt_price(section.balance_available, places=4) if section.balance_available is not None else "—"
        in_ord = fmt_price(section.balance_in_order, places=4) if section.balance_in_order is not None else "—"
        balance_html = (
            f"<div class='muted small'>balance: "
            f"<span class='mono'>{esc(avail)}</span> {esc(section.symbol)} available · "
            f"<span class='mono'>{esc(in_ord)}</span> in orders</div>"
        )

    return (
        "<section class='card'>"
        "<div class='card-head'>"
        f"<div><h2>{esc(section.symbol)} "
        f"<span class='muted' style='font-size:15px'>{esc(section.market)}</span></h2>"
        f"<div><strong>Price:</strong> <span class='mono'>{esc(price_str)} {esc(section.quote_currency)}</span></div>"
        f"{balance_html}</div>"
        f"<div class='state'>{labels_html}</div>"
        "</div>"
        "<div class='orders-split'>"
        f"<div><h3 style='color:var(--ok)'>BUY Orders</h3>{_order_table_html(section.buy_orders, 'buy')}</div>"
        f"<div><h3 style='color:var(--warn)'>SELL Orders</h3>{_order_table_html(section.sell_orders, 'sell')}</div>"
        "</div>"
        f"{_fib_context_html(section.fib_context)}"
        "</section>"
    )


def render_full_html(
    sections: list[LadderSymbolSection],
    *,
    rendered_at: str | None = None,
    broker_mode: str = "offline",
) -> str:
    if rendered_at is None:
        rendered_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    total_buy = sum(len(s.buy_orders) for s in sections)
    total_sell = sum(len(s.sell_orders) for s in sections)
    symbols_str = esc(", ".join(s.symbol for s in sections) if sections else "none")
    cards = "\n".join(render_symbol_section(s) for s in sections)
    empty_note = "<div class='muted' style='padding:16px'>No open orders found.</div>" if not sections else ""

    return (
        "<!doctype html>\n<html lang='en'>\n<head>\n"
        "  <meta charset='utf-8'>\n"
        "  <meta http-equiv='refresh' content='120'>\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        "  <title>Synth — Short Trader Open Orders</title>\n"
        f"  <style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        "  <header>\n"
        "    <h1>Synth v2 — Manual Short Trader Dashboard</h1>\n"
        f"    <div class='muted'>Rendered: {esc(rendered_at)} · Mode: {esc(broker_mode)} · Symbols: {symbols_str}</div>\n"
        f"    <div class='summary-line muted'>BUY orders: {total_buy} · SELL orders: {total_sell}</div>\n"
        "    <div class='muted small' style='margin-top:6px'>"
        "Read-only snapshot. No broker writes. No order submission. No automatic placement."
        "</div>\n"
        "  </header>\n"
        "  <main>\n"
        f"    {empty_note}\n"
        f"    {cards}\n"
        "  </main>\n"
        "</body>\n</html>"
    )


# ---------------------------------------------------------------------------
# JSON snapshot
# ---------------------------------------------------------------------------

def _order_to_dict(row: LadderOrderRow) -> dict[str, Any]:
    return {
        "order_id": row.order_id,
        "market": row.market,
        "side": row.side,
        "limit_price": str(row.limit_price),
        "amount": str(row.amount),
        "filled_amount": str(row.filled_amount),
        "quote_value": str(row.quote_value),
        "distance_pct": str(row.distance_pct) if row.distance_pct is not None else None,
        "status": row.status,
        "labels": list(row.labels),
    }


def build_json_snapshot(
    sections: list[LadderSymbolSection],
    *,
    snapshot_ts: str | None = None,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "snapshot_ts": snapshot_ts or datetime.now(UTC).isoformat(),
        "broker_writes": 0,
        "order_submission": 0,
        "symbols": [
            {
                "symbol": s.symbol,
                "market": s.market,
                "current_price": str(s.current_price) if s.current_price is not None else None,
                "balance_available": str(s.balance_available) if s.balance_available is not None else None,
                "balance_in_order": str(s.balance_in_order) if s.balance_in_order is not None else None,
                "section_labels": list(s.section_labels),
                "buy_orders": [_order_to_dict(o) for o in s.buy_orders],
                "sell_orders": [_order_to_dict(o) for o in s.sell_orders],
            }
            for s in sections
        ],
    }
