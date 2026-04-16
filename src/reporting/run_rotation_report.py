from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Human-friendly rotation report using effective overlay-adjusted selection output"
    )
    parser.add_argument("--top", type=int, default=15)
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def fetch_rows(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
        asof_ts_utc,
        symbol,
        selection_state,
        selection_bias,
        priority_rank,

        base_selection_score,
        effective_selection_score,
        effective_recommendation,

        regime_label_1h,
        regime_label_4h,
        advice_state_1h,
        advice_state_4h,

        breakout_failure_regime_tier,
        structural_conflict_type,
        htf_rule_state,
        recommendation_cap_final,

        latest_failed_breakout_ts_utc,
        hours_since_failed_breakout,
        summary_text

    FROM v_selection_latest_effective
    ORDER BY effective_selection_score DESC, symbol ASC
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def classify_action(row: dict[str, Any]) -> tuple[str, str, str]:
    rec = str(row.get("effective_recommendation") or "NO_TRADE").upper()
    selection_state = str(row.get("selection_state") or "").upper()

    if rec == "BUY":
        return (
            "BUY READY",
            "Nu tot ongeveer 6 uur",
            "Overlay-gecorrigeerde score en context laten directe allocatie toe.",
        )

    if rec == "WATCH":
        if selection_state == "PREPARE":
            return (
                "PREPARE",
                "Binnen ongeveer 4 tot 24 uur",
                "Structuur is constructief, maar overlay-context remt directe aggressie.",
            )

        if selection_state == "WATCHLIST":
            return (
                "WATCHLIST",
                "Binnen ongeveer 1 tot 3 dagen",
                "Interessant, maar nog niet rijp voor directe allocatie.",
            )

        return (
            "WATCH",
            "Binnen ongeveer 4 tot 24 uur",
            "Context is bruikbaar, maar nog niet sterk genoeg voor directe allocatie.",
        )

    if rec == "TACTICAL_ONLY":
        return (
            "TACTICAL ONLY",
            "Intraday tot ongeveer 1 dag",
            "Alleen geschikt voor kortere, tactische trades.",
        )

    return (
        "AVOID / NO TRADE",
        "-",
        "Geen duidelijke overlay-gecorrigeerde edge voor nieuwe allocatie.",
    )


def overlay_line(row: dict[str, Any]) -> str:
    parts: list[str] = []

    if row.get("breakout_failure_regime_tier"):
        parts.append(f"breakout={row['breakout_failure_regime_tier']}")

    if row.get("structural_conflict_type"):
        parts.append(f"struct={row['structural_conflict_type']}")

    if row.get("htf_rule_state"):
        parts.append(f"htf={row['htf_rule_state']}")

    if row.get("recommendation_cap_final"):
        parts.append(f"cap={row['recommendation_cap_final']}")

    if row.get("hours_since_failed_breakout") is not None and row.get("breakout_failure_regime_tier"):
        parts.append(f"hours_since_failure={row['hours_since_failed_breakout']}")

    if not parts:
        return "Geen actieve overlay-conflicten."

    return " | ".join(parts)


def structure_line(row: dict[str, Any]) -> str:
    symbol = str(row["symbol"])
    state = str(row["selection_state"])
    bias = str(row["selection_bias"])
    base_score = str(row["base_selection_score"])
    eff_score = str(row["effective_selection_score"])

    return (
        f"{symbol} staat nu op {state} / {bias}. "
        f"Base score={base_score}, effective score={eff_score}."
    )


def timing_line(row: dict[str, Any]) -> str:
    symbol = str(row["symbol"])
    advice_4h = str(row.get("advice_state_4h") or "-")
    advice_1h = str(row.get("advice_state_1h") or "-")

    return f"4h advice={advice_4h}; 1h advice={advice_1h} voor {symbol}."


def macro_line(row: dict[str, Any]) -> str:
    regime_4h = str(row.get("regime_label_4h") or "-")
    regime_1h = str(row.get("regime_label_1h") or "-")
    return f"Regime 4h={regime_4h}; regime 1h={regime_1h}."


def final_priority(row: dict[str, Any]) -> tuple[int, Decimal, str]:
    action_rank = {
        "BUY": 5,
        "WATCH": 4,
        "TACTICAL_ONLY": 3,
        "NO_TRADE": 1,
    }.get(str(row.get("effective_recommendation") or "NO_TRADE").upper(), 0)

    score = _to_decimal(row.get("effective_selection_score"), "0")
    symbol = str(row.get("symbol") or "")
    return (action_rank, score, symbol)


def render_coin_block(row: dict[str, Any]) -> str:
    symbol = str(row["symbol"])
    action_label, time_window, action_reason = classify_action(row)

    lines = [
        f"{symbol} — {action_label}",
        f"Tijdvenster: {time_window}",
        f"Structuur: {structure_line(row)}",
        f"Timing: {timing_line(row)}",
        f"Macro: {macro_line(row)}",
        f"Overlays: {overlay_line(row)}",
        f"Actie: {action_reason}",
    ]

    if row.get("summary_text"):
        lines.append(f"Samenvatting: {row['summary_text']}")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    conn = get_db_connection()

    try:
        rows = fetch_rows(conn)

        if not rows:
            print("[WARN] no effective rotation rows found")
            return 0

        snapshot_ts = rows[0]["asof_ts_utc"]
        ranked_rows = sorted(rows, key=final_priority, reverse=True)

        print("=== SYNTH ROTATION REPORT (HUMAN / EFFECTIVE) ===")
        print()
        print(f"snapshot_ts={snapshot_ts}")
        print()

        shown = 0
        for row in ranked_rows:
            if shown >= args.top:
                break

            print(render_coin_block(row))
            print("-" * 88)
            shown += 1

        counts = {
            "BUY": 0,
            "WATCH": 0,
            "TACTICAL_ONLY": 0,
            "NO_TRADE": 0,
        }

        for row in ranked_rows:
            rec = str(row.get("effective_recommendation") or "NO_TRADE").upper()
            if rec not in counts:
                rec = "NO_TRADE"
            counts[rec] += 1

        print("SUMMARY")
        print(f"buy={counts['BUY']}")
        print(f"watch={counts['WATCH']}")
        print(f"tactical_only={counts['TACTICAL_ONLY']}")
        print(f"no_trade={counts['NO_TRADE']}")

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
