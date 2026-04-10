from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.common.db import db_cursor
from src.reporting.human_labels import (
    derive_human_labels,
    safe_decimal_str,
    should_show_buy_fields,
    should_show_no_trade_fields,
    should_show_sell_fields,
)


DECIMAL_ZERO = Decimal("0")
TOP_TRADE_THRESHOLD = Decimal("0.65")
WATCH_THRESHOLD = Decimal("0.45")


@dataclass(slots=True)
class AssetReport:
    asset_id: int
    symbol: str
    action: str
    context_score: Decimal
    setup_bias: str
    structure_state: str
    phase_state: str
    tactical_state: str
    entry_quality: str
    current_price_eur: Decimal
    buy_zones: list[Decimal]
    sell_zones: list[Decimal]
    invalidation_level: Decimal | None
    execution_mode: str
    ladder_plan: list[str]
    trade_type: str
    short_reason: str
    bucket: str


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _safe_upper(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip().upper()


def _coalesce_text(row: dict[str, Any], keys: list[str], default: str = "") -> str:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return default


def _coalesce_decimal(row: dict[str, Any], keys: list[str], default: str = "0") -> Decimal:
    for key in keys:
        if key in row and row[key] is not None:
            return _to_decimal(row[key], default)
    return Decimal(default)


def _fetch_rows() -> list[dict[str, Any]]:
    sql = """
    WITH
    latest_decision AS (
        SELECT *
        FROM (
            SELECT
                d.*,
                ROW_NUMBER() OVER (
                    PARTITION BY d.asset_id
                    ORDER BY
                        COALESCE(d.decision_ts_utc, d.created_ts_utc) DESC,
                        d.decision_log_id DESC
                ) AS rn
            FROM decision_log d
        ) x
        WHERE x.rn = 1
    ),
    latest_advice_1d AS (
        SELECT *
        FROM (
            SELECT
                a.*,
                ROW_NUMBER() OVER (
                    PARTITION BY a.asset_id
                    ORDER BY
                        COALESCE(a.asof_ts_utc, a.created_ts_utc) DESC,
                        a.advice_state_id DESC
                ) AS rn
            FROM advice_state a
            WHERE a.interval_code = '1d'
        ) x
        WHERE x.rn = 1
    ),
    latest_advice_4h AS (
        SELECT *
        FROM (
            SELECT
                a.*,
                ROW_NUMBER() OVER (
                    PARTITION BY a.asset_id
                    ORDER BY
                        COALESCE(a.asof_ts_utc, a.created_ts_utc) DESC,
                        a.advice_state_id DESC
                ) AS rn
            FROM advice_state a
            WHERE a.interval_code = '4h'
        ) x
        WHERE x.rn = 1
    ),
    latest_signal_1d AS (
        SELECT *
        FROM (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.asset_id
                    ORDER BY
                        COALESCE(s.signal_ts_utc, s.created_ts_utc) DESC,
                        s.signal_engine_state_id DESC
                ) AS rn
            FROM signal_engine_state s
            WHERE s.interval_code = '1d'
        ) x
        WHERE x.rn = 1
    ),
    latest_signal_4h AS (
        SELECT *
        FROM (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.asset_id
                    ORDER BY
                        COALESCE(s.signal_ts_utc, s.created_ts_utc) DESC,
                        s.signal_engine_state_id DESC
                ) AS rn
            FROM signal_engine_state s
            WHERE s.interval_code = '4h'
        ) x
        WHERE x.rn = 1
    ),
    latest_signal_5m AS (
        SELECT *
        FROM (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.asset_id
                    ORDER BY
                        COALESCE(s.signal_ts_utc, s.created_ts_utc) DESC,
                        s.signal_engine_state_id DESC
                ) AS rn
            FROM signal_engine_state s
            WHERE s.interval_code = '5m'
        ) x
        WHERE x.rn = 1
    ),
    latest_close_1d AS (
        SELECT *
        FROM (
            SELECT
                c.asset_id,
                c.close_price AS close_1d,
                ROW_NUMBER() OVER (
                    PARTITION BY c.asset_id
                    ORDER BY c.close_ts_utc DESC
                ) AS rn
            FROM obs_market_candle c
            WHERE c.venue = 'bitvavo'
              AND c.interval_code = '1d'
        ) x
        WHERE x.rn = 1
    ),
    latest_close_4h AS (
        SELECT *
        FROM (
            SELECT
                c.asset_id,
                c.close_price AS close_4h,
                ROW_NUMBER() OVER (
                    PARTITION BY c.asset_id
                    ORDER BY c.close_ts_utc DESC
                ) AS rn
            FROM obs_market_candle c
            WHERE c.venue = 'bitvavo'
              AND c.interval_code = '4h'
        ) x
        WHERE x.rn = 1
    ),
    latest_close_5m AS (
        SELECT *
        FROM (
            SELECT
                c.asset_id,
                c.close_price AS close_5m,
                ROW_NUMBER() OVER (
                    PARTITION BY c.asset_id
                    ORDER BY c.close_ts_utc DESC
                ) AS rn
            FROM obs_market_candle c
            WHERE c.venue = 'bitvavo'
              AND c.interval_code = '5m'
        ) x
        WHERE x.rn = 1
    )
    SELECT
        a.asset_id,
        a.symbol,

        d.action_state AS decision_action,
        d.summary_text AS decision_summary,

        a1.advice_state AS advice_action_1d,
        a1.regime_label AS advice_setup_bias_1d,
        a1.opportunity_score AS advice_context_score_1d,
        a1.risk_score AS advice_risk_score_1d,
        a1.summary_text AS advice_summary_1d,

        a4.advice_state AS advice_action_4h,
        a4.regime_label AS advice_setup_bias_4h,
        a4.opportunity_score AS advice_context_score_4h,
        a4.risk_score AS advice_risk_score_4h,
        a4.summary_text AS advice_summary_4h,
        a4.time_horizon_hint AS time_horizon_hint_4h,

        s1.trend_signal AS trend_signal_1d,
        s1.phase_signal AS phase_signal_1d,
        s1.setup_signal AS setup_signal_1d,

        s4.trend_signal AS trend_signal_4h,
        s4.phase_signal AS phase_signal_4h,
        s4.setup_signal AS setup_signal_4h,
        s4.signal_confidence AS signal_confidence_4h,
        s4.expansion_position_score AS expansion_position_score_4h,
        s4.pullback_quality_score AS pullback_quality_score_4h,
        s4.late_trend_flag AS late_trend_flag_4h,

        s5.trend_signal AS trend_signal_5m,
        s5.phase_signal AS phase_signal_5m,
        s5.setup_signal AS setup_signal_5m,
        s5.rotation_signal AS rotation_signal_5m,
        s5.compass_signal AS compass_signal_5m,

        c1.close_1d,
        c4.close_4h,
        c5.close_5m

    FROM asset a
    LEFT JOIN latest_decision d
        ON d.asset_id = a.asset_id
    LEFT JOIN latest_advice_1d a1
        ON a1.asset_id = a.asset_id
    LEFT JOIN latest_advice_4h a4
        ON a4.asset_id = a.asset_id
    LEFT JOIN latest_signal_1d s1
        ON s1.asset_id = a.asset_id
    LEFT JOIN latest_signal_4h s4
        ON s4.asset_id = a.asset_id
    LEFT JOIN latest_signal_5m s5
        ON s5.asset_id = a.asset_id
    LEFT JOIN latest_close_1d c1
        ON c1.asset_id = a.asset_id
    LEFT JOIN latest_close_4h c4
        ON c4.asset_id = a.asset_id
    LEFT JOIN latest_close_5m c5
        ON c5.asset_id = a.asset_id
    WHERE a4.asset_id IS NOT NULL
       OR s4.asset_id IS NOT NULL
       OR d.asset_id IS NOT NULL
    ORDER BY a.symbol ASC
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        return list(cur.fetchall())


def _derive_action(row: dict[str, Any], context_score: Decimal) -> str:
    decision_action = _safe_upper(row.get("decision_action"))
    advice_action_4h = _safe_upper(row.get("advice_action_4h"))
    advice_action_1d = _safe_upper(row.get("advice_action_1d"))

    buy_aliases = {"BUY", "ACCUMULATE", "ADD", "TRIGGERED"}
    sell_aliases = {"SELL", "REDUCE", "EXIT", "TRIM"}
    hold_aliases = {"HOLD", "WATCH", "PREPARE", "NO_ACTION", "AVOID"}

    for candidate in (decision_action, advice_action_4h, advice_action_1d):
        if candidate in buy_aliases:
            return "BUY"
        if candidate in sell_aliases:
            return "SELL"
        if candidate in hold_aliases:
            return "HOLD"

    if context_score >= TOP_TRADE_THRESHOLD:
        return "BUY"
    return "HOLD"


def _derive_structure_state(row: dict[str, Any]) -> str:
    trend_4h = _safe_upper(row.get("trend_signal_4h"))
    trend_1d = _safe_upper(row.get("trend_signal_1d"))

    blob = " ".join([trend_4h, trend_1d])

    if "TREND_UP" in blob:
        return "TREND_UP"
    if "TREND_DOWN" in blob:
        return "TREND_DOWN"
    if "SIDEWAYS" in blob or "RANGE" in blob:
        return "RANGE"
    return "TRANSITION"


def _derive_phase_state(row: dict[str, Any]) -> str:
    for key in ("phase_signal_4h", "phase_signal_1d", "phase_signal_5m"):
        value = _safe_upper(row.get(key))
        if "CONVERGENCE" in value:
            return "CONVERGENCE"
        if "COMPRESSION" in value:
            return "COMPRESSION"
        if "EXPANSION" in value:
            return "EXPANSION"
        if "INTEGRATION" in value or "RESET" in value:
            return "INTEGRATION"
    return "INTEGRATION"


def _derive_tactical_state(row: dict[str, Any], structure_state: str) -> str:
    setup_5m = _safe_upper(row.get("setup_signal_5m"))
    trend_5m = _safe_upper(row.get("trend_signal_5m"))
    phase_5m = _safe_upper(row.get("phase_signal_5m"))
    blob = " ".join([setup_5m, trend_5m, phase_5m])

    if "PULLBACK" in blob or "RECLAIM" in blob:
        return "PULLBACK"
    if "REJECTION" in blob:
        return "REJECTION"
    if "BREAKOUT_FAILURE" in blob or "FAILURE" in blob:
        return "FAILURE"
    if "BREAKOUT" in blob:
        return "BREAKOUT_ATTEMPT"
    if "RANGE" in blob or structure_state == "RANGE":
        return "RANGE"

    return "PULLBACK"


def _derive_entry_quality(
    context_score: Decimal,
    structure_state: str,
    tactical_state: str,
    trade_quality_score: Decimal,
) -> str:
    if trade_quality_score >= TOP_TRADE_THRESHOLD and structure_state in {"TREND_UP", "RANGE"}:
        if tactical_state in {"PULLBACK", "REJECTION", "RANGE"}:
            return "HIGH"

    if context_score >= WATCH_THRESHOLD:
        return "MEDIUM"

    return "LOW"


def _pick_price_anchor(row: dict[str, Any]) -> Decimal:
    for key in ("close_5m", "close_4h", "close_1d"):
        value = _to_decimal(row.get(key), "0")
        if value > DECIMAL_ZERO:
            return value
    return DECIMAL_ZERO


def _round_price(value: Decimal) -> Decimal:
    if value <= DECIMAL_ZERO:
        return value
    return value.quantize(Decimal("0.00000001"))


def _make_buy_zones(current_price: Decimal, trade_type: str) -> list[Decimal]:
    if current_price <= DECIMAL_ZERO:
        return []

    if trade_type == "TREND":
        offsets = [Decimal("0.020"), Decimal("0.050")]
    elif trade_type == "LATE_TREND_PULLBACK":
        offsets = [Decimal("0.030"), Decimal("0.060")]
    elif trade_type == "RANGE":
        offsets = [Decimal("0.015"), Decimal("0.030")]
    else:
        return []

    return [_round_price(current_price * (Decimal("1") - x)) for x in offsets]


def _make_sell_zones(current_price: Decimal, trade_type: str) -> list[Decimal]:
    if current_price <= DECIMAL_ZERO:
        return []

    if trade_type == "TREND":
        offsets = [Decimal("0.050"), Decimal("0.100")]
    elif trade_type == "LATE_TREND_PULLBACK":
        offsets = [Decimal("0.050"), Decimal("0.100")]
    elif trade_type == "RANGE":
        offsets = [Decimal("0.015"), Decimal("0.030")]
    else:
        return []

    return [_round_price(current_price * (Decimal("1") + x)) for x in offsets]


def _make_invalidation_level(current_price: Decimal, trade_type: str) -> Decimal | None:
    if current_price <= DECIMAL_ZERO:
        return None

    if trade_type == "TREND":
        return _round_price(current_price * Decimal("0.94"))
    if trade_type == "LATE_TREND_PULLBACK":
        return _round_price(current_price * Decimal("0.93"))
    if trade_type == "RANGE":
        return _round_price(current_price * Decimal("0.955"))
    return None


def _compute_trade_quality_score(row: dict[str, Any]) -> Decimal:
    context_score = _coalesce_decimal(row, ["advice_context_score_4h", "advice_context_score_1d"], "0")
    pullback_quality_score = _coalesce_decimal(row, ["pullback_quality_score_4h"], "0")
    expansion_position_score = _coalesce_decimal(row, ["expansion_position_score_4h"], "0")

    score = (
        Decimal("0.4") * context_score
        + Decimal("0.3") * pullback_quality_score
        + Decimal("0.3") * expansion_position_score
    )
    return score.quantize(Decimal("0.000001"))


def _infer_trade_type(row: dict[str, Any], structure_state: str) -> str:
    advice = _safe_upper(row.get("advice_action_4h"))
    setup = _safe_upper(row.get("setup_signal_4h"))
    late_trend_flag = bool(row.get("late_trend_flag_4h"))

    if late_trend_flag:
        return "LATE_TREND_PULLBACK"

    if advice in {"BUY", "ACCUMULATE", "ADD", "TRIGGERED"}:
        return "TREND"

    if structure_state == "RANGE" or advice in {"WATCH", "PREPARE"}:
        return "RANGE"

    if setup in {"CONFIRMED", "READY"}:
        return "TREND"

    return "WAIT"


def _derive_execution_mode(action: str, trade_type: str) -> str:
    if action == "SELL":
        return "WAIT"

    if trade_type == "TREND":
        return "PASSIVE"
    if trade_type == "LATE_TREND_PULLBACK":
        return "WAIT"
    if trade_type == "RANGE":
        return "PASSIVE_REPRICE"
    return "WAIT"


def _make_ladder_plan(action: str, buy_zones: list[Decimal], sell_zones: list[Decimal]) -> list[str]:
    if action == "BUY" and buy_zones:
        weights = ["40%", "60%"] if len(buy_zones) == 2 else ["20%", "40%", "40%"]
        return [f"{weights[i]} @ {buy_zones[i]}" for i in range(min(len(weights), len(buy_zones)))]

    if action == "SELL" and sell_zones:
        weights = ["50%", "50%"] if len(sell_zones) == 2 else ["30%", "35%", "35%"]
        return [f"{weights[i]} @ {sell_zones[i]}" for i in range(min(len(weights), len(sell_zones)))]

    return ["WAIT"]


def _make_short_reason(
    action: str,
    trade_type: str,
    structure_state: str,
    phase_state: str,
    tactical_state: str,
) -> str:
    if action == "BUY":
        return (
            f"{trade_type} candidate within {structure_state} / {phase_state}; tactical state={tactical_state.lower()}.\n"
            f"Structure is usable, but timing still depends on cleaner pullback quality."
        )

    if action == "SELL":
        return (
            "Structure is weak or late for fresh upside positioning.\n"
            "Reduce into strength rather than adding fresh longs."
        )

    return (
        "Current setup is informative but not yet strong enough to justify new exposure.\n"
        "Stay selective and preserve optionality."
    )


def _classify_bucket(action: str, trade_type: str, trade_quality_score: Decimal) -> str:
    if action == "SELL":
        return "NO_TRADE"

    if trade_type == "TREND" and trade_quality_score >= TOP_TRADE_THRESHOLD:
        return "TOP"

    if trade_quality_score >= WATCH_THRESHOLD and trade_type in {"TREND", "LATE_TREND_PULLBACK", "RANGE"}:
        return "WATCH"

    return "NO_TRADE"


def _build_report(row: dict[str, Any]) -> AssetReport:
    context_score = max(
        _coalesce_decimal(row, ["advice_context_score_4h"], "0"),
        _coalesce_decimal(row, ["advice_context_score_1d"], "0"),
    )

    structure_state = _derive_structure_state(row)
    phase_state = _derive_phase_state(row)
    trade_quality_score = _compute_trade_quality_score(row)
    trade_type = _infer_trade_type(row, structure_state)
    tactical_state = _derive_tactical_state(row, structure_state)
    action = _derive_action(row, context_score)
    entry_quality = _derive_entry_quality(context_score, structure_state, tactical_state, trade_quality_score)

    current_price = _pick_price_anchor(row)
    buy_zones = _make_buy_zones(current_price, trade_type)
    sell_zones = _make_sell_zones(current_price, trade_type)
    invalidation_level = _make_invalidation_level(current_price, trade_type)
    execution_mode = _derive_execution_mode(action, trade_type)
    ladder_plan = _make_ladder_plan(action, buy_zones, sell_zones)
    bucket = _classify_bucket(action, trade_type, trade_quality_score)

    setup_bias = _coalesce_text(
        row,
        ["advice_setup_bias_4h", "advice_setup_bias_1d"],
        default="NEUTRAL",
    ).upper()

    short_reason = _make_short_reason(
        action=action,
        trade_type=trade_type,
        structure_state=structure_state,
        phase_state=phase_state,
        tactical_state=tactical_state,
    )

    return AssetReport(
        asset_id=int(row["asset_id"]),
        symbol=str(row["symbol"]),
        action=action,
        context_score=trade_quality_score,
        setup_bias=setup_bias,
        structure_state=structure_state,
        phase_state=phase_state,
        tactical_state=tactical_state,
        entry_quality=entry_quality,
        current_price_eur=current_price,
        buy_zones=buy_zones,
        sell_zones=sell_zones,
        invalidation_level=invalidation_level,
        execution_mode=execution_mode,
        ladder_plan=ladder_plan,
        trade_type=trade_type,
        short_reason=short_reason,
        bucket=bucket,
    )


def _sort_key(report: AssetReport) -> tuple[Decimal, int, int, str]:
    entry_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(report.entry_quality, 0)
    structure_rank = {
        "TREND_UP": 3,
        "RANGE": 2,
        "TRANSITION": 1,
        "TREND_DOWN": 0,
    }.get(report.structure_state, 0)
    return (
        report.context_score,
        entry_rank,
        structure_rank,
        report.symbol,
    )


def _first_or_none(levels: list[Decimal], index: int) -> str:
    if len(levels) <= index:
        return "-"
    return str(levels[index])


def _print_human_section(title: str, reports: list[AssetReport]) -> None:
    print(title)
    print()

    if not reports:
        print("(none)")
        print()
        return

    for report in reports:
        labels = derive_human_labels(report)

        print(
            f"{report.symbol} | {labels['human_bucket']} | score={report.context_score} | "
            f"{report.structure_state} | {labels['human_execution_label']}"
        )
        print(
            f"Action: {labels['human_action']} | "
            f"Tone: {labels['ui_tone']} | "
            f"Priority: {labels['ui_priority']}"
        )
        print(
            f"Bias: {report.setup_bias} | Phase: {report.phase_state} | "
            f"Entry: {report.entry_quality} | Type: {report.trade_type}"
        )

        if should_show_buy_fields(report):
            print(f"Buy now: {_first_or_none(report.buy_zones, 0)}")
            print(f"Deeper buy: {_first_or_none(report.buy_zones, 1)}")

        if should_show_sell_fields(report):
            print(f"Sell first: {_first_or_none(report.sell_zones, 0)}")

        if should_show_no_trade_fields(report):
            print("Buy now: -")
            print("Deeper buy: -")
            print("Sell first: -")

        print(f"Invalidation: {safe_decimal_str(report.invalidation_level)}")
        print(f"Why: {labels['one_liner']}")
        print("-" * 72)

    print()


def _format_levels(levels: list[Decimal]) -> str:
    if not levels:
        return "[]"
    return "[" + ", ".join(str(x) for x in levels) + "]"


def _print_extended_bucket(title: str, reports: list[AssetReport]) -> None:
    print(title)
    print()

    if not reports:
        print("(none)")
        print()
        return

    for report in reports:
        labels = derive_human_labels(report)

        print(f"{report.symbol} | {labels['human_bucket']} | score={report.context_score}")
        print(
            f"Structure: {report.structure_state} / {report.phase_state} / bias={report.setup_bias}"
        )
        print(
            f"Tactical: {report.tactical_state} / entry_quality={report.entry_quality} / trade_type={report.trade_type}"
        )
        print(
            f"Plan: Buy={_format_levels(report.buy_zones)} | Sell={_format_levels(report.sell_zones)}"
        )
        print(f"Invalidation: {safe_decimal_str(report.invalidation_level)}")
        print(
            f"Execution: {labels['human_execution_label']} | Ladder={'; '.join(report.ladder_plan)}"
        )
        print("Reason:")
        print(report.short_reason)
        print(labels["one_liner"])
        print("-" * 72)

    print()


def main() -> int:
    rows = _fetch_rows()
    reports = [_build_report(row) for row in rows]
    reports.sort(key=_sort_key, reverse=True)

    top_trades = [r for r in reports if r.bucket == "TOP"]
    active_watch = [r for r in reports if r.bucket == "WATCH"]
    no_trade = [r for r in reports if r.bucket == "NO_TRADE"]

    print("=== LIVE TRADE REPORT (HUMAN) ===")
    print()
    _print_human_section("🔥 EXECUTE NOW", top_trades)
    _print_human_section("👀 ACTIVE WATCH", active_watch)
    _print_human_section("❌ NO TRADE", no_trade)

    print("=== LIVE TRADE REPORT (EXTENDED DETAIL) ===")
    print()
    _print_extended_bucket("🔥 TOP TRADES (EXECUTE NOW)", top_trades)
    _print_extended_bucket("👀 ACTIVE WATCH", active_watch)
    _print_extended_bucket("❌ NO TRADE", no_trade)

    print("SUMMARY")
    print(f"buy_now={len([r for r in reports if derive_human_labels(r)['human_bucket'] == 'BUY NOW'])}")
    print(f"watch_buy={len([r for r in reports if derive_human_labels(r)['human_bucket'] == 'WATCH BUY'])}")
    print(f"reduce_sell={len([r for r in reports if derive_human_labels(r)['human_bucket'] == 'REDUCE / SELL'])}")
    print(f"no_trade={len([r for r in reports if derive_human_labels(r)['human_bucket'] == 'NO TRADE'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
