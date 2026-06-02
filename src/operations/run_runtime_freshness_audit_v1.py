from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from src.common.db import get_connection


REPORT_NAME = "runtime_freshness_audit_v1"
REPORT_VERSION = "0.1"


@dataclass(frozen=True)
class StageSpec:
    stage: str
    table_name: str
    interval: str
    ts_column: str
    stale_after: timedelta
    key_column: str | None = None
    expect_asset_coverage: bool = False
    filters: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class WorstAssetRow:
    stage: str
    interval: str
    symbol: str
    latest_ts: str
    age: str
    status: str


@dataclass(frozen=True)
class StageResult:
    stage: str
    interval: str
    rows: int | None
    latest_ts: str
    age: str
    status: str
    covered_assets: int | None
    expected_assets: int | None
    missing_assets: int | None
    stale_assets: int | None
    max_age: str
    error: str
    worst_assets: tuple[WorstAssetRow, ...]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only runtime freshness audit for 4h chain and dashboard support stages."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    parser.add_argument("--top-n", type=int, default=20)
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def normalize_ts(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def fmt_age_from_seconds(total_seconds: float | None) -> str:
    if total_seconds is None:
        return ""
    seconds = max(0, int(total_seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d{hours:02}h"
    if hours > 0:
        return f"{hours}h{minutes:02}m"
    return f"{minutes}m"


def seconds_since(now: datetime, value: datetime | None) -> float | None:
    ts = normalize_ts(value)
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds())


def table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = %s
            LIMIT 1
            """,
            (table_name,),
        )
        return cur.fetchone() is not None


def table_columns(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
            """,
            (table_name,),
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def fetch_enabled_tradeable_assets(conn: Any) -> dict[int, str]:
    if not table_exists(conn, "asset"):
        return {}
    columns = table_columns(conn, "asset")
    if not {"asset_id", "symbol"}.issubset(columns):
        return {}

    where = ["1 = 1"]
    if "is_enabled" in columns:
        where.append("is_enabled = 1")
    if "is_tradeable" in columns:
        where.append("is_tradeable = 1")

    sql = f"""
        SELECT asset_id, symbol
        FROM asset
        WHERE {' AND '.join(where)}
        ORDER BY symbol ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return {int(row["asset_id"]): str(row["symbol"]).upper() for row in rows}


def summarize_stage(
    conn: Any,
    *,
    spec: StageSpec,
    venue: str,
    asset_symbols: dict[int, str],
    now: datetime,
    top_n: int,
) -> StageResult:
    if not table_exists(conn, spec.table_name):
        return StageResult(
            stage=spec.stage,
            interval=spec.interval,
            rows=None,
            latest_ts="",
            age="",
            status="UNKNOWN",
            covered_assets=None,
            expected_assets=None,
            missing_assets=None,
            stale_assets=None,
            max_age="",
            error=f"table_missing:{spec.table_name}",
            worst_assets=(),
        )

    columns = table_columns(conn, spec.table_name)
    required = {spec.ts_column}
    if spec.key_column:
        required.add(spec.key_column)
    if "venue" not in columns:
        venue_filter_supported = False
    else:
        venue_filter_supported = True
    missing_columns = sorted(required - columns)
    if missing_columns:
        return StageResult(
            stage=spec.stage,
            interval=spec.interval,
            rows=None,
            latest_ts="",
            age="",
            status="UNKNOWN",
            covered_assets=None,
            expected_assets=None,
            missing_assets=None,
            stale_assets=None,
            max_age="",
            error=f"missing_columns:{','.join(missing_columns)}",
            worst_assets=(),
        )

    where_parts: list[str] = []
    params: list[Any] = []
    if venue_filter_supported:
        where_parts.append("venue = %s")
        params.append(venue)
    for column_name, value in spec.filters:
        if column_name not in columns:
            return StageResult(
                stage=spec.stage,
                interval=spec.interval,
                rows=None,
                latest_ts="",
                age="",
                status="UNKNOWN",
                covered_assets=None,
                expected_assets=None,
                missing_assets=None,
                stale_assets=None,
                max_age="",
                error=f"missing_filter_column:{column_name}",
                worst_assets=(),
            )
        where_parts.append(f"{column_name} = %s")
        params.append(value)

    if spec.expect_asset_coverage and spec.key_column == "asset_id" and asset_symbols:
        asset_ids = sorted(asset_symbols.keys())
        placeholders = ",".join(["%s"] * len(asset_ids))
        where_parts.append(f"asset_id IN ({placeholders})")
        params.extend(asset_ids)
    elif spec.expect_asset_coverage and spec.key_column == "symbol" and asset_symbols:
        symbols = sorted(asset_symbols.values())
        placeholders = ",".join(["%s"] * len(symbols))
        where_parts.append(f"symbol IN ({placeholders})")
        params.extend(symbols)

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                MAX({spec.ts_column}) AS latest_ts
            FROM {spec.table_name}
            {where_sql}
            """,
            params,
        )
        overall = cur.fetchone() or {}

    total_rows = int(overall.get("row_count") or 0)
    latest_ts = normalize_ts(overall.get("latest_ts"))
    latest_age_seconds = seconds_since(now, latest_ts)

    if total_rows == 0:
        return StageResult(
            stage=spec.stage,
            interval=spec.interval,
            rows=0,
            latest_ts="",
            age="",
            status="MISSING",
            covered_assets=0 if spec.expect_asset_coverage else None,
            expected_assets=len(asset_symbols) if spec.expect_asset_coverage else None,
            missing_assets=len(asset_symbols) if spec.expect_asset_coverage else None,
            stale_assets=0 if spec.expect_asset_coverage else None,
            max_age="",
            error="",
            worst_assets=(),
        )

    worst_assets: list[WorstAssetRow] = []
    covered_assets: int | None = None
    expected_assets: int | None = None
    missing_assets_count: int | None = None
    stale_assets_count: int | None = None
    max_age_seconds = latest_age_seconds
    status = "FRESH" if latest_age_seconds is not None and latest_age_seconds <= spec.stale_after.total_seconds() else "STALE"

    if spec.key_column:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    {spec.key_column} AS item_key,
                    COUNT(*) AS row_count,
                    MAX({spec.ts_column}) AS latest_ts
                FROM {spec.table_name}
                {where_sql}
                GROUP BY {spec.key_column}
                """,
                params,
            )
            grouped_rows = list(cur.fetchall())

        by_key: dict[Any, datetime | None] = {
            row["item_key"]: normalize_ts(row.get("latest_ts")) for row in grouped_rows
        }
        covered_assets = len(by_key)
        if spec.expect_asset_coverage:
            expected_assets = len(asset_symbols)
            expected_keys: Iterable[Any]
            if spec.key_column == "asset_id":
                expected_keys = asset_symbols.keys()
            elif spec.key_column == "symbol":
                expected_keys = asset_symbols.values()
            else:
                expected_keys = ()

            expected_set = set(expected_keys)
            present_set = {key if spec.key_column != "symbol" else str(key).upper() for key in by_key}
            missing_keys = sorted(expected_set - present_set)
            missing_assets_count = len(missing_keys)
            if missing_keys:
                status = "STALE"
                for key in missing_keys:
                    symbol = asset_symbols.get(int(key), str(key)) if spec.key_column == "asset_id" else str(key)
                    worst_assets.append(
                        WorstAssetRow(
                            stage=spec.stage,
                            interval=spec.interval,
                            symbol=symbol,
                            latest_ts="",
                            age="",
                            status="MISSING",
                        )
                    )

        stale_present_rows: list[tuple[float, WorstAssetRow]] = []
        for key, ts in by_key.items():
            age_seconds = seconds_since(now, ts)
            if age_seconds is not None:
                max_age_seconds = max(max_age_seconds or 0.0, age_seconds)
            if age_seconds is None or age_seconds <= spec.stale_after.total_seconds():
                continue
            status = "STALE"
            symbol = asset_symbols.get(int(key), str(key)) if spec.key_column == "asset_id" else str(key).upper()
            stale_present_rows.append(
                (
                    age_seconds,
                    WorstAssetRow(
                        stage=spec.stage,
                        interval=spec.interval,
                        symbol=symbol,
                        latest_ts=fmt_ts(ts),
                        age=fmt_age_from_seconds(age_seconds),
                        status="STALE",
                    ),
                )
            )

        stale_present_rows.sort(key=lambda item: item[0], reverse=True)
        stale_assets_count = len(stale_present_rows)
        worst_assets.extend(row for _, row in stale_present_rows[:top_n])

    return StageResult(
        stage=spec.stage,
        interval=spec.interval,
        rows=total_rows,
        latest_ts=fmt_ts(latest_ts),
        age=fmt_age_from_seconds(latest_age_seconds),
        status=status,
        covered_assets=covered_assets,
        expected_assets=expected_assets,
        missing_assets=missing_assets_count,
        stale_assets=stale_assets_count,
        max_age=fmt_age_from_seconds(max_age_seconds),
        error="",
        worst_assets=tuple(worst_assets[:top_n]),
    )


def stage_specs() -> list[StageSpec]:
    return [
        StageSpec(
            stage="candles",
            table_name="obs_market_candle",
            interval="4h",
            ts_column="close_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(hours=6),
            filters=(("interval_code", "4h"),),
        ),
        StageSpec(
            stage="feat_candle",
            table_name="feat_candle",
            interval="4h",
            ts_column="close_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(hours=6),
            filters=(("interval_code", "4h"),),
        ),
        StageSpec(
            stage="signal_state",
            table_name="signal_state",
            interval="4h",
            ts_column="close_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(hours=6),
            filters=(("interval_code", "4h"),),
        ),
        StageSpec(
            stage="signal_engine_state",
            table_name="signal_engine_state",
            interval="4h",
            ts_column="signal_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(hours=6),
            filters=(("interval_code", "4h"),),
        ),
        StageSpec(
            stage="paper_advice",
            table_name="paper_advice_observation",
            interval="4h",
            ts_column="asof_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(hours=6),
            filters=(("interval_code", "4h"),),
        ),
        StageSpec(
            stage="selection_state",
            table_name="selection_state",
            interval="4h",
            ts_column="asof_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(hours=6),
        ),
        StageSpec(
            stage="candles",
            table_name="obs_market_candle",
            interval="15m",
            ts_column="close_ts_utc",
            key_column="asset_id",
            expect_asset_coverage=True,
            stale_after=timedelta(minutes=45),
            filters=(("interval_code", "15m"),),
        ),
        StageSpec(
            stage="market_price_snapshot",
            table_name="market_price_snapshot",
            interval="-",
            ts_column="observed_ts_utc",
            key_column="symbol",
            expect_asset_coverage=True,
            stale_after=timedelta(minutes=30),
        ),
        StageSpec(
            stage="account_position_snapshot",
            table_name="account_position_snapshot",
            interval="-",
            ts_column="snapshot_ts_utc",
            stale_after=timedelta(hours=24),
        ),
        StageSpec(
            stage="trading_account_balance_snapshot",
            table_name="trading_account_balance_snapshot",
            interval="-",
            ts_column="snapshot_ts_utc",
            stale_after=timedelta(hours=24),
        ),
        StageSpec(
            stage="strategy_runtime_snapshot",
            table_name="strategy_runtime_snapshot",
            interval="4h",
            ts_column="snapshot_ts_utc",
            stale_after=timedelta(hours=6),
            filters=(("interval_code", "4h"), ("chain_name", "run_chain_4h")),
        ),
    ]


def print_table(results: list[StageResult], top_n: int) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print("broker_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("executor=none")
    print("decision_gate_changes=0")
    print()
    print("stage | interval | rows | latest_ts | age | status")
    for result in results:
        rows_value = "" if result.rows is None else str(result.rows)
        print(
            f"{result.stage} | {result.interval} | {rows_value} | "
            f"{result.latest_ts or '-'} | {result.age or '-'} | {result.status}"
        )
    print()
    print(f"worst_stale_assets_top_n={top_n}")
    print("stage | interval | symbol | latest_ts | age | status")
    printed_any = False
    for result in results:
        for row in result.worst_assets[:top_n]:
            printed_any = True
            print(
                f"{row.stage} | {row.interval} | {row.symbol} | "
                f"{row.latest_ts or '-'} | {row.age or '-'} | {row.status}"
            )
    if not printed_any:
        print("- | - | - | - | - | -")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.now(UTC)
    conn = get_connection()
    try:
        asset_symbols = fetch_enabled_tradeable_assets(conn)
        results = [
            summarize_stage(
                conn,
                spec=spec,
                venue=args.venue,
                asset_symbols=asset_symbols,
                now=now,
                top_n=args.top_n,
            )
            for spec in stage_specs()
        ]
    finally:
        conn.close()

    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "venue": args.venue,
        "generated_at_utc": fmt_ts(now),
        "broker_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "decision_gate_changes": 0,
        "results": [asdict(result) for result in results],
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2))
    else:
        print_table(results, args.top_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
