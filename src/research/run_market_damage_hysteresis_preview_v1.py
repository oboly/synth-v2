from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "market_damage_hysteresis_preview_v1"
REPORT_VERSION = "0.1"


@dataclass(frozen=True)
class PreviewRow:
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: datetime
    selection_state: str
    priority_rank: int | None
    selection_score: Decimal | None
    btc_prior_24h: Decimal | None
    current_setup_filter_state: str
    current_setup_filter_reason: str
    proposed_market_context_state: str
    proposed_setup_effect: str
    proposed_reason: str
    would_change_current_market_damage_fail: bool
    notes: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Preview current hard MARKET_DAMAGE_RISK behavior against a proposed "
            "BTC prior-24h hysteresis/caution-band. Read-only."
        )
    )
    p.add_argument("--venue", default="bitvavo")
    p.add_argument("--filter-name", default="trade_setup_filter_v1")
    p.add_argument("--filter-version", default="1.1")
    p.add_argument("--asset-suitability-mode", default="candidate_weak_set")
    p.add_argument("--current-hard-min", default="-0.015")
    p.add_argument("--proposed-hard-min", default="-0.025")
    p.add_argument("--proposed-caution-min", default="-0.015")
    p.add_argument("--proposed-clear-above", default="-0.010")
    p.add_argument("--current-overheat-max", default="0.015")
    p.add_argument("--limit", type=int, default=80)
    p.add_argument("--output", choices=("table", "json"), default="table")
    return p.parse_args()


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fmt_decimal(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    return str(value.quantize(Decimal(places)))


def fetch_latest_filter_rows(
    conn: Any,
    *,
    venue: str,
    filter_name: str,
    filter_version: str,
    asset_suitability_mode: str,
    limit: int,
) -> list[dict[str, Any]]:
    sql = """
    WITH latest_filter AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM trade_setup_filter_observation
        WHERE venue = %(venue)s
          AND filter_name = %(filter_name)s
          AND filter_version = %(filter_version)s
          AND asset_suitability_mode = %(asset_suitability_mode)s
    )
    SELECT
        f.asset_id,
        a.symbol,
        f.venue,
        f.asof_ts_utc,
        f.selection_state,
        f.selection_score,
        f.priority_rank,
        f.btc_prior_24h,
        f.setup_filter_state,
        f.setup_filter_reason,
        f.notes
    FROM trade_setup_filter_observation f
    JOIN latest_filter lf
      ON lf.asof_ts_utc = f.asof_ts_utc
    JOIN asset a
      ON a.asset_id = f.asset_id
    WHERE f.venue = %(venue)s
      AND f.filter_name = %(filter_name)s
      AND f.filter_version = %(filter_version)s
      AND f.asset_suitability_mode = %(asset_suitability_mode)s
    ORDER BY
        CASE WHEN f.selection_state = 'WATCHLIST' THEN 0 ELSE 1 END,
        f.priority_rank IS NULL,
        f.priority_rank ASC,
        f.selection_score DESC,
        a.symbol ASC
    LIMIT %(limit)s
    """
    params = {
        "venue": venue,
        "filter_name": filter_name,
        "filter_version": filter_version,
        "asset_suitability_mode": asset_suitability_mode,
        "limit": int(limit),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def classify_proposed(
    row: dict[str, Any],
    *,
    current_hard_min: Decimal,
    proposed_hard_min: Decimal,
    proposed_caution_min: Decimal,
    proposed_clear_above: Decimal,
    current_overheat_max: Decimal,
) -> tuple[str, str, str, bool]:
    selection_state = str(row.get("selection_state") or "").upper()
    current_reason = str(row.get("setup_filter_reason") or "").upper()
    btc_prior = to_decimal(row.get("btc_prior_24h"))

    if selection_state != "WATCHLIST":
        return (
            "OUT_OF_SCOPE_NOT_WATCHLIST",
            "UNCHANGED",
            current_reason or "SELECTION_STATE_NOT_ELIGIBLE",
            False,
        )

    if btc_prior is None:
        return (
            "BTC_CONTEXT_MISSING",
            "UNCHANGED_FAIL",
            "BTC_PRIOR_24H_MISSING",
            False,
        )

    if btc_prior < proposed_hard_min:
        return (
            "HARD_MARKET_DAMAGE",
            "HARD_FAIL",
            "MARKET_DAMAGE_RISK",
            False,
        )

    if proposed_hard_min <= btc_prior < proposed_caution_min:
        return (
            "MARKET_DAMAGE_CAUTION_BAND",
            "CAUTION_NOT_HARD_FAIL",
            "MARKET_DAMAGE_CAUTION",
            current_reason == "MARKET_DAMAGE_RISK",
        )

    if btc_prior > current_overheat_max:
        return (
            "BTC_OVERHEAT_ZONE",
            "UNCHANGED_FAIL",
            "BTC_PRIOR_OVERHEAT_ZONE",
            False,
        )

    if btc_prior >= proposed_clear_above:
        return (
            "MARKET_DAMAGE_CLEAR",
            "NORMAL",
            "MARKET_CONTEXT_OK",
            current_reason == "MARKET_DAMAGE_RISK",
        )

    return (
        "MARKET_CONTEXT_NORMAL_BAND",
        "NORMAL",
        "MARKET_CONTEXT_OK",
        current_reason == "MARKET_DAMAGE_RISK",
    )


def build_rows(raw_rows: list[dict[str, Any]], args: argparse.Namespace) -> list[PreviewRow]:
    current_hard_min = Decimal(args.current_hard_min)
    proposed_hard_min = Decimal(args.proposed_hard_min)
    proposed_caution_min = Decimal(args.proposed_caution_min)
    proposed_clear_above = Decimal(args.proposed_clear_above)
    current_overheat_max = Decimal(args.current_overheat_max)

    rows: list[PreviewRow] = []

    for raw in raw_rows:
        proposed_state, proposed_effect, proposed_reason, would_change = classify_proposed(
            raw,
            current_hard_min=current_hard_min,
            proposed_hard_min=proposed_hard_min,
            proposed_caution_min=proposed_caution_min,
            proposed_clear_above=proposed_clear_above,
            current_overheat_max=current_overheat_max,
        )
        rows.append(
            PreviewRow(
                asset_id=int(raw["asset_id"]),
                symbol=str(raw["symbol"]).upper(),
                venue=str(raw["venue"]),
                asof_ts_utc=raw["asof_ts_utc"],
                selection_state=str(raw.get("selection_state") or ""),
                priority_rank=(
                    None if raw.get("priority_rank") is None else int(raw["priority_rank"])
                ),
                selection_score=to_decimal(raw.get("selection_score")),
                btc_prior_24h=to_decimal(raw.get("btc_prior_24h")),
                current_setup_filter_state=str(raw.get("setup_filter_state") or ""),
                current_setup_filter_reason=str(raw.get("setup_filter_reason") or ""),
                proposed_market_context_state=proposed_state,
                proposed_setup_effect=proposed_effect,
                proposed_reason=proposed_reason,
                would_change_current_market_damage_fail=would_change,
                notes=str(raw.get("notes") or ""),
            )
        )

    return rows


def serialize_row(row: PreviewRow) -> dict[str, Any]:
    out = asdict(row)
    for key, value in list(out.items()):
        if isinstance(value, Decimal):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat(sep=" ")
    return out


def print_table(rows: list[PreviewRow]) -> None:
    headers = [
        "symbol",
        "rank",
        "selection",
        "btc24",
        "current",
        "current_reason",
        "proposed_state",
        "effect",
        "would_change",
    ]
    table = []
    for r in rows:
        table.append(
            [
                r.symbol,
                "" if r.priority_rank is None else str(r.priority_rank),
                r.selection_state,
                fmt_decimal(r.btc_prior_24h),
                r.current_setup_filter_state,
                r.current_setup_filter_reason,
                r.proposed_market_context_state,
                r.proposed_setup_effect,
                "YES" if r.would_change_current_market_damage_fail else "NO",
            ]
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in table)) if table else len(headers[i])
        for i in range(len(headers))
    ]

    print(" | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("-+-".join("-" * widths[i] for i in range(len(headers))))
    for row in table:
        print(" | ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def main() -> None:
    args = parse_args()

    conn = get_connection()
    try:
        raw_rows = fetch_latest_filter_rows(
            conn,
            venue=args.venue,
            filter_name=args.filter_name,
            filter_version=args.filter_version,
            asset_suitability_mode=args.asset_suitability_mode,
            limit=args.limit,
        )
    finally:
        conn.close()

    rows = build_rows(raw_rows, args)

    summary = {
        "total_rows": len(rows),
        "current_reason_counts": dict(Counter(r.current_setup_filter_reason for r in rows)),
        "proposed_state_counts": dict(Counter(r.proposed_market_context_state for r in rows)),
        "proposed_effect_counts": dict(Counter(r.proposed_setup_effect for r in rows)),
        "would_change_count": sum(
            1 for r in rows if r.would_change_current_market_damage_fail
        ),
    }

    if args.output == "json":
        print(json.dumps(
            {
                "report": REPORT_NAME,
                "version": REPORT_VERSION,
                "scope": "read-only market-only diagnostic; no db writes; no broker calls",
                "thresholds": {
                    "current_hard_min": args.current_hard_min,
                    "proposed_hard_min": args.proposed_hard_min,
                    "proposed_caution_min": args.proposed_caution_min,
                    "proposed_clear_above": args.proposed_clear_above,
                    "current_overheat_max": args.current_overheat_max,
                },
                "summary": summary,
                "rows": [serialize_row(r) for r in rows],
            },
            indent=2,
            sort_keys=True,
        ))
        return

    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=read-only market-only diagnostic")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 db_writes=0")
    print(
        "thresholds="
        f"current_hard_min={args.current_hard_min} "
        f"proposed_hard_min={args.proposed_hard_min} "
        f"proposed_caution_min={args.proposed_caution_min} "
        f"proposed_clear_above={args.proposed_clear_above} "
        f"current_overheat_max={args.current_overheat_max}"
    )
    print(f"summary={json.dumps(summary, sort_keys=True)}")
    print()
    print_table(rows)


if __name__ == "__main__":
    main()
