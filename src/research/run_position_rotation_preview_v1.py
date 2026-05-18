from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "position_rotation_preview_v1"
REPORT_VERSION = "0.1"


@dataclass(frozen=True)
class RotationRow:
    trading_account_id: int
    account_code: str
    account_mode: str
    live_trading_enabled: int
    position_symbol: str
    venue: str
    position_snapshot_ts_utc: datetime | None
    position_source_name: str | None
    position_source_age_days: Decimal | None
    position_source_state: str
    quantity_base: Decimal | None
    available_quantity_base: Decimal | None
    reserved_quantity_base: Decimal | None
    position_mark_price_eur: Decimal | None
    position_value_eur: Decimal | None
    paper_asof_ts_utc: datetime | None
    selection_state: str | None
    priority_rank: int | None
    selection_score: Decimal | None
    setup_filter_state: str | None
    setup_filter_reason: str | None
    advice_state: str | None
    advice_action: str | None
    leg_direction: str | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    tp_zone_low: Decimal | None
    tp_zone_high: Decimal | None
    invalidation_price: Decimal | None
    aplus_bucket: str | None
    better_candidates: list[str]
    rotation_state: str
    rotation_pressure_score: int
    reason_codes: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only account-aware position rotation preview v1."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--trading-account-id", type=int, default=None)
    parser.add_argument("--stale-days", type=Decimal, default=Decimal("1.0"))
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def dec_text(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def dt_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat(sep=" ")


def fetch_latest_position_rows(
    conn: Any,
    *,
    venue: str,
    trading_account_id: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"venue": venue, "limit": int(limit)}
    account_filter = ""
    if trading_account_id is not None:
        account_filter = "AND p.trading_account_id = %(trading_account_id)s"
        params["trading_account_id"] = int(trading_account_id)

    sql = f"""
    WITH latest_position AS (
        SELECT trading_account_id, MAX(snapshot_ts_utc) AS snapshot_ts_utc
        FROM account_position_snapshot
        WHERE venue = %(venue)s
        GROUP BY trading_account_id
    )
    SELECT
        p.snapshot_ts_utc,
        p.trading_account_id,
        ta.account_code,
        ta.account_mode,
        ta.live_trading_enabled,
        p.asset_id,
        p.symbol,
        p.venue,
        p.quantity_base,
        p.available_quantity_base,
        p.reserved_quantity_base,
        p.average_entry_price_eur,
        p.mark_price_eur,
        (p.quantity_base * p.mark_price_eur) AS position_value_eur,
        p.source_name
    FROM account_position_snapshot p
    JOIN latest_position lp
      ON lp.trading_account_id = p.trading_account_id
     AND lp.snapshot_ts_utc = p.snapshot_ts_utc
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE p.venue = %(venue)s
      AND p.quantity_base > 0
      {account_filter}
    ORDER BY position_value_eur DESC, p.symbol ASC
    LIMIT %(limit)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_latest_paper_advice_rows(
    conn: Any,
    *,
    venue: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    sql = """
    WITH latest_advice AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM paper_advice_observation
        WHERE venue = %(venue)s
          AND interval_code = %(interval)s
    )
    SELECT
        p.*
    FROM paper_advice_observation p
    JOIN latest_advice la
      ON la.asof_ts_utc = p.asof_ts_utc
    WHERE p.venue = %(venue)s
      AND p.interval_code = %(interval)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"venue": venue, "interval": interval})
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def classify_position_source(
    *,
    snapshot_ts: datetime | None,
    stale_days: Decimal,
) -> tuple[str, Decimal | None, list[str]]:
    reasons: list[str] = []

    if snapshot_ts is None:
        return "MISSING", None, ["POSITION_SOURCE_MISSING"]

    now = datetime.now(UTC).replace(tzinfo=None)
    age_seconds = Decimal(str((now - snapshot_ts).total_seconds()))
    age_days = age_seconds / Decimal("86400")

    if age_days > stale_days:
        reasons.append("POSITION_SOURCE_STALE")
        return "STALE", age_days, reasons

    reasons.append("POSITION_SOURCE_FRESH")
    return "FRESH", age_days, reasons


