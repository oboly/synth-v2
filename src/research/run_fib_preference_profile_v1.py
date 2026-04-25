from __future__ import annotations

"""
ENGINE: run_fib_preference_profile_v1
MODE: historical

INPUT:
- synth_bt.fib_reaction_profile

OUTPUT:
- synth_bt.fib_preference_profile

CLI:
python -m src.research.run_fib_preference_profile_v1 \
  --venue bitvavo \
  --interval-codes 4h \
  --from-ts "2026-03-01 00:00:00" \
  --to-ts "2026-04-22 00:00:00" \
  --write-db

HISTORICAL:
- supported

NOTES:
- derives preferred fib levels per asset / interval / regime
- keeps both reaction-oriented and execution-oriented preference ranking
- execution score penalizes negative continuation instead of zero-clipping it
"""

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.common.db import get_connection


SOURCE_DB = "synth_bt"
DEFAULT_INTERVAL_CODES = ["4h"]


@dataclass(frozen=True)
class FibReactionRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    regime_label: str
    fib_level: Decimal
    opportunity_count: int
    touch_count: int
    reaction_count: int
    failure_count: int
    avg_reaction_return: Decimal | None
    avg_continuation_return: Decimal | None
    hit_rate: Decimal | None
    touch_rate: Decimal | None


