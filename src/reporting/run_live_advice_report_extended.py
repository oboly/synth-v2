from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.common.db import db_cursor
from src.reporting.presentation import (
    derive_human_action,
    derive_human_bucket,
    derive_human_execution_label,
    derive_one_liner,
    derive_ui_priority,
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
        d.summary_text AS decision_summary_text,

        a1.advice_state AS advice_state_1d,
        a1.regime_label AS regime_label_1d,
        a1.opportunity_score AS opportunity_score_1d,
        a1.risk_score AS advice_risk_score_1d,
        a1.summary_text AS advice_summary_text_1d,

        a4.advice_state AS advice_state_4h,
        a4.regime_label AS regime_label_4h,
        a4.opportunity_score AS opportunity_score_4h,
        a4.risk_score AS advice_risk_score_4h,
        a4.summary_text AS advice_summary_text_4h,

        s1.trend_signal AS trend_signal_1d,
        s1.phase_signal AS phase_signal_1d,
        s1.setup_signal AS setup_signal_1d,
        s1.signal_confidence AS signal_confidence_1d,
        s1.reason_text AS reason_text_1d,

        s4.trend_signal AS trend_signal_4h,
        s4.phase_signal AS phase_signal_4h,
        s4.setup_signal AS setup_signal_4h,
        s4.signal_confidence AS signal_confidence_4h,
        s4.reason_text AS reason_text_4h,

        s5.trend_signal AS trend_signal_5m,
        s5.phase_signal AS phase_signal_5m,
        s5.setup_signal AS setup_signal_5m,
        s5.signal_confidence AS signal_confidence_5m,
        s5.reason_text AS reason_text_5m,

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
    WHERE d.asset_id IS NOT NULL
       OR a4.asset_id IS NOT NULL
       OR s4.asset_id IS NOT NULL
    ORDER BY a.symbol ASC
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        return list(cur.fetchall())


def _derive_action(row: dict[str, Any], context_score: Decimal) -> str:
    decision_action = _safe_upper(row.get("decision_action"))
    advice_state_4h = _safe_upper(row.get("advice_state_4h"))
    advice_state_1d = _safe_upper(row.get("advice_state_1d"))

    for candidate in (decision_action, advice_state_4h, advice_state_1d):
        if candidate in {"BUY", "SELL", "HOLD"}:
            return candidate

    trend_4h = _safe_upper(row.get("trend_signal_4h"))
    trend_1d = _safe_upper(row.get("trend_signal_1d"))

    if context_score >= TOP_TRADE_THRESHOLD and ("UP" in trend_4h or "UP" in trend_1d):
        return "BUY"

    if "DOWN" in trend_4h and context_score < WATCH_THRESHOLD:
        return "SELL"

    return "HOLD"


def _derive_structure_state(row: dict[str, Any]) -> str:
    trend_4h = _safe_upper(row.get("trend_signal_4h"))
    trend_1d = _safe_upper(row.get("trend_signal_1d"))

    blob = " ".join([trend_4h, trend_1d])

    if "RANGE" in blob:
        return "RANGE"
    if "DOWN" in blob:
        return "TREND_DOWN"
    if "UP" in blob:
        return "TREND_UP"
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
    reason_5m = _safe_upper(row.get("reason_text_5m"))

    blob = " ".join([setup_5m, trend_5m, reason_5m])

    if "REJECTION" in blob:
        return "REJECTION"
    if "FAILURE" in blob:
        return "FAILURE"
    if "BREAKOUT" in blob:
        return "BREAKOUT_ATTEMPT"
    if "RANGE" in blob:
        return "RANGE"
    if "PULLBACK" in blob or "RECLAIM" in blob:
        return "PULLBACK"

    if structure_state == "TREND_DOWN":
        return "REJECTION"
    if structure_state == "RANGE":
        return "RANGE"
    return "PULLBACK"


def _derive_entry_quality(
    context_score: Decimal,
    structure_state: str,
    tactical_state: str,
) -> str:
    if context_score >= TOP_TRADE_THRESHOLD and structure_state in {"TREND_UP", "RANGE"}:
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


def _make_buy_zones(
    current_price: Decimal,
    structure_state: str,
    phase_state: str,
) -> list[Decimal]:
    if current_price <= DECIMAL_ZERO:
        return []

    if structure_state == "TREND_UP":
        if phase_state == "EXPANSION":
            offsets = [Decimal("0.020"), Decimal("0.035"), Decimal("0.050")]
        else:
            offsets = [Decimal("0.010"), Decimal("0.0225"), Decimal("0.035")]
    elif structure_state == "RANGE":
        offsets = [Decimal("0.015"), Decimal("0.030"), Decimal("0.045")]
    else:
        offsets = [Decimal("0.025"), Decimal("0.040"), Decimal("0.060")]

    return [_round_price(current_price * (Decimal("1") - x)) for x in offsets]


def _make_sell_zones(
    current_price: Decimal,
    structure_state: str,
) -> list[Decimal]:
    if current_price <= DECIMAL_ZERO:
        return []

    if structure_state == "TREND_UP":
        offsets = [Decimal("0.025"), Decimal("0.050"), Decimal("0.080")]
    elif structure_state == "RANGE":
        offsets = [Decimal("0.015"), Decimal("0.030"), Decimal("0.045")]
    else:
        offsets = [Decimal("0.020"), Decimal("0.040"), Decimal("0.060")]

    return [_round_price(current_price * (Decimal("1") + x)) for x in offsets]


def _make_invalidation_level(
    current_price: Decimal,
    structure_state: str,
) -> Decimal | None:
    if current_price <= DECIMAL_ZERO:
        return None

    if structure_state == "TREND_UP":
        return _round_price(current_price * Decimal("0.94"))
    if structure_state == "RANGE":
        return _round_price(current_price * Decimal("0.955"))
    return _round_price(current_price * Decimal("0.92"))


def _derive_execution_mode(
    action: str,
    context_score: Decimal,
    structure_state: str,
    tactical_state: str,
) -> str:
    if action != "BUY":
        return "WAIT"

    if context_score >= TOP_TRADE_THRESHOLD and tactical_state in {"PULLBACK", "REJECTION"}:
        return "PASSIVE_REPRICE"

    if (
        context_score >= TOP_TRADE_THRESHOLD
        and structure_state == "TREND_UP"
        and tactical_state == "BREAKOUT_ATTEMPT"
    ):
        return "AGGRESSIVE_LIMIT"

    if context_score >= WATCH_THRESHOLD:
        return "PASSIVE"

    return "WAIT"


def _derive_trade_type(
    structure_state: str,
    tactical_state: str,
) -> str:
    if structure_state == "TREND_UP":
        return "TREND"
    if structure_state == "RANGE":
        return "RANGE"
    if tactical_state == "FAILURE":
        return "REVERSAL"
    return "WAIT"


def _make_ladder_plan(
    action: str,
    execution_mode: str,
    buy_zones: list[Decimal],
    sell_zones: list[Decimal],
) -> list[str]:
    if action == "BUY" and buy_zones:
        if execution_mode == "AGGRESSIVE_LIMIT":
            weights = ["40%", "35%", "25%"]
        else:
            weights = ["20%", "40%", "40%"]
        return [
            f"{weights[i]} @ {buy_zones[i]}"
            for i in range(min(len(buy_zones), 3))
        ]

    if action == "SELL" and sell_zones:
        weights = ["30%", "35%", "35%"]
        return [
            f"{weights[i]} @ {sell_zones[i]}"
            for i in range(min(len(sell_zones), 3))
        ]

    return ["WAIT"]


def _make_short_reason(
    action: str,
    structure_state: str,
    phase_state: str,
    tactical_state: str,
    execution_mode: str,
    row: dict[str, Any],
) -> str:
    advice_text = _coalesce_text(
        row,
        ["advice_summary_text_4h", "advice_summary_text_1d", "decision_summary_text", "reason_text_4h"],
        default="",
    )

    if action == "BUY":
        base = (
            f"{structure_state} with {phase_state.lower()} context; tactical state={tactical_state.lower()}.\n"
            f"Use {execution_mode.lower()} execution because structure leads and 5m only refines timing."
        )
        if advice_text:
            return f"{base}\n{advice_text}"
        return base

    if action == "SELL":
        return (
            "Structure is not supportive for fresh risk-on continuation.\n"
            "Use staged exits into strength rather than forcing a market chase."
        )

    if advice_text:
        return f"Structure clarity is insufficient or reward/risk is weak.\n{advice_text}"

    return (
        "Structure clarity is insufficient or reward/risk is weak.\n"
        "Preserve optionality and wait for cleaner alignment."
    )


def _classify_bucket(
    action: str,
    context_score: Decimal,
    entry_quality: str,
    structure_state: str,
) -> str:
    if action == "BUY" and context_score > TOP_TRADE_THRESHOLD and entry_quality == "HIGH":
        return "TOP"
    if action == "SELL":
        return "REDUCE"
    if context_score >= WATCH_THRESHOLD and structure_state in {"TREND_UP", "RANGE", "TRANSITION"}:
        return "WATCH"
    return "NO_TRADE"


def _build_report(row: dict[str, Any]) -> AssetReport:
    context_score = max(
        _coalesce_decimal(row, ["opportunity_score_4h"], "0"),
        _coalesce_decimal(row, ["opportunity_score_1d"], "0"),
        _coalesce_decimal(row, ["signal_confidence_4h"], "0"),
        _coalesce_decimal(row, ["signal_confidence_1d"], "0"),
    )

    action = _derive_action(row, context_score)
    structure_state = _derive_structure_state(row)
    phase_state = _derive_phase_state(row)
    tactical_state = _derive_tactical_state(row, structure_state)
    entry_quality = _derive_entry_quality(context_score, structure_state, tactical_state)

    current_price = _pick_price_anchor(row)
    buy_zones = _make_buy_zones(current_price, structure_state, phase_state)
    sell_zones = _make_sell_zones(current_price, structure_state)
    invalidation_level = _make_invalidation_level(current_price, structure_state)
    execution_mode = _derive_execution_mode(action, context_score, structure_state, tactical_state)
    trade_type = _derive_trade_type(structure_state, tactical_state)
    ladder_plan = _make_ladder_plan(action, execution_mode, buy_zones, sell_zones)
    bucket = _classify_bucket(action, context_score, entry_quality, structure_state)

    setup_bias = _coalesce_text(
        row,
        ["regime_label_4h", "regime_label_1d"],
        default="NEUTRAL",
    ).upper()

    short_reason = _make_short_reason(
        action=action,
        structure_state=structure_state,
        phase_state=phase_state,
        tactical_state=tactical_state,
        execution_mode=execution_mode,
        row=row,
    )

    return AssetReport(
        asset_id=int(row["asset_id"]),
        symbol=str(row["symbol"]),
        action=action,
        context_score=context_score,
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


def _sort_key(report: AssetReport) -> tuple[int, Decimal, int, int, str]:
    entry_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(report.entry_quality, 0)
    structure_rank = {
        "TREND_UP": 3,
        "RANGE": 2,
        "TRANSITION": 1,
        "TREND_DOWN": 0,
    }.get(report.structure_state, 0)
    return (
        derive_ui_priority(report),
        report.context_score,
        entry_rank,
        structure_rank,
        report.symbol,
    )


def _format_levels(levels: list[Decimal]) -> str:
    if not levels:
        return "[]"
    return "[" + ", ".join(str(x) for x in levels) + "]"


def _first_or_none(levels: list[Decimal], index: int) -> str:
    if len(levels) <= index:
        return "-"
    return str(levels[index])


def _bucket_title_for_print(bucket_name: str) -> str:
    mapping = {
        "BUY NOW": "🔥 BUY NOW",
        "WATCH BUY": "👀 WATCH BUY",
        "REDUCE / SELL": "⚠ REDUCE / SELL INTO STRENGTH",
        "NO TRADE": "❌ NO TRADE",
    }
    return mapping.get(bucket_name, bucket_name)


def _print_human_section(title: str, reports: list[AssetReport]) -> None:
    print(title)
    print()

    if not reports:
        print("(none)")
        print()
        return

    for report in reports:
        human_action = derive_human_action(report)
        human_execution = derive_human_execution_label(report)
        one_liner = derive_one_liner(report)

        print(
            f"{report.symbol} | {human_action} | score={report.context_score} | "
            f"{report.structure_state} | {human_execution}"
        )
        print(f"Bias: {report.setup_bias} | Phase: {report.phase_state} | Entry: {report.entry_quality}")

        if should_show_buy_fields(report):
            print(f"Buy now: {_first_or_none(report.buy_zones, 0)}")
            print(f"Deeper buy: {_first_or_none(report.buy_zones, 1)}")
            print(f"Sell first: {_first_or_none(report.sell_zones, 0)}")
        elif should_show_sell_fields(report):
            print(f"Sell first: {_first_or_none(report.sell_zones, 0)}")
            print(f"Sell higher: {_first_or_none(report.sell_zones, 1)}")
            print("Fresh longs: avoid")
        elif should_show_no_trade_fields(report):
            print("Action: no valid setup")
            print("Fresh entries: avoid")
            print(f"Next useful area: {_first_or_none(report.buy_zones, 0)}")

        print(f"Invalidation: {report.invalidation_level if report.invalidation_level is not None else '-'}")
        print(f"Why: {one_liner}")
        print("-" * 72)
    print()


def _print_extended_bucket(title: str, reports: list[AssetReport]) -> None:
    print(title)
    print()

    if not reports:
        print("(none)")
        print()
        return

    for report in reports:
        print(f"{report.symbol} | {report.action} | score={report.context_score}")
        print(
            f"Structure: {report.structure_state} / {report.phase_state} / bias={report.setup_bias}"
        )
        print(
            f"Tactical: {report.tactical_state} / entry_quality={report.entry_quality} / trade_type={report.trade_type}"
        )
        print(
            f"Plan: Buy={_format_levels(report.buy_zones)} | Sell={_format_levels(report.sell_zones)}"
        )
        print(f"Invalidation: {report.invalidation_level}")
        print(
            f"Execution: {report.execution_mode} | Ladder={'; '.join(report.ladder_plan)}"
        )
        print("Reason:")
        print(report.short_reason)
        print("-" * 72)
    print()


def main() -> int:
    rows = _fetch_rows()
    reports = [_build_report(row) for row in rows]
    reports.sort(key=_sort_key, reverse=True)

    buy_now = [r for r in reports if derive_human_bucket(r) == "BUY NOW"]
    watch_buy = [r for r in reports if derive_human_bucket(r) == "WATCH BUY"]
    reduce_sell = [r for r in reports if derive_human_bucket(r) == "REDUCE / SELL"]
    no_trade = [r for r in reports if derive_human_bucket(r) == "NO TRADE"]

    print("=== LIVE TRADE REPORT (HUMAN) ===")
    print()
    _print_human_section(_bucket_title_for_print("BUY NOW"), buy_now)
    _print_human_section(_bucket_title_for_print("WATCH BUY"), watch_buy)
    _print_human_section(_bucket_title_for_print("REDUCE / SELL"), reduce_sell)
    _print_human_section(_bucket_title_for_print("NO TRADE"), no_trade)

    print("=== LIVE TRADE REPORT (EXTENDED DETAIL) ===")
    print()
    _print_extended_bucket("🔥 BUY NOW", buy_now)
    _print_extended_bucket("👀 WATCH BUY", watch_buy)
    _print_extended_bucket("⚠ REDUCE / SELL INTO STRENGTH", reduce_sell)
    _print_extended_bucket("❌ NO TRADE", no_trade)

    print("SUMMARY")
    print(f"buy_now={len(buy_now)}")
    print(f"watch_buy={len(watch_buy)}")
    print(f"reduce_sell={len(reduce_sell)}")
    print(f"no_trade={len(no_trade)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