def classify_rotation(
    *,
    position_row: dict[str, Any],
    advice_row: dict[str, Any] | None,
    position_source_state: str,
) -> tuple[str, int, list[str]]:
    reasons: list[str] = []
    score = 0

    if position_source_state == "STALE":
        reasons.append("POSITION_SOURCE_STALE")
        score += 2
    elif position_source_state == "MISSING":
        reasons.append("POSITION_SOURCE_MISSING")
        return "NO_POSITION_CONTEXT", score, reasons
    else:
        reasons.append("POSITION_SOURCE_FRESH")

    if not advice_row:
        reasons.append("PAPER_ADVICE_MISSING")
        return "REVIEW_ONLY", score + 1, reasons

    selection_state = str(advice_row.get("selection_state") or "").upper()
    setup_state = str(advice_row.get("setup_filter_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

    if selection_state:
        reasons.append(f"SELECTION_{selection_state}")
    if setup_state:
        reasons.append(f"SETUP_{setup_state}")
    if setup_reason:
        reasons.append(setup_reason)
    if advice_action:
        reasons.append(f"ADVICE_{advice_action}")
    if leg_direction:
        reasons.append(f"LEG_{leg_direction}")
    if aplus_bucket:
        reasons.append(aplus_bucket)

    if setup_reason == "MARKET_DAMAGE_RISK":
        score += 4
    elif setup_reason == "MARKET_DAMAGE_CAUTION":
        score += 2

    if advice_action == "WATCH_ONLY":
        score += 2
    elif advice_action == "WAIT":
        score += 1

    if leg_direction == "DOWN":
        score += 2

    if aplus_bucket == "APLUS_AVOID":
        score += 2
    elif aplus_bucket == "APLUS_UNKNOWN":
        score += 1

    if selection_state == "AVOID":
        score += 2
    elif selection_state == "NEUTRAL":
        score += 1
    elif selection_state == "WATCHLIST":
        score -= 1

    if position_source_state == "STALE":
        # Stale private-read position data must never escalate to an exit label.
        # It may raise review pressure, but fresh account state is required before
        # any exit/trim-specific downstream workflow.
        if score >= 4:
            return "REDUCE_REVIEW_CANDIDATE_STALE_SOURCE", score, reasons
        return "HOLD_REVIEW_STALE_SOURCE", score, reasons

    if score >= 7:
        return "EXIT_CANDIDATE", score, reasons
    if score >= 4:
        return "REDUCE_CANDIDATE", score, reasons
    if score >= 2:
        return "HOLD_REVIEW", score, reasons

    return "HOLD", score, reasons



def market_candidate_quality_score(advice_row: dict[str, Any] | None) -> Decimal:
    if not advice_row:
        return Decimal("-999")

    score = Decimal("0")
    selection_state = str(advice_row.get("selection_state") or "").upper()
    setup_state = str(advice_row.get("setup_filter_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

    selection_score = dec(advice_row.get("selection_score")) or Decimal("0")
    score += selection_score * Decimal("10")

    if selection_state == "WATCHLIST":
        score += Decimal("4")
    elif selection_state == "NEUTRAL":
        score += Decimal("1")
    elif selection_state == "AVOID":
        score -= Decimal("4")

    if setup_state == "PASS":
        score += Decimal("5")
    elif setup_state == "FAIL":
        score -= Decimal("2")

    if setup_reason == "MARKET_DAMAGE_RISK":
        score -= Decimal("5")
    elif setup_reason == "MARKET_DAMAGE_CAUTION":
        score -= Decimal("2")
    elif setup_reason == "SELECTION_STATE_NOT_ELIGIBLE":
        score -= Decimal("2")

    if advice_action in {"BUY_READY", "ACCUMULATE", "BUY"}:
        score += Decimal("5")
    elif advice_action == "WATCH_ONLY":
        score -= Decimal("1")
    elif advice_action == "WAIT":
        score += Decimal("0")

    if leg_direction == "UP":
        score += Decimal("2")
    elif leg_direction == "DOWN":
        score -= Decimal("2")

    if aplus_bucket == "APLUS_AVOID":
        score -= Decimal("4")
    elif aplus_bucket == "APLUS_UNKNOWN":
        score -= Decimal("1")
    elif aplus_bucket.startswith("APLUS_"):
        score += Decimal("1")

    return score


def rank_market_candidates(
    advice_by_symbol: dict[str, dict[str, Any]],
) -> list[tuple[str, Decimal]]:
    ranked: list[tuple[str, Decimal]] = []

    for symbol, advice in advice_by_symbol.items():
        selection_state = str(advice.get("selection_state") or "").upper()
        if selection_state == "AVOID":
            continue

        candidate_score = market_candidate_quality_score(advice)
        ranked.append((symbol, candidate_score))

    ranked.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return ranked


def choose_better_candidates(
    *,
    current_symbol: str,
    current_advice: dict[str, Any] | None,
    ranked_candidates: list[tuple[str, Decimal]],
    max_items: int = 3,
) -> list[str]:
    current_quality = market_candidate_quality_score(current_advice)

    out: list[str] = []
    for symbol, candidate_score in ranked_candidates:
        if symbol == current_symbol:
            continue
        if candidate_score <= current_quality:
            continue
        out.append(f"{symbol}:{candidate_score.quantize(Decimal('0.01'))}")
        if len(out) >= max_items:
            break

    return out



def build_rows(
    position_rows: list[dict[str, Any]],
    advice_by_symbol: dict[str, dict[str, Any]],
    *,
    stale_days: Decimal,
) -> list[RotationRow]:
    out: list[RotationRow] = []
    ranked_candidates = rank_market_candidates(advice_by_symbol)

    for position in position_rows:
        symbol = str(position["symbol"]).upper()
        advice = advice_by_symbol.get(symbol)
        source_state, source_age_days, source_reasons = classify_position_source(
            snapshot_ts=position.get("snapshot_ts_utc"),
            stale_days=stale_days,
        )
        rotation_state, pressure_score, rotation_reasons = classify_rotation(
            position_row=position,
            advice_row=advice,
            position_source_state=source_state,
        )
        reason_codes = list(dict.fromkeys(source_reasons + rotation_reasons))
        better_candidates = choose_better_candidates(
            current_symbol=symbol,
            current_advice=advice,
            ranked_candidates=ranked_candidates,
        )
        if better_candidates:
            reason_codes.append("BETTER_CANDIDATES_AVAILABLE")
        else:
            reason_codes.append("NO_BETTER_CANDIDATES_FOUND")

        out.append(
            RotationRow(
                trading_account_id=int(position["trading_account_id"]),
                account_code=str(position.get("account_code") or ""),
                account_mode=str(position.get("account_mode") or ""),
                live_trading_enabled=int(position.get("live_trading_enabled") or 0),
                position_symbol=symbol,
                venue=str(position["venue"]),
                position_snapshot_ts_utc=position.get("snapshot_ts_utc"),
                position_source_name=position.get("source_name"),
                position_source_age_days=source_age_days,
                position_source_state=source_state,
                quantity_base=dec(position.get("quantity_base")),
                available_quantity_base=dec(position.get("available_quantity_base")),
                reserved_quantity_base=dec(position.get("reserved_quantity_base")),
                position_mark_price_eur=dec(position.get("mark_price_eur")),
                position_value_eur=dec(position.get("position_value_eur")),
                paper_asof_ts_utc=None if not advice else advice.get("asof_ts_utc"),
                selection_state=None if not advice else advice.get("selection_state"),
                priority_rank=None
                if not advice or advice.get("priority_rank") is None
                else int(advice.get("priority_rank")),
                selection_score=None if not advice else dec(advice.get("selection_score")),
                setup_filter_state=None if not advice else advice.get("setup_filter_state"),
                setup_filter_reason=None if not advice else advice.get("setup_filter_reason"),
                advice_state=None if not advice else advice.get("advice_state"),
                advice_action=None if not advice else advice.get("advice_action"),
                leg_direction=None if not advice else advice.get("leg_direction"),
                entry_zone_low=None if not advice else dec(advice.get("entry_zone_low")),
                entry_zone_high=None if not advice else dec(advice.get("entry_zone_high")),
                tp_zone_low=None if not advice else dec(advice.get("tp_zone_low")),
                tp_zone_high=None if not advice else dec(advice.get("tp_zone_high")),
                invalidation_price=None if not advice else dec(advice.get("invalidation_price")),
                aplus_bucket=None if not advice else advice.get("aplus_bucket"),
                better_candidates=better_candidates,
                rotation_state=rotation_state,
                rotation_pressure_score=pressure_score,
                reason_codes=reason_codes,
            )
        )

    return out


def serialize_row(row: RotationRow) -> dict[str, Any]:
    data = asdict(row)
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = str(value)
        elif isinstance(value, datetime):
            data[key] = value.isoformat(sep=" ")
    return data


def print_table(rows: list[RotationRow]) -> None:
    headers = [
        "symbol",
        "value_eur",
        "qty",
        "src",
        "age_d",
        "selection",
        "setup_reason",
        "leg",
        "action",
        "tp_zone",
        "rotation",
        "score",
        "better",
    ]

    table: list[list[str]] = []
    for row in rows:
        tp_zone = ""
        if row.tp_zone_low is not None or row.tp_zone_high is not None:
            tp_zone = f"{dec_text(row.tp_zone_low, '0.000000')}..{dec_text(row.tp_zone_high, '0.000000')}"
        table.append(
            [
                row.position_symbol,
                dec_text(row.position_value_eur, "0.01"),
                dec_text(row.quantity_base, "0.000000"),
                row.position_source_state,
                dec_text(row.position_source_age_days, "0.01"),
                row.selection_state or "",
                row.setup_filter_reason or "",
                row.leg_direction or "",
                row.advice_action or "",
                tp_zone,
                row.rotation_state,
                str(row.rotation_pressure_score),
                ",".join(row.better_candidates[:3]),
            ]
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in table)) if table else len(headers[i])
        for i in range(len(headers))
    ]

    def fmt(row: list[str]) -> str:
        return " | ".join(row[i].ljust(widths[i]) for i in range(len(row)))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in table:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    conn = get_connection()
    try:
        position_rows = fetch_latest_position_rows(
            conn,
            venue=args.venue,
            trading_account_id=args.trading_account_id,
            limit=args.limit,
        )
        advice_by_symbol = fetch_latest_paper_advice_rows(
            conn,
            venue=args.venue,
            interval=args.interval,
        )
    finally:
        conn.close()

    rows = build_rows(
        position_rows,
        advice_by_symbol,
        stale_days=args.stale_days,
    )

    state_counts: dict[str, int] = {}
    for row in rows:
        state_counts[row.rotation_state] = state_counts.get(row.rotation_state, 0) + 1

    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=read-only account-aware rotation preview")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 db_writes=0")
    print("decision_gate=none execution_planner=none executor=none")
    print(f"venue={args.venue} interval={args.interval}")
    print(f"rows={len(rows)} stale_days={args.stale_days}")
    print(f"state_counts={json.dumps(state_counts, sort_keys=True)}")
    print()

    if args.output == "json":
        print(json.dumps([serialize_row(row) for row in rows], indent=2, sort_keys=True))
    else:
        print_table(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