@dataclass(frozen=True)
class RankedLevel:
    fib_level: Decimal
    reaction_score: Decimal
    execution_score: Decimal
    hit_rate: Decimal
    avg_reaction_return: Decimal
    avg_continuation_return: Decimal
    touch_rate: Decimal
    opportunity_count: int
    touch_count: int
    reaction_count: int
    failure_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build fib preference profile from fib_reaction_profile.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval-codes", nargs="+", default=DEFAULT_INTERVAL_CODES)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--min-opportunity-count", type=int, default=20)
    parser.add_argument("--min-touch-count", type=int, default=10)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q8(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _norm_positive(value: Decimal, cap: str) -> Decimal:
    cap_d = Decimal(cap)
    if value <= 0:
        return Decimal("0")
    if value >= cap_d:
        return Decimal("1")
    return _q8(value / cap_d)


def _norm_signed(value: Decimal, cap: str) -> Decimal:
    cap_d = Decimal(cap)
    if cap_d <= 0:
        raise ValueError("cap must be positive")
    scaled = value / cap_d
    return _q8(_clamp(scaled, Decimal("-1"), Decimal("1")))


def ensure_result_table() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS fib_preference_profile (
        fib_preference_profile_id BIGINT NOT NULL AUTO_INCREMENT,
        asset_id INT NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        venue VARCHAR(32) NOT NULL,
        interval_code VARCHAR(16) NOT NULL,
        regime_label VARCHAR(32) NOT NULL,

        preferred_fib_level_primary DECIMAL(10,6) DEFAULT NULL,
        preferred_fib_level_secondary DECIMAL(10,6) DEFAULT NULL,

        primary_preference_score DECIMAL(18,8) DEFAULT NULL,
        secondary_preference_score DECIMAL(18,8) DEFAULT NULL,

        primary_hit_rate DECIMAL(18,8) DEFAULT NULL,
        secondary_hit_rate DECIMAL(18,8) DEFAULT NULL,

        primary_avg_reaction_return DECIMAL(18,8) DEFAULT NULL,
        secondary_avg_reaction_return DECIMAL(18,8) DEFAULT NULL,

        primary_avg_continuation_return DECIMAL(18,8) DEFAULT NULL,
        secondary_avg_continuation_return DECIMAL(18,8) DEFAULT NULL,

        primary_touch_rate DECIMAL(18,8) DEFAULT NULL,
        secondary_touch_rate DECIMAL(18,8) DEFAULT NULL,

        primary_opportunity_count INT DEFAULT NULL,
        secondary_opportunity_count INT DEFAULT NULL,

        reaction_fib_level_primary DECIMAL(10,6) DEFAULT NULL,
        reaction_fib_level_secondary DECIMAL(10,6) DEFAULT NULL,
        reaction_primary_score DECIMAL(18,8) DEFAULT NULL,
        reaction_secondary_score DECIMAL(18,8) DEFAULT NULL,

        execution_fib_level_primary DECIMAL(10,6) DEFAULT NULL,
        execution_fib_level_secondary DECIMAL(10,6) DEFAULT NULL,
        execution_primary_score DECIMAL(18,8) DEFAULT NULL,
        execution_secondary_score DECIMAL(18,8) DEFAULT NULL,

        ranking_json LONGTEXT DEFAULT NULL,
        notes TEXT DEFAULT NULL,

        from_ts_utc DATETIME(6) NOT NULL,
        to_ts_utc DATETIME(6) NOT NULL,
        created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

        PRIMARY KEY (fib_preference_profile_id),
        UNIQUE KEY uq_fib_preference_profile (
            asset_id,
            venue,
            interval_code,
            regime_label,
            from_ts_utc,
            to_ts_utc
        ),
        KEY ix_fib_preference_profile_lookup (
            asset_id,
            venue,
            interval_code,
            regime_label
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    alter_statements = [
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS reaction_fib_level_primary DECIMAL(10,6) DEFAULT NULL AFTER secondary_opportunity_count",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS reaction_fib_level_secondary DECIMAL(10,6) DEFAULT NULL AFTER reaction_fib_level_primary",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS reaction_primary_score DECIMAL(18,8) DEFAULT NULL AFTER reaction_fib_level_secondary",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS reaction_secondary_score DECIMAL(18,8) DEFAULT NULL AFTER reaction_primary_score",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS execution_fib_level_primary DECIMAL(10,6) DEFAULT NULL AFTER reaction_secondary_score",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS execution_fib_level_secondary DECIMAL(10,6) DEFAULT NULL AFTER execution_fib_level_primary",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS execution_primary_score DECIMAL(18,8) DEFAULT NULL AFTER execution_fib_level_secondary",
        "ALTER TABLE fib_preference_profile ADD COLUMN IF NOT EXISTS execution_secondary_score DECIMAL(18,8) DEFAULT NULL AFTER execution_primary_score",
    ]
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            for sql in alter_statements:
                cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_reaction_rows(
    *,
    venue: str,
    interval_codes: list[str],
    from_ts: str,
    to_ts: str,
    asset_id: int | None,
) -> list[FibReactionRow]:
    interval_placeholders = ",".join(["%s"] * len(interval_codes))
    params: list[Any] = [venue, from_ts, to_ts, *interval_codes]

    asset_filter_sql = ""
    if asset_id is not None:
        asset_filter_sql = "AND asset_id = %s"
        params.append(asset_id)

    sql = f"""
    SELECT
        asset_id,
        symbol,
        venue,
        interval_code,
        regime_label,
        fib_level,
        opportunity_count,
        touch_count,
        reaction_count,
        failure_count,
        avg_reaction_return,
        avg_continuation_return,
        hit_rate,
        touch_rate
    FROM fib_reaction_profile
    WHERE venue = %s
      AND from_ts_utc = %s
      AND to_ts_utc = %s
      AND interval_code IN ({interval_placeholders})
      {asset_filter_sql}
    ORDER BY asset_id, interval_code, regime_label, fib_level
    """
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[FibReactionRow] = []
    for row in rows:
        out.append(
            FibReactionRow(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                interval_code=str(row["interval_code"]),
                regime_label=str(row["regime_label"]),
                fib_level=_to_decimal(row["fib_level"]),
                opportunity_count=int(row["opportunity_count"]),
                touch_count=int(row["touch_count"]),
                reaction_count=int(row["reaction_count"]),
                failure_count=int(row["failure_count"]),
                avg_reaction_return=None if row["avg_reaction_return"] is None else _to_decimal(row["avg_reaction_return"]),
                avg_continuation_return=None if row["avg_continuation_return"] is None else _to_decimal(row["avg_continuation_return"]),
                hit_rate=None if row["hit_rate"] is None else _to_decimal(row["hit_rate"]),
                touch_rate=None if row["touch_rate"] is None else _to_decimal(row["touch_rate"]),
            )
        )
    return out


def build_ranked_level(row: FibReactionRow) -> RankedLevel:
    hit_rate = row.hit_rate or Decimal("0")
    avg_reaction_return = row.avg_reaction_return or Decimal("0")
    avg_continuation_return = row.avg_continuation_return or Decimal("0")
    touch_rate = row.touch_rate or Decimal("0")

    normalized_reaction_positive = _norm_positive(avg_reaction_return, "0.08")
    normalized_continuation_signed = _norm_signed(avg_continuation_return, "0.08")

    reaction_score = _q8(
        Decimal("0.45") * hit_rate
        + Decimal("0.25") * normalized_reaction_positive
        + Decimal("0.20") * _norm_positive(avg_continuation_return, "0.08")
        + Decimal("0.10") * touch_rate
    )

    execution_score = _q8(
        Decimal("0.40") * hit_rate
        + Decimal("0.20") * normalized_reaction_positive
        + Decimal("0.30") * normalized_continuation_signed
        + Decimal("0.10") * touch_rate
    )

    return RankedLevel(
        fib_level=row.fib_level,
        reaction_score=reaction_score,
        execution_score=execution_score,
        hit_rate=hit_rate,
        avg_reaction_return=avg_reaction_return,
        avg_continuation_return=avg_continuation_return,
        touch_rate=touch_rate,
        opportunity_count=row.opportunity_count,
        touch_count=row.touch_count,
        reaction_count=row.reaction_count,
        failure_count=row.failure_count,
    )


def rank_group(
    rows: list[FibReactionRow],
    *,
    min_opportunity_count: int,
    min_touch_count: int,
) -> tuple[list[RankedLevel], list[RankedLevel]]:
    eligible = [
        row for row in rows
        if row.opportunity_count >= min_opportunity_count
        and row.touch_count >= min_touch_count
    ]

    ranked = [build_ranked_level(row) for row in eligible]

    reaction_ranked = sorted(
        ranked,
        key=lambda r: (
            -r.reaction_score,
            -r.hit_rate,
            -r.avg_reaction_return,
            -r.avg_continuation_return,
            float(r.fib_level),
        ),
    )

    execution_ranked = sorted(
        ranked,
        key=lambda r: (
            -r.execution_score,
            -r.hit_rate,
            -r.avg_continuation_return,
            -r.avg_reaction_return,
            float(r.fib_level),
        ),
    )

    return reaction_ranked, execution_ranked


def build_rows_for_output(
    rows: list[FibReactionRow],
    *,
    min_opportunity_count: int,
    min_touch_count: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], list[FibReactionRow]] = {}
    symbol_by_group: dict[tuple[int, str, str], str] = {}
    venue_by_group: dict[tuple[int, str, str], str] = {}

    for row in rows:
        key = (row.asset_id, row.interval_code, row.regime_label)
        grouped.setdefault(key, []).append(row)
        symbol_by_group[key] = row.symbol
        venue_by_group[key] = row.venue

    out: list[dict[str, Any]] = []
    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[1], k[2])):
        asset_id, interval_code, regime_label = key
        reaction_ranked, execution_ranked = rank_group(
            grouped[key],
            min_opportunity_count=min_opportunity_count,
            min_touch_count=min_touch_count,
        )

        reaction_primary = reaction_ranked[0] if len(reaction_ranked) >= 1 else None
        reaction_secondary = reaction_ranked[1] if len(reaction_ranked) >= 2 else None
        execution_primary = execution_ranked[0] if len(execution_ranked) >= 1 else None
        execution_secondary = execution_ranked[1] if len(execution_ranked) >= 2 else None

        ranking_json = json.dumps(
            {
                "reaction_ranked": [
                    {
                        "fib_level": str(r.fib_level),
                        "reaction_score": str(r.reaction_score),
                        "execution_score": str(r.execution_score),
                        "hit_rate": str(r.hit_rate),
                        "avg_reaction_return": str(r.avg_reaction_return),
                        "avg_continuation_return": str(r.avg_continuation_return),
                        "touch_rate": str(r.touch_rate),
                        "opportunity_count": r.opportunity_count,
                        "touch_count": r.touch_count,
                        "reaction_count": r.reaction_count,
                        "failure_count": r.failure_count,
                    }
                    for r in reaction_ranked
                ],
                "execution_ranked": [
                    {
                        "fib_level": str(r.fib_level),
                        "reaction_score": str(r.reaction_score),
                        "execution_score": str(r.execution_score),
                        "hit_rate": str(r.hit_rate),
                        "avg_reaction_return": str(r.avg_reaction_return),
                        "avg_continuation_return": str(r.avg_continuation_return),
                        "touch_rate": str(r.touch_rate),
                        "opportunity_count": r.opportunity_count,
                        "touch_count": r.touch_count,
                        "reaction_count": r.reaction_count,
                        "failure_count": r.failure_count,
                    }
                    for r in execution_ranked
                ],
            },
            ensure_ascii=False,
        )

        effective_primary = execution_primary
        effective_secondary = execution_secondary

        out.append(
            {
                "asset_id": asset_id,
                "symbol": symbol_by_group[key],
                "venue": venue_by_group[key],
                "interval_code": interval_code,
                "regime_label": regime_label,

                "preferred_fib_level_primary": None if effective_primary is None else effective_primary.fib_level,
                "preferred_fib_level_secondary": None if effective_secondary is None else effective_secondary.fib_level,

                "primary_preference_score": None if effective_primary is None else effective_primary.execution_score,
                "secondary_preference_score": None if effective_secondary is None else effective_secondary.execution_score,

                "primary_hit_rate": None if effective_primary is None else effective_primary.hit_rate,
                "secondary_hit_rate": None if effective_secondary is None else effective_secondary.hit_rate,

                "primary_avg_reaction_return": None if effective_primary is None else effective_primary.avg_reaction_return,
                "secondary_avg_reaction_return": None if effective_secondary is None else effective_secondary.avg_reaction_return,

                "primary_avg_continuation_return": None if effective_primary is None else effective_primary.avg_continuation_return,
                "secondary_avg_continuation_return": None if effective_secondary is None else effective_secondary.avg_continuation_return,

                "primary_touch_rate": None if effective_primary is None else effective_primary.touch_rate,
                "secondary_touch_rate": None if effective_secondary is None else effective_secondary.touch_rate,

                "primary_opportunity_count": None if effective_primary is None else effective_primary.opportunity_count,
                "secondary_opportunity_count": None if effective_secondary is None else effective_secondary.opportunity_count,

                "reaction_fib_level_primary": None if reaction_primary is None else reaction_primary.fib_level,
                "reaction_fib_level_secondary": None if reaction_secondary is None else reaction_secondary.fib_level,
                "reaction_primary_score": None if reaction_primary is None else reaction_primary.reaction_score,
                "reaction_secondary_score": None if reaction_secondary is None else reaction_secondary.reaction_score,

                "execution_fib_level_primary": None if execution_primary is None else execution_primary.fib_level,
                "execution_fib_level_secondary": None if execution_secondary is None else execution_secondary.fib_level,
                "execution_primary_score": None if execution_primary is None else execution_primary.execution_score,
                "execution_secondary_score": None if execution_secondary is None else execution_secondary.execution_score,

                "ranking_json": ranking_json,
                "notes": (
                    None if execution_primary is not None
                    else f"no eligible level: min_opportunity_count={min_opportunity_count}, min_touch_count={min_touch_count}"
                ),
            }
        )
    return out


