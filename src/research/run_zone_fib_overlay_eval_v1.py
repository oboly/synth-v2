"""
Synth v2.5 / v2.6 research runner: leak-free Zone/Fib overlay evaluator.

Layer:
    research/evaluation only.

Rules:
    - Read-only.
    - One DB connection per run.
    - Future candles start strictly after context asof:
          obs_market_candle.open_ts_utc > execution_zone_context.asof_ts_utc
    - Explicit candle ordering:
          ORDER BY open_ts_utc ASC
    - Touch-aware return:
          close of candle after first future touch vs first-touch reference price.
    - No writes to decision, execution, account, order, or live tables.

Primary context source:
    synth.execution_zone_context

Expected schema:
    expected_entry_zone_low
    expected_entry_zone_high
    zone_confidence_score
    zone_alignment_score
    notes containing e.g. fib_pref_regime=TREND_UP

Optional volatility enrichment:
    v_execution_zone_touch_with_volatility.volatility_bucket
    Only volatility_bucket is read from this view. Forward/touch return columns are not used.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymysql

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


FORBIDDEN_SQL_PREFIXES = (
    "insert",
    "update",
    "delete",
    "replace",
    "create",
    "alter",
    "drop",
    "truncate",
    "grant",
    "revoke",
    "call",
    "load",
    "rename",
    "lock",
    "unlock",
)


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class ContextRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    zone_low: Decimal
    zone_high: Decimal
    zone_mid: Decimal
    regime: str
    volatility_bucket: str
    zone_confidence_score: Optional[Decimal]
    zone_alignment_score: Optional[Decimal]
    expected_entry_zone_type: Optional[str]


@dataclass(frozen=True)
class Candle:
    open_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class EvalRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    regime: str
    volatility_bucket: str
    zone_low: Decimal
    zone_high: Decimal
    zone_mid: Decimal
    zone_confidence_score: Optional[Decimal]
    zone_alignment_score: Optional[Decimal]
    expected_entry_zone_type: Optional[str]
    touched: bool
    touch_ts_utc: Optional[datetime]
    touch_reference_price: Optional[Decimal]
    after_touch_close_ts_utc: Optional[datetime]
    after_touch_close_price: Optional[Decimal]
    ret_after_touch: Optional[Decimal]
    unevaluable_reason: Optional[str]


def load_project_env() -> None:
    if load_dotenv is None:
        return

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


def env_first(names: Sequence[str], default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def build_db_config(args: argparse.Namespace) -> DbConfig:
    load_project_env()

    host = args.host or env_first(("SYNTH_DB_HOST", "DB_HOST", "MYSQL_HOST", "MARIADB_HOST"), "127.0.0.1")
    port = int(args.port or env_first(("SYNTH_DB_PORT", "DB_PORT", "MYSQL_PORT", "MARIADB_PORT"), "3306"))
    user = args.user or env_first(("SYNTH_DB_USER", "DB_USER", "MYSQL_USER", "MARIADB_USER"), "root")
    password = args.password
    if password is None:
        password = env_first(("SYNTH_DB_PASSWORD", "DB_PASSWORD", "MYSQL_PASSWORD", "MARIADB_PASSWORD"), "")
    database = args.database or env_first(("SYNTH_DB_NAME", "DB_NAME", "MYSQL_DATABASE", "MARIADB_DATABASE"), "synth")

    if host is None or user is None or database is None:
        raise ValueError("Incomplete DB configuration.")

    return DbConfig(
        host=str(host),
        port=port,
        user=str(user),
        password=str(password),
        database=str(database),
    )


def connect(config: DbConfig) -> pymysql.connections.Connection:
    conn = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("START TRANSACTION READ ONLY")
    return conn


def assert_read_only_sql(sql: str) -> None:
    stripped = sql.strip().lower()
    for prefix in FORBIDDEN_SQL_PREFIXES:
        if stripped.startswith(prefix):
            raise RuntimeError(f"Refusing non-read-only SQL: {prefix}")


def fetch_all(
    conn: pymysql.connections.Connection,
    sql: str,
    params: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    assert_read_only_sql(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def q(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe identifier: {identifier}")
    return f"`{identifier}`"


def fetch_columns(conn: pymysql.connections.Connection, database: str, source: str) -> List[str]:
    rows = fetch_all(
        conn,
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (database, source),
    )
    return [str(row["COLUMN_NAME"]) for row in rows]


def pick_column(columns: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    existing = set(columns)
    for candidate in candidates:
        if candidate in existing:
            return candidate
    return None


def parse_ts(raw: str) -> datetime:
    value = raw.strip().replace("T", " ")
    if value.endswith("Z"):
        value = value[:-1]
    return datetime.fromisoformat(value)


def to_decimal(value: Any, name: str) -> Decimal:
    if value is None:
        raise ValueError(f"Missing decimal field: {name}")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def decimal_to_float(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def decimal_mean(values: Sequence[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def normalize_bounds(low: Decimal, high: Decimal) -> Tuple[Decimal, Decimal]:
    if low <= high:
        return low, high
    return high, low


def parse_regime(notes: Optional[str], fallback: Optional[str]) -> str:
    if fallback:
        return str(fallback)

    if not notes:
        return "UNKNOWN"

    patterns = (
        r"\bfib_pref_regime=([A-Z0-9_]+)",
        r"\bregime=([A-Z0-9_]+)",
        r"\bmarket_regime=([A-Z0-9_]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, notes)
        if match:
            return match.group(1)

    return "UNKNOWN"


def interval_to_timedelta(interval_code: str, candles: int) -> timedelta:
    match = re.fullmatch(r"(\d+)(m|h|d)", interval_code.strip().lower())
    if not match:
        return timedelta(days=90)

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "m":
        return timedelta(minutes=value * candles)
    if unit == "h":
        return timedelta(hours=value * candles)
    if unit == "d":
        return timedelta(days=value * candles)

    return timedelta(days=90)


def detect_context_columns(columns: Sequence[str]) -> Dict[str, Optional[str]]:
    return {
        "asset_id": pick_column(columns, ("asset_id",)),
        "symbol": pick_column(columns, ("symbol", "base_symbol", "asset_symbol")),
        "venue": pick_column(columns, ("venue", "venue_code")),
        "interval_code": pick_column(columns, ("interval_code", "interval")),
        "asof_ts_utc": pick_column(columns, ("asof_ts_utc", "open_ts_utc", "context_ts_utc")),
        "zone_low": pick_column(
            columns,
            (
                "expected_entry_zone_low",
                "zone_low",
                "zone_low_price",
                "zone_bottom",
                "lower_price",
                "price_low",
                "support_low",
            ),
        ),
        "zone_high": pick_column(
            columns,
            (
                "expected_entry_zone_high",
                "zone_high",
                "zone_high_price",
                "zone_top",
                "upper_price",
                "price_high",
                "support_high",
            ),
        ),
        "zone_mid": pick_column(
            columns,
            (
                "expected_entry_zone_mid",
                "zone_mid",
                "zone_mid_price",
                "zone_price",
                "mid_price",
                "reference_price",
                "zone_ref_price",
            ),
        ),
        "regime": pick_column(columns, ("regime", "regime_code", "trend_regime", "structure_regime", "market_regime")),
        "volatility_bucket": pick_column(columns, ("volatility_bucket", "vol_bucket", "volatility_regime", "vol_regime", "atr_bucket")),
        "zone_confidence_score": pick_column(columns, ("zone_confidence_score", "confidence_score")),
        "zone_alignment_score": pick_column(columns, ("zone_alignment_score", "alignment_score")),
        "expected_entry_zone_type": pick_column(columns, ("expected_entry_zone_type", "zone_type")),
        "notes": pick_column(columns, ("notes",)),
    }


def require_mapping(mapping: Dict[str, Optional[str]], required_keys: Sequence[str]) -> None:
    missing = [key for key in required_keys if mapping.get(key) is None]
    if missing:
        raise RuntimeError("Context source is missing required columns: " + ", ".join(missing))


def fetch_asset_symbol_map(
    conn: pymysql.connections.Connection,
    database: str,
    asset_ids: Sequence[int],
) -> Dict[int, str]:
    if not asset_ids:
        return {}

    for table_name in ("asset", "assets", "dim_asset"):
        columns = fetch_columns(conn, database, table_name)
        if not columns:
            continue

        id_col = pick_column(columns, ("asset_id", "id"))
        symbol_col = pick_column(columns, ("symbol", "base_symbol", "asset_symbol", "code"))
        if id_col is None or symbol_col is None:
            continue

        placeholders = ", ".join(["%s"] * len(asset_ids))
        rows = fetch_all(
            conn,
            f"""
            SELECT {q(id_col)} AS asset_id, {q(symbol_col)} AS symbol
            FROM {q(table_name)}
            WHERE {q(id_col)} IN ({placeholders})
            """,
            tuple(asset_ids),
        )
        return {int(row["asset_id"]): str(row["symbol"]) for row in rows if row.get("symbol")}

    return {}


def fetch_volatility_bucket_map(
    conn: pymysql.connections.Connection,
    database: str,
    volatility_view: str,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
) -> Dict[Tuple[int, str, str, datetime], str]:
    if not volatility_view:
        return {}

    columns = fetch_columns(conn, database, volatility_view)
    required = {"asset_id", "venue", "interval_code", "asof_ts_utc", "volatility_bucket"}
    if not required.issubset(set(columns)):
        return {}

    rows = fetch_all(
        conn,
        f"""
        SELECT
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
            volatility_bucket
        FROM {q(volatility_view)}
        WHERE venue = %s
          AND interval_code = %s
          AND asof_ts_utc >= %s
          AND asof_ts_utc < %s
        """,
        (venue, interval_code, from_ts, to_ts),
    )

    result: Dict[Tuple[int, str, str, datetime], str] = {}
    for row in rows:
        key = (
            int(row["asset_id"]),
            str(row["venue"]),
            str(row["interval_code"]),
            row["asof_ts_utc"],
        )
        result[key] = str(row["volatility_bucket"] or "UNKNOWN")

    return result


def fetch_context_rows(
    conn: pymysql.connections.Connection,
    database: str,
    context_source: str,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    symbols: Sequence[str],
    limit: Optional[int],
    volatility_view: str,
) -> List[ContextRow]:
    columns = fetch_columns(conn, database, context_source)
    if not columns:
        raise RuntimeError(f"Context source not found or empty: {database}.{context_source}")

    mapping = detect_context_columns(columns)
    require_mapping(mapping, ("asset_id", "venue", "interval_code", "asof_ts_utc", "zone_low", "zone_high"))

    asset_id_col = str(mapping["asset_id"])
    symbol_col = mapping["symbol"]
    venue_col = str(mapping["venue"])
    interval_col = str(mapping["interval_code"])
    asof_col = str(mapping["asof_ts_utc"])
    low_col = str(mapping["zone_low"])
    high_col = str(mapping["zone_high"])
    mid_col = mapping["zone_mid"]
    regime_col = mapping["regime"]
    vol_col = mapping["volatility_bucket"]
    confidence_col = mapping["zone_confidence_score"]
    alignment_col = mapping["zone_alignment_score"]
    zone_type_col = mapping["expected_entry_zone_type"]
    notes_col = mapping["notes"]

    select_parts = [
        f"{q(asset_id_col)} AS asset_id",
        f"{q(venue_col)} AS venue",
        f"{q(interval_col)} AS interval_code",
        f"{q(asof_col)} AS asof_ts_utc",
        f"{q(low_col)} AS zone_low",
        f"{q(high_col)} AS zone_high",
    ]

    select_parts.append(f"{q(symbol_col)} AS symbol" if symbol_col else "CAST(NULL AS CHAR) AS symbol")
    select_parts.append(f"{q(mid_col)} AS zone_mid" if mid_col else f"(({q(low_col)} + {q(high_col)}) / 2) AS zone_mid")
    select_parts.append(f"{q(regime_col)} AS regime_raw" if regime_col else "CAST(NULL AS CHAR) AS regime_raw")
    select_parts.append(f"{q(vol_col)} AS volatility_bucket" if vol_col else "CAST(NULL AS CHAR) AS volatility_bucket")
    select_parts.append(f"{q(confidence_col)} AS zone_confidence_score" if confidence_col else "CAST(NULL AS DECIMAL(18,8)) AS zone_confidence_score")
    select_parts.append(f"{q(alignment_col)} AS zone_alignment_score" if alignment_col else "CAST(NULL AS DECIMAL(18,8)) AS zone_alignment_score")
    select_parts.append(f"{q(zone_type_col)} AS expected_entry_zone_type" if zone_type_col else "CAST(NULL AS CHAR) AS expected_entry_zone_type")
    select_parts.append(f"{q(notes_col)} AS notes" if notes_col else "CAST(NULL AS CHAR) AS notes")

    where_parts = [
        f"{q(venue_col)} = %s",
        f"{q(interval_col)} = %s",
        f"{q(asof_col)} >= %s",
        f"{q(asof_col)} < %s",
        f"{q(low_col)} IS NOT NULL",
        f"{q(high_col)} IS NOT NULL",
    ]
    params: List[Any] = [venue, interval_code, from_ts, to_ts]

    if symbols:
        if symbol_col is None:
            raise RuntimeError("--symbols requires a symbol column in the context source.")
        placeholders = ", ".join(["%s"] * len(symbols))
        where_parts.append(f"{q(symbol_col)} IN ({placeholders})")
        params.extend(symbols)

    if limit is not None:
        limit_sql = " LIMIT %s"
        params.append(int(limit))
    else:
        limit_sql = ""

    rows = fetch_all(
        conn,
        f"""
        SELECT
            {", ".join(select_parts)}
        FROM {q(context_source)}
        WHERE {" AND ".join(where_parts)}
        ORDER BY {q(asof_col)} ASC, {q(asset_id_col)} ASC
        {limit_sql}
        """,
        tuple(params),
    )

    asset_ids = sorted({int(row["asset_id"]) for row in rows})
    asset_symbol_map = fetch_asset_symbol_map(conn, database, asset_ids)
    volatility_map = fetch_volatility_bucket_map(
        conn=conn,
        database=database,
        volatility_view=volatility_view,
        venue=venue,
        interval_code=interval_code,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    context_rows: List[ContextRow] = []
    for row in rows:
        asset_id = int(row["asset_id"])
        zone_low, zone_high = normalize_bounds(
            to_decimal(row["zone_low"], "zone_low"),
            to_decimal(row["zone_high"], "zone_high"),
        )
        zone_mid = to_decimal(row["zone_mid"], "zone_mid")

        symbol = str(row.get("symbol") or asset_symbol_map.get(asset_id) or asset_id)
        regime = parse_regime(row.get("notes"), row.get("regime_raw"))

        volatility_bucket = row.get("volatility_bucket")
        if not volatility_bucket:
            vol_key = (asset_id, str(row["venue"]), str(row["interval_code"]), row["asof_ts_utc"])
            volatility_bucket = volatility_map.get(vol_key, "UNKNOWN")

        context_rows.append(
            ContextRow(
                asset_id=asset_id,
                symbol=symbol,
                venue=str(row["venue"]),
                interval_code=str(row["interval_code"]),
                asof_ts_utc=row["asof_ts_utc"],
                zone_low=zone_low,
                zone_high=zone_high,
                zone_mid=zone_mid,
                regime=regime,
                volatility_bucket=str(volatility_bucket or "UNKNOWN"),
                zone_confidence_score=to_optional_decimal(row.get("zone_confidence_score")),
                zone_alignment_score=to_optional_decimal(row.get("zone_alignment_score")),
                expected_entry_zone_type=str(row["expected_entry_zone_type"]) if row.get("expected_entry_zone_type") else None,
            )
        )

    return context_rows


def fetch_candles(
    conn: pymysql.connections.Connection,
    context_rows: Sequence[ContextRow],
    max_future_candles: int,
    after_touch_candles: int,
) -> Dict[Tuple[int, str, str], List[Candle]]:
    grouped: Dict[Tuple[int, str, str], List[ContextRow]] = {}
    for row in context_rows:
        grouped.setdefault((row.asset_id, row.venue, row.interval_code), []).append(row)

    db_rows = fetch_all(conn, "SELECT DATABASE() AS db_name")
    database = str(db_rows[0]["db_name"])
    candle_columns = fetch_columns(conn, database, "obs_market_candle")

    open_col = pick_column(candle_columns, ("open", "open_price", "price_open", "o"))
    high_col = pick_column(candle_columns, ("high", "high_price", "price_high", "h"))
    low_col = pick_column(candle_columns, ("low", "low_price", "price_low", "l"))
    close_col = pick_column(candle_columns, ("close", "close_price", "price_close", "c"))

    missing = []
    if open_col is None:
        missing.append("open/open_price")
    if high_col is None:
        missing.append("high/high_price")
    if low_col is None:
        missing.append("low/low_price")
    if close_col is None:
        missing.append("close/close_price")
    if missing:
        raise RuntimeError(
            "obs_market_candle is missing required OHLC column mapping: "
            + ", ".join(missing)
            + ". Existing columns: "
            + ", ".join(candle_columns)
        )

    result: Dict[Tuple[int, str, str], List[Candle]] = {}
    extra_candles = max_future_candles + after_touch_candles + 4

    for key, rows in grouped.items():
        asset_id, venue, interval_code = key
        min_asof = min(row.asof_ts_utc for row in rows)
        max_asof = max(row.asof_ts_utc for row in rows)
        load_to = max_asof + interval_to_timedelta(interval_code, extra_candles)

        candle_rows = fetch_all(
            conn,
            f"""
            SELECT
                open_ts_utc,
                {q(open_col)} AS open_price,
                {q(high_col)} AS high_price,
                {q(low_col)} AS low_price,
                {q(close_col)} AS close_price
            FROM obs_market_candle
            WHERE asset_id = %s
              AND venue = %s
              AND interval_code = %s
              AND open_ts_utc > %s
              AND open_ts_utc <= %s
            ORDER BY open_ts_utc ASC
            """,
            (asset_id, venue, interval_code, min_asof, load_to),
        )

        result[key] = [
            Candle(
                open_ts_utc=row["open_ts_utc"],
                open_price=to_decimal(row["open_price"], "open_price"),
                high_price=to_decimal(row["high_price"], "high_price"),
                low_price=to_decimal(row["low_price"], "low_price"),
                close_price=to_decimal(row["close_price"], "close_price"),
            )
            for row in candle_rows
        ]

    return result

def candle_touches_zone(candle: Candle, zone_low: Decimal, zone_high: Decimal) -> bool:
    return candle.low_price <= zone_high and candle.high_price >= zone_low


def get_touch_reference(candle: Candle, zone_low: Decimal, zone_high: Decimal, zone_mid: Decimal) -> Decimal:
    if zone_low <= candle.open_price <= zone_high:
        return candle.open_price
    if candle.open_price > zone_high:
        return zone_high
    if candle.open_price < zone_low:
        return zone_low
    return zone_mid


def evaluate_one(
    context: ContextRow,
    candles: Sequence[Candle],
    max_future_candles: int,
    after_touch_candles: int,
) -> EvalRow:
    future = [candle for candle in candles if candle.open_ts_utc > context.asof_ts_utc]
    future = future[: max_future_candles + after_touch_candles + 1]

    base = {
        "asset_id": context.asset_id,
        "symbol": context.symbol,
        "venue": context.venue,
        "interval_code": context.interval_code,
        "asof_ts_utc": context.asof_ts_utc,
        "regime": context.regime,
        "volatility_bucket": context.volatility_bucket,
        "zone_low": context.zone_low,
        "zone_high": context.zone_high,
        "zone_mid": context.zone_mid,
        "zone_confidence_score": context.zone_confidence_score,
        "zone_alignment_score": context.zone_alignment_score,
        "expected_entry_zone_type": context.expected_entry_zone_type,
    }

    if not future:
        return EvalRow(
            **base,
            touched=False,
            touch_ts_utc=None,
            touch_reference_price=None,
            after_touch_close_ts_utc=None,
            after_touch_close_price=None,
            ret_after_touch=None,
            unevaluable_reason="NO_FUTURE_CANDLES",
        )

    touch_index: Optional[int] = None
    touch_candle: Optional[Candle] = None

    for idx, candle in enumerate(future[:max_future_candles]):
        if candle_touches_zone(candle, context.zone_low, context.zone_high):
            touch_index = idx
            touch_candle = candle
            break

    if touch_index is None or touch_candle is None:
        return EvalRow(
            **base,
            touched=False,
            touch_ts_utc=None,
            touch_reference_price=None,
            after_touch_close_ts_utc=None,
            after_touch_close_price=None,
            ret_after_touch=None,
            unevaluable_reason="NO_TOUCH_WITHIN_HORIZON",
        )

    ref_price = get_touch_reference(touch_candle, context.zone_low, context.zone_high, context.zone_mid)
    after_index = touch_index + after_touch_candles

    if after_index >= len(future):
        return EvalRow(
            **base,
            touched=True,
            touch_ts_utc=touch_candle.open_ts_utc,
            touch_reference_price=ref_price,
            after_touch_close_ts_utc=None,
            after_touch_close_price=None,
            ret_after_touch=None,
            unevaluable_reason="TOUCHED_BUT_NO_AFTER_TOUCH_CANDLE",
        )

    after_candle = future[after_index]
    if ref_price <= Decimal("0"):
        ret_after_touch = None
        reason = "INVALID_TOUCH_REFERENCE_PRICE"
    else:
        ret_after_touch = (after_candle.close_price - ref_price) / ref_price
        reason = None

    return EvalRow(
        **base,
        touched=True,
        touch_ts_utc=touch_candle.open_ts_utc,
        touch_reference_price=ref_price,
        after_touch_close_ts_utc=after_candle.open_ts_utc,
        after_touch_close_price=after_candle.close_price,
        ret_after_touch=ret_after_touch,
        unevaluable_reason=reason,
    )


def evaluate_rows(
    context_rows: Sequence[ContextRow],
    candle_map: Dict[Tuple[int, str, str], List[Candle]],
    max_future_candles: int,
    after_touch_candles: int,
) -> List[EvalRow]:
    result: List[EvalRow] = []

    for context in context_rows:
        key = (context.asset_id, context.venue, context.interval_code)
        result.append(
            evaluate_one(
                context=context,
                candles=candle_map.get(key, []),
                max_future_candles=max_future_candles,
                after_touch_candles=after_touch_candles,
            )
        )

    return result


def summarize_group(rows: Sequence[EvalRow]) -> Dict[str, Any]:
    touched_rows = [row for row in rows if row.touched]
    return_rows = [row.ret_after_touch for row in touched_rows if row.ret_after_touch is not None]
    wins = [value for value in return_rows if value > Decimal("0")]
    confidence_values = [row.zone_confidence_score for row in rows if row.zone_confidence_score is not None]
    alignment_values = [row.zone_alignment_score for row in rows if row.zone_alignment_score is not None]

    return {
        "rows": len(rows),
        "touched": len(touched_rows),
        "touch_rate": len(touched_rows) / len(rows) if rows else None,
        "avg_zone_confidence_score": decimal_to_float(decimal_mean(confidence_values)),
        "avg_zone_alignment_score": decimal_to_float(decimal_mean(alignment_values)),
        "avg_ret_after_touch": decimal_to_float(decimal_mean(return_rows)),
        "median_ret_after_touch": statistics.median([float(value) for value in return_rows]) if return_rows else None,
        "wr_after_touch": len(wins) / len(return_rows) if return_rows else None,
        "return_rows": len(return_rows),
    }


def summarize_by(rows: Sequence[EvalRow], attr: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[EvalRow]] = {}
    for row in rows:
        grouped.setdefault(str(getattr(row, attr)), []).append(row)
    return {key: summarize_group(value) for key, value in sorted(grouped.items(), key=lambda item: item[0])}


def summarize_reasons(rows: Sequence[EvalRow]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        reason = row.unevaluable_reason or "OK"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def summarize(rows: Sequence[EvalRow]) -> Dict[str, Any]:
    return {
        "overall": summarize_group(rows),
        "by_regime": summarize_by(rows, "regime"),
        "by_touched": {
            "false": summarize_group([row for row in rows if not row.touched]),
            "true": summarize_group([row for row in rows if row.touched]),
        },
        "by_volatility_bucket": summarize_by(rows, "volatility_bucket"),
        "by_symbol": summarize_by(rows, "symbol"),
        "by_expected_entry_zone_type": summarize_by(rows, "expected_entry_zone_type"),
        "unevaluable_reasons": summarize_reasons(rows),
    }


def serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return float(value)
    return value


def eval_row_to_dict(row: EvalRow) -> Dict[str, Any]:
    return {
        "asset_id": row.asset_id,
        "symbol": row.symbol,
        "venue": row.venue,
        "interval_code": row.interval_code,
        "asof_ts_utc": row.asof_ts_utc,
        "regime": row.regime,
        "volatility_bucket": row.volatility_bucket,
        "zone_low": row.zone_low,
        "zone_high": row.zone_high,
        "zone_mid": row.zone_mid,
        "zone_confidence_score": row.zone_confidence_score,
        "zone_alignment_score": row.zone_alignment_score,
        "expected_entry_zone_type": row.expected_entry_zone_type,
        "touched": row.touched,
        "touch_ts_utc": row.touch_ts_utc,
        "touch_reference_price": row.touch_reference_price,
        "after_touch_close_ts_utc": row.after_touch_close_ts_utc,
        "after_touch_close_price": row.after_touch_close_price,
        "ret_after_touch": row.ret_after_touch,
        "unevaluable_reason": row.unevaluable_reason,
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=serialize), encoding="utf-8")


def write_csv(path: Path, rows: Sequence[EvalRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dict_rows = [eval_row_to_dict(row) for row in rows]

    fieldnames = [
        "asset_id",
        "symbol",
        "venue",
        "interval_code",
        "asof_ts_utc",
        "regime",
        "volatility_bucket",
        "zone_low",
        "zone_high",
        "zone_mid",
        "zone_confidence_score",
        "zone_alignment_score",
        "expected_entry_zone_type",
        "touched",
        "touch_ts_utc",
        "touch_reference_price",
        "after_touch_close_ts_utc",
        "after_touch_close_price",
        "ret_after_touch",
        "unevaluable_reason",
    ]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in dict_rows:
            writer.writerow({key: serialize(value) for key, value in row.items()})


def parse_symbols(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Leak-free read-only Zone/Fib overlay evaluator.")

    parser.add_argument("--database", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)

    parser.add_argument("--context-source", default="execution_zone_context")
    parser.add_argument("--volatility-view", default="v_execution_zone_touch_with_volatility")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="4h")
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--limit", type=int, default=None)

    parser.add_argument("--max-future-candles", type=int, default=12)
    parser.add_argument("--after-touch-candles", type=int, default=1)

    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--quiet", action="store_true")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_future_candles <= 0:
        raise ValueError("--max-future-candles must be > 0")
    if args.after_touch_candles <= 0:
        raise ValueError("--after-touch-candles must be > 0")

    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)
    if to_ts <= from_ts:
        raise ValueError("--to-ts must be after --from-ts")

    config = build_db_config(args)
    conn = connect(config)

    try:
        context_rows = fetch_context_rows(
            conn=conn,
            database=config.database,
            context_source=args.context_source,
            venue=args.venue,
            interval_code=args.interval_code,
            from_ts=from_ts,
            to_ts=to_ts,
            symbols=parse_symbols(args.symbols),
            limit=args.limit,
            volatility_view=args.volatility_view,
        )

        candle_map = fetch_candles(
            conn=conn,
            context_rows=context_rows,
            max_future_candles=args.max_future_candles,
            after_touch_candles=args.after_touch_candles,
        )

        eval_rows = evaluate_rows(
            context_rows=context_rows,
            candle_map=candle_map,
            max_future_candles=args.max_future_candles,
            after_touch_candles=args.after_touch_candles,
        )

        payload = {
            "runner": "run_zone_fib_overlay_eval_v1",
            "mode": "read_only_leak_free",
            "context_source": args.context_source,
            "volatility_view": args.volatility_view,
            "venue": args.venue,
            "interval_code": args.interval_code,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "max_future_candles": args.max_future_candles,
            "after_touch_candles": args.after_touch_candles,
            "context_rows": len(context_rows),
            "evaluated_rows": len(eval_rows),
            "diagnostics": summarize(eval_rows),
        }

        if args.out_json:
            write_json(Path(args.out_json), payload)
        if args.out_csv:
            write_csv(Path(args.out_csv), eval_rows)

        if not args.quiet:
            print(json.dumps(payload, indent=2, sort_keys=True, default=serialize))

    finally:
        try:
            conn.rollback()
        finally:
            conn.close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
