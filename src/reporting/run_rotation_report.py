from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Human-friendly multi-timeframe rotation report"
    )
    parser.add_argument("--ranking-version", default="v2")
    parser.add_argument("--top", type=int, default=15)
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def fetch_rows(conn, *, ranking_version: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        interval_code,
        asof_ts_utc,
        final_rank,
        symbol,
        asset_class,
        sector,
        trade_quality_score,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        notes
    FROM vw_ranking_latest
    WHERE ranking_version = %s
      AND interval_code IN ('1h', '4h', '1d')
    ORDER BY interval_code, final_rank
    """

    with conn.cursor() as cur:
        cur.execute(sql, (ranking_version,))
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def group_by_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}

    for row in rows:
        symbol = str(row["symbol"])
        interval_code = str(row["interval_code"])

        grouped.setdefault(symbol, {})
        grouped[symbol][interval_code] = row

    return grouped


def classify_action(
    row_4h: dict[str, Any] | None,
    row_1h: dict[str, Any] | None,
    row_1d: dict[str, Any] | None,
) -> tuple[str, str, str]:
    class_4h = str((row_4h or {}).get("classification_code") or "")
    class_1h = str((row_1h or {}).get("classification_code") or "")
    class_1d = str((row_1d or {}).get("classification_code") or "")

    if class_4h in {"LEADER", "CONTINUATION_CANDIDATE"} and class_1h == "CONTINUATION_CANDIDATE":
        return (
            "BUY READY",
            "Nu tot ongeveer 6 uur",
            "Structuur en timing liggen beide redelijk goed.",
        )

    if class_4h in {"LEADER", "CONTINUATION_CANDIDATE"} and class_1h == "PULLBACK_WATCH":
        return (
            "PREPARE",
            "Binnen ongeveer 4 tot 24 uur",
            "Structuur is sterk, maar timing wacht nog op dip of reclaim.",
        )

    if class_4h == "PULLBACK_WATCH":
        return (
            "WATCHLIST",
            "Binnen ongeveer 1 tot 3 dagen",
            "Interessant, maar nog niet rijp voor directe actie.",
        )

    if class_4h in {"RANGE_TRADER", "SPECULATIVE_HIGH_BETA"}:
        return (
            "TACTICAL ONLY",
            "Intraday tot ongeveer 1 dag",
            "Alleen geschikt voor kortere, tactische trades.",
        )

    if class_1d == "PULLBACK_WATCH" and class_4h in {"NO_TRADE", "RANGE_TRADER"}:
        return (
            "WATCHLIST",
            "Binnen ongeveer 1 tot 3 dagen",
            "Dagstructuur verbetert, maar 4h bevestigt nog niet genoeg.",
        )

    return (
        "AVOID",
        "-",
        "Geen duidelijke edge voor nieuwe allocatie.",
    )


def structure_line(row_4h: dict[str, Any] | None) -> str:
    if not row_4h:
        return "Geen 4h-structuur beschikbaar."

    symbol = str(row_4h["symbol"])
    classification = str(row_4h["classification_code"])
    bucket = str(row_4h["rotation_bucket"])
    score = str(row_4h["trade_quality_score"])

    if classification == "LEADER":
        return f"{symbol} is structureel sterk op 4h en hoort nu bij de voorlopers. Score: {score}."
    if classification == "CONTINUATION_CANDIDATE":
        return f"{symbol} heeft op 4h een bruikbare continuation-structuur. Score: {score}."
    if classification == "PULLBACK_WATCH":
        return f"{symbol} is op 4h interessant, maar wacht nog op een betere pullback-entry. Score: {score}."
    if classification == "RANGE_TRADER":
        return f"{symbol} zit op 4h meer in range-gedrag dan in echte trendrotatie. Score: {score}."
    if classification == "SPECULATIVE_HIGH_BETA":
        return f"{symbol} is op 4h vooral een high-beta/speculatieve setup. Score: {score}."

    return f"{symbol} heeft op 4h nog geen overtuigende structurele allocatie-status. Bucket: {bucket}. Score: {score}."


def timing_line(row_1h: dict[str, Any] | None) -> str:
    if not row_1h:
        return "Geen 1h-timing beschikbaar."

    symbol = str(row_1h["symbol"])
    classification = str(row_1h["classification_code"])
    score = str(row_1h["trade_quality_score"])

    if classification == "CONTINUATION_CANDIDATE":
        return f"Op 1h ondersteunt timing de trend al redelijk; {symbol} hoeft niet per se op extra dip te wachten. Score: {score}."
    if classification == "PULLBACK_WATCH":
        return f"Op 1h wacht timing nog op een dip, reclaim of nettere entry voor {symbol}. Score: {score}."
    if classification == "RANGE_TRADER":
        return f"Op 1h is {symbol} momenteel vooral een range/timing-verhaal. Score: {score}."
    if classification == "SPECULATIVE_HIGH_BETA":
        return f"Op 1h is {symbol} beweeglijk en vooral tactisch bruikbaar. Score: {score}."

    return f"Op 1h geeft {symbol} nog geen sterke entry-timing voor nieuwe longs. Score: {score}."


def macro_line(row_1d: dict[str, Any] | None) -> str:
    if not row_1d:
        return "Geen 1d-context beschikbaar."

    symbol = str(row_1d["symbol"])
    classification = str(row_1d["classification_code"])
    score = str(row_1d["trade_quality_score"])

    if classification == "LEADER":
        return f"Op 1d wordt {symbol} ook macro bevestigd als leider. Score: {score}."
    if classification == "CONTINUATION_CANDIDATE":
        return f"Op 1d ondersteunt de grotere structuur {symbol} al voorzichtig. Score: {score}."
    if classification == "PULLBACK_WATCH":
        return f"Op 1d verbetert {symbol}, maar de grotere structuur wacht nog op verdere bevestiging. Score: {score}."
    if classification == "RANGE_TRADER":
        return f"Op 1d zit {symbol} nog meer in neutrale/range-context dan in volle expansie. Score: {score}."

    return f"Op 1d geeft {symbol} nog geen brede structurele bevestiging. Score: {score}."


def final_priority(
    row_4h: dict[str, Any] | None,
    row_1h: dict[str, Any] | None,
    row_1d: dict[str, Any] | None,
    action_label: str,
) -> tuple[int, Decimal, Decimal, Decimal, str]:
    action_rank = {
        "BUY READY": 5,
        "PREPARE": 4,
        "WATCHLIST": 3,
        "TACTICAL ONLY": 2,
        "AVOID": 1,
    }.get(action_label, 0)

    score_4h = _to_decimal((row_4h or {}).get("trade_quality_score"), "0")
    score_1h = _to_decimal((row_1h or {}).get("trade_quality_score"), "0")
    score_1d = _to_decimal((row_1d or {}).get("trade_quality_score"), "0")
    symbol = str((row_4h or row_1h or row_1d or {}).get("symbol") or "")

    return (action_rank, score_4h, score_1h, score_1d, symbol)


def render_coin_block(
    symbol: str,
    row_4h: dict[str, Any] | None,
    row_1h: dict[str, Any] | None,
    row_1d: dict[str, Any] | None,
) -> str:
    action_label, time_window, action_reason = classify_action(row_4h, row_1h, row_1d)

    asset_class = str(
        (row_4h or row_1h or row_1d or {}).get("asset_class") or "-"
    )
    sector = str(
        (row_4h or row_1h or row_1d or {}).get("sector") or "-"
    )

    lines = [
        f"{symbol} — {action_label}",
        f"Klasse: {asset_class} | Sector: {sector}",
        f"Tijdvenster: {time_window}",
        f"Structuur: {structure_line(row_4h)}",
        f"Timing: {timing_line(row_1h)}",
        f"Macro: {macro_line(row_1d)}",
        f"Actie: {action_reason}",
    ]

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    conn = get_db_connection()

    try:
        rows = fetch_rows(conn, ranking_version=args.ranking_version)
        grouped = group_by_symbol(rows)

        snapshot_4h = next((r["asof_ts_utc"] for r in rows if r["interval_code"] == "4h"), None)
        snapshot_1h = next((r["asof_ts_utc"] for r in rows if r["interval_code"] == "1h"), None)
        snapshot_1d = next((r["asof_ts_utc"] for r in rows if r["interval_code"] == "1d"), None)

        ranked_items: list[tuple[tuple[int, Decimal, Decimal, Decimal, str], str, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]] = []

        for symbol, by_tf in grouped.items():
            row_4h = by_tf.get("4h")
            row_1h = by_tf.get("1h")
            row_1d = by_tf.get("1d")
            action_label, _, _ = classify_action(row_4h, row_1h, row_1d)
            prio = final_priority(row_4h, row_1h, row_1d, action_label)
            ranked_items.append((prio, symbol, row_4h, row_1h, row_1d))

        ranked_items.sort(reverse=True)

        print("=== SYNTH ROTATION REPORT (HUMAN) ===")
        print()
        print(f"ranking_version={args.ranking_version}")
        print(f"snapshot_4h={snapshot_4h}")
        print(f"snapshot_1h={snapshot_1h}")
        print(f"snapshot_1d={snapshot_1d}")
        print()

        shown = 0
        for _, symbol, row_4h, row_1h, row_1d in ranked_items:
            if shown >= args.top:
                break

            print(render_coin_block(symbol, row_4h, row_1h, row_1d))
            print("-" * 88)
            shown += 1

        counts = {
            "BUY READY": 0,
            "PREPARE": 0,
            "WATCHLIST": 0,
            "TACTICAL ONLY": 0,
            "AVOID": 0,
        }

        for _, _, row_4h, row_1h, row_1d in ranked_items:
            action_label, _, _ = classify_action(row_4h, row_1h, row_1d)
            counts[action_label] += 1

        print("SUMMARY")
        print(f"buy_ready={counts['BUY READY']}")
        print(f"prepare={counts['PREPARE']}")
        print(f"watchlist={counts['WATCHLIST']}")
        print(f"tactical_only={counts['TACTICAL ONLY']}")
        print(f"avoid={counts['AVOID']}")

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