def upsert_preference_rows(
    *,
    rows: list[dict[str, Any]],
    from_ts: str,
    to_ts: str,
) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO fib_preference_profile (
        asset_id,
        symbol,
        venue,
        interval_code,
        regime_label,
        preferred_fib_level_primary,
        preferred_fib_level_secondary,
        primary_preference_score,
        secondary_preference_score,
        primary_hit_rate,
        secondary_hit_rate,
        primary_avg_reaction_return,
        secondary_avg_reaction_return,
        primary_avg_continuation_return,
        secondary_avg_continuation_return,
        primary_touch_rate,
        secondary_touch_rate,
        primary_opportunity_count,
        secondary_opportunity_count,
        reaction_fib_level_primary,
        reaction_fib_level_secondary,
        reaction_primary_score,
        reaction_secondary_score,
        execution_fib_level_primary,
        execution_fib_level_secondary,
        execution_primary_score,
        execution_secondary_score,
        ranking_json,
        notes,
        from_ts_utc,
        to_ts_utc
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        symbol = VALUES(symbol),
        preferred_fib_level_primary = VALUES(preferred_fib_level_primary),
        preferred_fib_level_secondary = VALUES(preferred_fib_level_secondary),
        primary_preference_score = VALUES(primary_preference_score),
        secondary_preference_score = VALUES(secondary_preference_score),
        primary_hit_rate = VALUES(primary_hit_rate),
        secondary_hit_rate = VALUES(secondary_hit_rate),
        primary_avg_reaction_return = VALUES(primary_avg_reaction_return),
        secondary_avg_reaction_return = VALUES(secondary_avg_reaction_return),
        primary_avg_continuation_return = VALUES(primary_avg_continuation_return),
        secondary_avg_continuation_return = VALUES(secondary_avg_continuation_return),
        primary_touch_rate = VALUES(primary_touch_rate),
        secondary_touch_rate = VALUES(secondary_touch_rate),
        primary_opportunity_count = VALUES(primary_opportunity_count),
        secondary_opportunity_count = VALUES(secondary_opportunity_count),
        reaction_fib_level_primary = VALUES(reaction_fib_level_primary),
        reaction_fib_level_secondary = VALUES(reaction_fib_level_secondary),
        reaction_primary_score = VALUES(reaction_primary_score),
        reaction_secondary_score = VALUES(reaction_secondary_score),
        execution_fib_level_primary = VALUES(execution_fib_level_primary),
        execution_fib_level_secondary = VALUES(execution_fib_level_secondary),
        execution_primary_score = VALUES(execution_primary_score),
        execution_secondary_score = VALUES(execution_secondary_score),
        ranking_json = VALUES(ranking_json),
        notes = VALUES(notes),
        updated_ts_utc = CURRENT_TIMESTAMP(6)
    """
    params: list[list[Any]] = []
    for row in rows:
        params.append(
            [
                row["asset_id"],
                row["symbol"],
                row["venue"],
                row["interval_code"],
                row["regime_label"],
                row["preferred_fib_level_primary"],
                row["preferred_fib_level_secondary"],
                row["primary_preference_score"],
                row["secondary_preference_score"],
                row["primary_hit_rate"],
                row["secondary_hit_rate"],
                row["primary_avg_reaction_return"],
                row["secondary_avg_reaction_return"],
                row["primary_avg_continuation_return"],
                row["secondary_avg_continuation_return"],
                row["primary_touch_rate"],
                row["secondary_touch_rate"],
                row["primary_opportunity_count"],
                row["secondary_opportunity_count"],
                row["reaction_fib_level_primary"],
                row["reaction_fib_level_secondary"],
                row["reaction_primary_score"],
                row["reaction_secondary_score"],
                row["execution_fib_level_primary"],
                row["execution_fib_level_secondary"],
                row["execution_primary_score"],
                row["execution_secondary_score"],
                row["ranking_json"],
                row["notes"],
                from_ts,
                to_ts,
            ]
        )

    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params)
        conn.commit()
        return len(params)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "asset_id",
        "symbol",
        "interval_code",
        "regime_label",
        "reaction_primary",
        "reaction_score",
        "execution_primary",
        "execution_score",
    ]
    printable: list[list[str]] = []
    for row in rows:
        printable.append(
            [
                str(row["asset_id"]),
                str(row["symbol"]),
                str(row["interval_code"]),
                str(row["regime_label"]),
                "" if row["reaction_fib_level_primary"] is None else str(row["reaction_fib_level_primary"]),
                "" if row["reaction_primary_score"] is None else str(row["reaction_primary_score"]),
                "" if row["execution_fib_level_primary"] is None else str(row["execution_fib_level_primary"]),
                "" if row["execution_primary_score"] is None else str(row["execution_primary_score"]),
            ]
        )

    widths = [len(h) for h in headers]
    for row in printable:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    source_rows = fetch_reaction_rows(
        venue=args.venue,
        interval_codes=args.interval_codes,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        asset_id=args.asset_id,
    )

    preference_rows = build_rows_for_output(
        source_rows,
        min_opportunity_count=args.min_opportunity_count,
        min_touch_count=args.min_touch_count,
    )

    rows_written = 0
    if args.write_db:
        ensure_result_table()
        rows_written = upsert_preference_rows(
            rows=preference_rows,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
        )

    if args.output == "json":
        print(json.dumps(preference_rows, indent=2, ensure_ascii=False, default=str))
    else:
        print_table(preference_rows)

    print(
        f"source_rows={len(source_rows)} "
        f"preference_rows={len(preference_rows)} "
        f"rows_written={rows_written} "
        f"write_db={args.write_db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
