from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.market_context.market_context_builder_v1 import (
    MarketContextCandle,
    build_market_context_for_symbol,
)
from src.market_data.native_short_fib_context_v1 import (
    DEFAULT_ROWS_CSV as DEFAULT_NATIVE_SHORT_ROWS_CSV,
    SHORT_CONTEXT_SOURCE_NAME,
    SHORT_CONTEXT_VERSION,
    NativeShortContextRow,
    load_native_short_context_rows,
)


RUNNER_NAME = "build_market_signal_snapshot_inventory_v1"
RUNNER_VERSION = "0.1"
SCHEMA_VERSION = "market_signal_snapshot_inventory_v1"
DEFAULT_OUTPUT_ROOT = Path("data/research/market_signal_snapshot_inventory_v1")
DEFAULT_VENUE = "bitvavo"
DEFAULT_CANDLE_LOOKBACK_DAYS = 90
DEFAULT_QUOTE_CURRENCY = "EUR"

TIMEFRAME_NATIVE_SHORT = "4h+1h"
TIMEFRAME_4H = "4h"
TIMEFRAME_1H = "1h"

AVAILABILITY_AVAILABLE = "AVAILABLE"
AVAILABILITY_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

COVERAGE_AVAILABLE = "AVAILABLE"
COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_STALE = "STALE"
COVERAGE_SOURCE_MISSING = "SOURCE_MISSING"
COVERAGE_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

ERROR_OK = "OK"

NATIVE_AVAILABLE_STATUS = "NATIVE_SHORT_CONTEXT_AVAILABLE"
NATIVE_STALE_STATUS = "CONTEXT_INVALID_OR_STALE"
NATIVE_MISSING_STATUS = "SYMBOL_CONTEXT_MISSING"
NATIVE_PARTIAL_STATUSES = frozenset({"INSUFFICIENT_4H_HISTORY", "INSUFFICIENT_1H_HISTORY"})
STATE_STALE = "STALE"
STATE_NO_DATA = "NO_DATA"
STATE_LOW_CONFIDENCE = "LOW_CONFIDENCE"

SAFETY_STATEMENT = (
    "research-only, market-only, read-only, non-predictive; creates no strategy logic, "
    "selection logic, trade permission, order intent, account logic, or UI policy"
)


@dataclass(frozen=True)
class InventoryCandle:
    symbol: str
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class SnapshotBuildResult:
    run_id: str
    output_dir: Path
    artifact_paths: dict[str, Path]
    manifest: dict[str, Any]
    rows: list[dict[str, Any]]
    registry: list[dict[str, Any]]


CandleReader = Callable[
    [Any, str, str, list[str], datetime, datetime],
    dict[str, list[InventoryCandle]],
]


def _registry() -> list[dict[str, Any]]:
    return [
        {
            "signal_id": "native_short_context_status",
            "signal_family": "native_short_map_context",
            "technical_meaning": "Canonical native SHORT context row availability/status for the symbol.",
            "source_module": "src.market_data.native_short_fib_context_v1",
            "source_function_or_artifact": "native_short_fib_context_rows_v1.csv",
            "timeframe": TIMEFRAME_NATIVE_SHORT,
            "raw_value_type": "string",
            "normalized_state_semantics": "Existing native SHORT context_status value, or DATA_UNAVAILABLE when the source row is missing.",
            "freshness_source": "latest_primary_close_ts_utc and latest_support_close_ts_utc from the source row",
            "coverage_semantics": "AVAILABLE for NATIVE_SHORT_CONTEXT_AVAILABLE; PARTIAL/STALE/SOURCE_MISSING otherwise.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "native_short_4h_lifecycle_state",
            "signal_family": "native_short_map_context",
            "technical_meaning": "Existing native SHORT primary 4h lifecycle state.",
            "source_module": "src.market_data.native_short_fib_context_v1",
            "source_function_or_artifact": "NativeShortContextRow.primary_4h_lifecycle_state",
            "timeframe": TIMEFRAME_4H,
            "raw_value_type": "string",
            "normalized_state_semantics": "Existing primary_4h_lifecycle_state; no lifecycle reinterpretation.",
            "freshness_source": "latest_primary_close_ts_utc from the source row",
            "coverage_semantics": "Inherits native SHORT context coverage without fallback substitution.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "native_short_1h_support_state",
            "signal_family": "native_short_map_context",
            "technical_meaning": "Existing native SHORT supporting 1h alignment/support state.",
            "source_module": "src.market_data.native_short_fib_context_v1",
            "source_function_or_artifact": "NativeShortContextRow.supporting_1h_state",
            "timeframe": TIMEFRAME_1H,
            "raw_value_type": "string",
            "normalized_state_semantics": "Existing supporting_1h_state; no support reinterpretation.",
            "freshness_source": "latest_support_close_ts_utc from the source row",
            "coverage_semantics": "Inherits native SHORT context coverage without fallback substitution.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "native_short_map_freshness",
            "signal_family": "native_short_map_context",
            "technical_meaning": "Existing native SHORT context freshness status.",
            "source_module": "src.market_data.native_short_fib_context_v1",
            "source_function_or_artifact": "NativeShortContextRow.context_freshness_status",
            "timeframe": TIMEFRAME_NATIVE_SHORT,
            "raw_value_type": "string",
            "normalized_state_semantics": "Existing context_freshness_status, including stale states.",
            "freshness_source": "latest primary/support close timestamp from the source row",
            "coverage_semantics": "STALE when native context_status or freshness status is stale; otherwise inherited.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "native_short_map_lineage",
            "signal_family": "native_short_map_context",
            "technical_meaning": "Existing native SHORT map identity, cycle, rollover, and source-reference lineage.",
            "source_module": "src.market_data.native_short_fib_context_v1",
            "source_function_or_artifact": "NativeShortContextRow map/source lineage fields",
            "timeframe": TIMEFRAME_NATIVE_SHORT,
            "raw_value_type": "object",
            "normalized_state_semantics": "current_map_status when present, otherwise DATA_UNAVAILABLE.",
            "freshness_source": "latest primary/support close timestamp from the source row",
            "coverage_semantics": "Inherits native SHORT context coverage; missing lineage is explicit.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "local_ma_atr_4h_state",
            "signal_family": "local_ma_atr_context",
            "technical_meaning": "Canonical 4h local moving-average/ATR context state.",
            "source_module": "src.market_context.local_ma_atr_context_v1",
            "source_function_or_artifact": "build_local_ma_atr_context via build_market_context_for_symbol",
            "timeframe": TIMEFRAME_4H,
            "raw_value_type": "object",
            "normalized_state_semantics": "Existing LocalMaAtrState value; NO_DATA/STALE/LOW_CONFIDENCE are preserved.",
            "freshness_source": "latest_close_ts_utc returned by LocalMaAtrContextResult",
            "coverage_semantics": "SOURCE_MISSING with no candles; STALE/PARTIAL states are preserved.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "impulse_health_4h_state",
            "signal_family": "impulse_health_context",
            "technical_meaning": "Canonical 4h impulse-health context state.",
            "source_module": "src.market_context.impulse_health_state_v1",
            "source_function_or_artifact": "build_impulse_health_state via build_market_context_for_symbol",
            "timeframe": TIMEFRAME_4H,
            "raw_value_type": "object",
            "normalized_state_semantics": "Existing ImpulseHealthState value; NO_DATA/STALE/LOW_CONFIDENCE are preserved.",
            "freshness_source": "latest_close_ts_utc returned by ImpulseHealthStateResult",
            "coverage_semantics": "SOURCE_MISSING with no candles; STALE/PARTIAL states are preserved.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "extension_context_4h_state",
            "signal_family": "extension_context",
            "technical_meaning": "Existing derived 4h extension-context state from local MA/ATR and impulse-health context.",
            "source_module": "src.market_context.market_context_builder_v1",
            "source_function_or_artifact": "build_extension_context via build_market_context_for_symbol",
            "timeframe": TIMEFRAME_4H,
            "raw_value_type": "object",
            "normalized_state_semantics": "Existing extension_context state only; display hints are excluded from snapshot rows.",
            "freshness_source": "latest 4h local/impulse close timestamp",
            "coverage_semantics": "Worst visible coverage of the local MA/ATR and impulse-health inputs.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "candle_availability_4h",
            "signal_family": "market_candle_observation",
            "technical_meaning": "Presence of obs_market_candle rows at or before the as-of timestamp.",
            "source_module": "obs_market_candle",
            "source_function_or_artifact": "read-only SELECT from obs_market_candle joined to asset",
            "timeframe": TIMEFRAME_4H,
            "raw_value_type": "object",
            "normalized_state_semantics": "CANDLES_AVAILABLE when bounded candles exist; DATA_UNAVAILABLE otherwise.",
            "freshness_source": "latest candle close_ts_utc at or before as_of_ts_utc",
            "coverage_semantics": "SOURCE_MISSING when no bounded candles are present.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "candle_freshness_4h",
            "signal_family": "market_candle_observation",
            "technical_meaning": "Freshness of latest 4h obs_market_candle row relative to as-of timestamp.",
            "source_module": "obs_market_candle",
            "source_function_or_artifact": "read-only SELECT from obs_market_candle joined to asset",
            "timeframe": TIMEFRAME_4H,
            "raw_value_type": "object",
            "normalized_state_semantics": "FRESH, STALE, or DATA_UNAVAILABLE using a timeframe-specific stale threshold.",
            "freshness_source": "latest candle close_ts_utc at or before as_of_ts_utc",
            "coverage_semantics": "STALE when the latest bounded candle is older than the threshold.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "candle_availability_1h",
            "signal_family": "market_candle_observation",
            "technical_meaning": "Presence of obs_market_candle rows at or before the as-of timestamp.",
            "source_module": "obs_market_candle",
            "source_function_or_artifact": "read-only SELECT from obs_market_candle joined to asset",
            "timeframe": TIMEFRAME_1H,
            "raw_value_type": "object",
            "normalized_state_semantics": "CANDLES_AVAILABLE when bounded candles exist; DATA_UNAVAILABLE otherwise.",
            "freshness_source": "latest candle close_ts_utc at or before as_of_ts_utc",
            "coverage_semantics": "SOURCE_MISSING when no bounded candles are present.",
            "available_in_v1_runner": True,
        },
        {
            "signal_id": "candle_freshness_1h",
            "signal_family": "market_candle_observation",
            "technical_meaning": "Freshness of latest 1h obs_market_candle row relative to as-of timestamp.",
            "source_module": "obs_market_candle",
            "source_function_or_artifact": "read-only SELECT from obs_market_candle joined to asset",
            "timeframe": TIMEFRAME_1H,
            "raw_value_type": "object",
            "normalized_state_semantics": "FRESH, STALE, or DATA_UNAVAILABLE using a timeframe-specific stale threshold.",
            "freshness_source": "latest candle close_ts_utc at or before as_of_ts_utc",
            "coverage_semantics": "STALE when the latest bounded candle is older than the threshold.",
            "available_in_v1_runner": True,
        },
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a market-only, research-only, read-only inventory of existing canonical "
            "signal/context primitives per explicit symbol and timeframe."
        )
    )
    parser.add_argument("--symbols", required=True, help="Comma-separated explicit symbols; never inferred.")
    parser.add_argument("--venue", required=True, help="Explicit market venue, e.g. bitvavo.")
    parser.add_argument(
        "--as-of-ts-utc",
        default="",
        help="ISO-8601 UTC as-of timestamp. Defaults to current UTC only when omitted.",
    )
    parser.add_argument(
        "--native-short-context-rows",
        default=str(DEFAULT_NATIVE_SHORT_ROWS_CSV),
        help="Canonical native SHORT context rows CSV source.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Output root; the deterministic run_id subdirectory is created under this path.",
    )
    parser.add_argument("--candle-lookback-days", type=int, default=DEFAULT_CANDLE_LOOKBACK_DAYS)
    parser.add_argument("--database", default=None, help="Optional DB name override for candle reads.")
    return parser.parse_args(argv)


def parse_symbols(text: str) -> list[str]:
    symbols = sorted({part.strip().upper() for part in text.split(",") if part.strip()})
    if not symbols:
        raise ValueError("At least one explicit symbol is required")
    return symbols


def parse_ts_utc(value: str) -> datetime:
    text = value.strip()
    if not text:
        return datetime.now(UTC).replace(microsecond=0)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def format_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    value_utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value_utc.isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, datetime):
        return format_ts(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def deterministic_run_id(
    *,
    venue: str,
    symbols: list[str],
    as_of_ts_utc: datetime,
    native_short_rows_path: Path,
    candle_lookback_days: int,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "symbols": symbols,
        "as_of_ts_utc": format_ts(as_of_ts_utc),
        "native_short_rows_path": str(native_short_rows_path),
        "candle_lookback_days": candle_lookback_days,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    stamp = as_of_ts_utc.strftime("%Y%m%dT%H%M%SZ")
    return f"{SCHEMA_VERSION}_{stamp}_{digest[:12]}"


def _fetch_candles_by_symbol(
    conn: Any,
    venue: str,
    interval_code: str,
    symbols: list[str],
    since_utc: datetime,
    as_of_ts_utc: datetime,
) -> dict[str, list[InventoryCandle]]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT
        a.symbol,
        c.close_ts_utc,
        c.open_price,
        c.high_price,
        c.low_price,
        c.close_price
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol IN ({placeholders})
      AND c.close_ts_utc >= %s
      AND c.close_ts_utc <= %s
    ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, *symbols, since_utc, as_of_ts_utc))
        rows = list(cur.fetchall())

    out: dict[str, list[InventoryCandle]] = {symbol: [] for symbol in symbols}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        close_ts = row.get("close_ts_utc")
        if symbol not in out or close_ts is None:
            continue
        close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
        if close_ts_utc > as_of_ts_utc:
            continue
        out[symbol].append(
            InventoryCandle(
                symbol=symbol,
                close_ts_utc=close_ts_utc,
                open_price=Decimal(str(row["open_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
                close_price=Decimal(str(row["close_price"])),
            )
        )
    return out


def load_candles_from_db(
    *,
    venue: str,
    symbols: list[str],
    as_of_ts_utc: datetime,
    candle_lookback_days: int,
    database: str | None = None,
    candle_reader: CandleReader = _fetch_candles_by_symbol,
) -> dict[str, dict[str, list[InventoryCandle]]]:
    from src.common.db import get_connection

    since_utc = as_of_ts_utc - timedelta(days=candle_lookback_days)
    conn = get_connection(database=database)
    try:
        return {
            TIMEFRAME_4H: candle_reader(conn, venue, TIMEFRAME_4H, symbols, since_utc, as_of_ts_utc),
            TIMEFRAME_1H: candle_reader(conn, venue, TIMEFRAME_1H, symbols, since_utc, as_of_ts_utc),
        }
    finally:
        conn.close()


def _latest_ts(candles: Sequence[InventoryCandle]) -> datetime | None:
    if not candles:
        return None
    return max(candle.close_ts_utc for candle in candles)


def _oldest_ts(candles: Sequence[InventoryCandle]) -> datetime | None:
    if not candles:
        return None
    return min(candle.close_ts_utc for candle in candles)


def _native_source_record_id(row: NativeShortContextRow | None) -> str | None:
    if row is None:
        return None
    if row.map_cycle_id:
        return row.map_cycle_id
    if row.source_primary_ref or row.source_support_ref:
        return "|".join(part for part in (row.source_primary_ref, row.source_support_ref) if part)
    return row.symbol


def _native_lineage(row: NativeShortContextRow | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "map_cycle_id": row.map_cycle_id,
        "current_map_status": row.current_map_status,
        "previous_map_cycle_id": row.previous_map_cycle_id,
        "previous_map_lifecycle_state": row.previous_map_lifecycle_state,
        "primary_4h_lifecycle_state": row.primary_4h_lifecycle_state,
        "supporting_1h_state": row.supporting_1h_state,
        "rollover_state": row.rollover_state,
        "selection_reason": row.selection_reason,
        "source_primary_ref": row.source_primary_ref,
        "source_support_ref": row.source_support_ref,
        "source_name": row.source_name,
        "source_version": row.source_version,
    }


def _native_freshness(row: NativeShortContextRow | None, timeframe: str) -> datetime | None:
    if row is None:
        return None
    if timeframe == TIMEFRAME_1H:
        return row.latest_support_close_ts_utc
    if timeframe == TIMEFRAME_4H:
        return row.latest_primary_close_ts_utc
    candidates = [row.latest_primary_close_ts_utc, row.latest_support_close_ts_utc]
    present = [candidate for candidate in candidates if candidate is not None]
    return max(present) if present else None


def _native_coverage(row: NativeShortContextRow | None, *, source_missing: bool) -> str:
    if source_missing or row is None:
        return COVERAGE_SOURCE_MISSING
    if row.context_status == NATIVE_AVAILABLE_STATUS:
        return COVERAGE_AVAILABLE
    if row.context_status == NATIVE_STALE_STATUS or row.context_freshness_status.startswith("STALE"):
        return COVERAGE_STALE
    if row.context_status in NATIVE_PARTIAL_STATUSES:
        return COVERAGE_PARTIAL
    if row.context_status == NATIVE_MISSING_STATUS:
        return COVERAGE_SOURCE_MISSING
    return COVERAGE_DATA_UNAVAILABLE


def _native_availability(row: NativeShortContextRow | None, *, source_missing: bool) -> str:
    if source_missing or row is None or row.context_status == NATIVE_MISSING_STATUS:
        return AVAILABILITY_DATA_UNAVAILABLE
    return AVAILABILITY_AVAILABLE


def _row(
    *,
    symbol: str,
    as_of_ts_utc: datetime,
    timeframe: str,
    signal_id: str,
    signal_family: str,
    raw_value: Any,
    normalized_state: str,
    source_module: str,
    source_record_id: str | None,
    source_lineage: Any,
    freshness_ts_utc: datetime | str | None,
    coverage_status: str,
    availability_status: str,
    error_status: str = ERROR_OK,
) -> dict[str, Any]:
    parsed_freshness = (
        parse_ts_utc(freshness_ts_utc)
        if isinstance(freshness_ts_utc, str) and freshness_ts_utc
        else freshness_ts_utc
    )
    return {
        "symbol": symbol,
        "as_of_ts_utc": format_ts(as_of_ts_utc),
        "timeframe": timeframe,
        "signal_id": signal_id,
        "signal_family": signal_family,
        "raw_value": _json_safe(raw_value),
        "normalized_state": normalized_state,
        "source_module": source_module,
        "source_record_id": source_record_id,
        "source_lineage": _json_safe(source_lineage),
        "freshness_ts_utc": format_ts(parsed_freshness),
        "coverage_status": coverage_status,
        "availability_status": availability_status,
        "error_status": error_status,
    }


def _market_context_candles(candles: Sequence[InventoryCandle], as_of_ts_utc: datetime) -> list[MarketContextCandle]:
    bounded = [candle for candle in candles if candle.close_ts_utc <= as_of_ts_utc]
    return [
        MarketContextCandle(
            close_ts_utc=candle.close_ts_utc,
            open_price=candle.open_price,
            high_price=candle.high_price,
            low_price=candle.low_price,
            close_price=candle.close_price,
        )
        for candle in sorted(bounded, key=lambda c: c.close_ts_utc)
    ]


def _builder_coverage(*, state: str, candle_count: int) -> str:
    if candle_count <= 0:
        return COVERAGE_SOURCE_MISSING
    if state == STATE_STALE:
        return COVERAGE_STALE
    if state in {STATE_NO_DATA, STATE_LOW_CONFIDENCE}:
        return COVERAGE_PARTIAL
    return COVERAGE_AVAILABLE


def _builder_availability(*, coverage_status: str) -> str:
    if coverage_status == COVERAGE_SOURCE_MISSING:
        return AVAILABILITY_DATA_UNAVAILABLE
    return AVAILABILITY_AVAILABLE


def _worst_coverage(*statuses: str) -> str:
    order = {
        COVERAGE_SOURCE_MISSING: 5,
        COVERAGE_DATA_UNAVAILABLE: 4,
        COVERAGE_STALE: 3,
        COVERAGE_PARTIAL: 2,
        COVERAGE_AVAILABLE: 1,
    }
    return max(statuses, key=lambda status: order.get(status, 0))


def _candle_state(
    *,
    candles: Sequence[InventoryCandle],
    as_of_ts_utc: datetime,
    stale_after: timedelta,
) -> tuple[str, str, str]:
    if not candles:
        return "DATA_UNAVAILABLE", COVERAGE_SOURCE_MISSING, AVAILABILITY_DATA_UNAVAILABLE
    latest = _latest_ts(candles)
    if latest is not None and as_of_ts_utc - latest > stale_after:
        return STATE_STALE, COVERAGE_STALE, AVAILABILITY_AVAILABLE
    return "CANDLES_AVAILABLE", COVERAGE_AVAILABLE, AVAILABILITY_AVAILABLE


def build_snapshot_rows(
    *,
    symbols: list[str],
    venue: str,
    as_of_ts_utc: datetime,
    native_rows: dict[str, NativeShortContextRow],
    native_source_missing: bool,
    candles_by_timeframe: dict[str, dict[str, list[InventoryCandle]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    registry_by_key = {(entry["signal_id"], entry["timeframe"]): entry for entry in _registry()}

    for symbol in symbols:
        native_row = native_rows.get(symbol)
        native_coverage = _native_coverage(native_row, source_missing=native_source_missing)
        native_availability = _native_availability(native_row, source_missing=native_source_missing)
        native_lineage = _native_lineage(native_row)
        native_record_id = _native_source_record_id(native_row)

        def add_native(signal_id: str, timeframe: str, raw_value: Any, normalized_state: str) -> None:
            entry = registry_by_key[(signal_id, timeframe)]
            rows.append(
                _row(
                    symbol=symbol,
                    as_of_ts_utc=as_of_ts_utc,
                    timeframe=timeframe,
                    signal_id=signal_id,
                    signal_family=entry["signal_family"],
                    raw_value=raw_value,
                    normalized_state=normalized_state,
                    source_module=entry["source_module"],
                    source_record_id=native_record_id,
                    source_lineage=native_lineage,
                    freshness_ts_utc=_native_freshness(native_row, timeframe),
                    coverage_status=native_coverage,
                    availability_status=native_availability,
                )
            )

        add_native(
            "native_short_context_status",
            TIMEFRAME_NATIVE_SHORT,
            None if native_row is None else native_row.context_status,
            "DATA_UNAVAILABLE" if native_row is None else native_row.context_status,
        )
        add_native(
            "native_short_4h_lifecycle_state",
            TIMEFRAME_4H,
            None if native_row is None else native_row.primary_4h_lifecycle_state,
            "DATA_UNAVAILABLE" if native_row is None else native_row.primary_4h_lifecycle_state,
        )
        add_native(
            "native_short_1h_support_state",
            TIMEFRAME_1H,
            None if native_row is None else native_row.supporting_1h_state,
            "DATA_UNAVAILABLE" if native_row is None else native_row.supporting_1h_state,
        )
        add_native(
            "native_short_map_freshness",
            TIMEFRAME_NATIVE_SHORT,
            None if native_row is None else native_row.context_freshness_status,
            "DATA_UNAVAILABLE" if native_row is None else native_row.context_freshness_status,
        )
        add_native(
            "native_short_map_lineage",
            TIMEFRAME_NATIVE_SHORT,
            native_lineage,
            "DATA_UNAVAILABLE" if native_row is None else (native_row.current_map_status or "DATA_UNAVAILABLE"),
        )

        candles_4h = [
            candle
            for candle in candles_by_timeframe.get(TIMEFRAME_4H, {}).get(symbol, [])
            if candle.close_ts_utc <= as_of_ts_utc
        ]
        candles_1h = [
            candle
            for candle in candles_by_timeframe.get(TIMEFRAME_1H, {}).get(symbol, [])
            if candle.close_ts_utc <= as_of_ts_utc
        ]
        market_context = build_market_context_for_symbol(
            candles=_market_context_candles(candles_4h, as_of_ts_utc),
            now_utc=as_of_ts_utc,
        )

        local_raw = market_context["local_ma_atr_context"]
        local_state = str(local_raw["state"])
        local_coverage = _builder_coverage(state=local_state, candle_count=len(candles_4h))
        entry = registry_by_key[("local_ma_atr_4h_state", TIMEFRAME_4H)]
        rows.append(
            _row(
                symbol=symbol,
                as_of_ts_utc=as_of_ts_utc,
                timeframe=TIMEFRAME_4H,
                signal_id="local_ma_atr_4h_state",
                signal_family=entry["signal_family"],
                raw_value=local_raw,
                normalized_state=local_state,
                source_module=entry["source_module"],
                source_record_id="obs_market_candle:4h",
                source_lineage={"venue": venue, "interval_code": TIMEFRAME_4H, "candle_count": len(candles_4h)},
                freshness_ts_utc=local_raw.get("latest_close_ts_utc"),
                coverage_status=local_coverage,
                availability_status=_builder_availability(coverage_status=local_coverage),
            )
        )

        impulse_raw = market_context["impulse_health"]
        impulse_state = str(impulse_raw["state"])
        impulse_coverage = _builder_coverage(state=impulse_state, candle_count=len(candles_4h))
        entry = registry_by_key[("impulse_health_4h_state", TIMEFRAME_4H)]
        rows.append(
            _row(
                symbol=symbol,
                as_of_ts_utc=as_of_ts_utc,
                timeframe=TIMEFRAME_4H,
                signal_id="impulse_health_4h_state",
                signal_family=entry["signal_family"],
                raw_value=impulse_raw,
                normalized_state=impulse_state,
                source_module=entry["source_module"],
                source_record_id="obs_market_candle:4h",
                source_lineage={"venue": venue, "interval_code": TIMEFRAME_4H, "candle_count": len(candles_4h)},
                freshness_ts_utc=impulse_raw.get("latest_close_ts_utc"),
                coverage_status=impulse_coverage,
                availability_status=_builder_availability(coverage_status=impulse_coverage),
            )
        )

        extension_raw = market_context["extension_context"]
        extension_state = str(extension_raw["state"])
        extension_coverage = _worst_coverage(local_coverage, impulse_coverage)
        extension_freshness = local_raw.get("latest_close_ts_utc") or impulse_raw.get("latest_close_ts_utc")
        entry = registry_by_key[("extension_context_4h_state", TIMEFRAME_4H)]
        rows.append(
            _row(
                symbol=symbol,
                as_of_ts_utc=as_of_ts_utc,
                timeframe=TIMEFRAME_4H,
                signal_id="extension_context_4h_state",
                signal_family=entry["signal_family"],
                raw_value={
                    "state": extension_state,
                    "input_states": {
                        "local_ma_atr_state": local_state,
                        "impulse_health_state": impulse_state,
                    },
                    "warnings": extension_raw.get("warnings", []),
                },
                normalized_state=extension_state,
                source_module=entry["source_module"],
                source_record_id="local_ma_atr_4h_state|impulse_health_4h_state",
                source_lineage={"venue": venue, "interval_code": TIMEFRAME_4H, "candle_count": len(candles_4h)},
                freshness_ts_utc=extension_freshness,
                coverage_status=extension_coverage,
                availability_status=_builder_availability(coverage_status=extension_coverage),
            )
        )

        for timeframe, candles, stale_after in (
            (TIMEFRAME_4H, candles_4h, timedelta(hours=8)),
            (TIMEFRAME_1H, candles_1h, timedelta(hours=3)),
        ):
            latest = _latest_ts(candles)
            oldest = _oldest_ts(candles)
            raw_candle_value = {
                "venue": venue,
                "interval_code": timeframe,
                "candle_count": len(candles),
                "oldest_close_ts_utc": format_ts(oldest),
                "latest_close_ts_utc": format_ts(latest),
                "as_of_exclusive_future_candles": 0,
            }
            state, coverage, availability = _candle_state(
                candles=candles,
                as_of_ts_utc=as_of_ts_utc,
                stale_after=stale_after,
            )
            for signal_id, normalized_state in (
                (f"candle_availability_{timeframe}", "CANDLES_AVAILABLE" if candles else "DATA_UNAVAILABLE"),
                (f"candle_freshness_{timeframe}", state if candles else "DATA_UNAVAILABLE"),
            ):
                entry = registry_by_key[(signal_id, timeframe)]
                rows.append(
                    _row(
                        symbol=symbol,
                        as_of_ts_utc=as_of_ts_utc,
                        timeframe=timeframe,
                        signal_id=signal_id,
                        signal_family=entry["signal_family"],
                        raw_value=raw_candle_value,
                        normalized_state=normalized_state,
                        source_module=entry["source_module"],
                        source_record_id=f"obs_market_candle:{timeframe}",
                        source_lineage={"venue": venue, "interval_code": timeframe},
                        freshness_ts_utc=latest,
                        coverage_status=coverage if signal_id.startswith("candle_freshness") else (COVERAGE_AVAILABLE if candles else COVERAGE_SOURCE_MISSING),
                        availability_status=availability,
                    )
                )

    return sorted(rows, key=lambda row: (row["symbol"], row["signal_id"], row["timeframe"]))


def build_coverage_summary(rows: Sequence[dict[str, Any]], eligible_symbols: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["signal_id"]), str(row["timeframe"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (signal_id, timeframe), items in sorted(grouped.items()):
        out.append(
            {
                "signal_id": signal_id,
                "timeframe": timeframe,
                "eligible_symbols": eligible_symbols,
                "available_symbols": sum(1 for item in items if item["coverage_status"] == COVERAGE_AVAILABLE),
                "partial_symbols": sum(1 for item in items if item["coverage_status"] == COVERAGE_PARTIAL),
                "stale_symbols": sum(1 for item in items if item["coverage_status"] == COVERAGE_STALE),
                "unavailable_symbols": sum(
                    1
                    for item in items
                    if item["coverage_status"] in {COVERAGE_SOURCE_MISSING, COVERAGE_DATA_UNAVAILABLE}
                ),
                "error_symbols": sum(1 for item in items if item["error_status"] != ERROR_OK),
            }
        )
    return out


def build_freshness_summary(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["signal_id"]), str(row["timeframe"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (signal_id, timeframe), items in sorted(grouped.items()):
        timestamps = [parse_ts_utc(str(item["freshness_ts_utc"])) for item in items if item.get("freshness_ts_utc")]
        out.append(
            {
                "signal_id": signal_id,
                "timeframe": timeframe,
                "freshest_timestamp": format_ts(max(timestamps)) if timestamps else "",
                "oldest_available_timestamp": format_ts(min(timestamps)) if timestamps else "",
                "stale_count": sum(1 for item in items if item["coverage_status"] == COVERAGE_STALE),
                "missing_timestamp_count": sum(1 for item in items if not item.get("freshness_ts_utc")),
            }
        )
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(_json_safe(row), sort_keys=True, separators=(",", ":")) + "\n")


def _write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(
    *,
    symbols: list[str],
    venue: str,
    as_of_ts_utc: datetime,
    native_short_rows_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    candle_lookback_days: int = DEFAULT_CANDLE_LOOKBACK_DAYS,
    database: str | None = None,
    candles_by_timeframe: dict[str, dict[str, list[InventoryCandle]]] | None = None,
    native_rows_override: dict[str, NativeShortContextRow] | None = None,
    native_source_missing_override: bool | None = None,
    generated_at_ts_utc: datetime | None = None,
) -> SnapshotBuildResult:
    resolved_symbols = sorted({symbol.upper() for symbol in symbols})
    if not resolved_symbols:
        raise ValueError("At least one explicit symbol is required")
    resolved_as_of = as_of_ts_utc.astimezone(UTC).replace(microsecond=0)
    if candle_lookback_days <= 0:
        raise ValueError("candle_lookback_days must be positive")

    if native_rows_override is None:
        native_rows, native_source_missing = load_native_short_context_rows(native_short_rows_path)
    else:
        native_rows = native_rows_override
        native_source_missing = bool(native_source_missing_override)

    if candles_by_timeframe is None:
        candles_by_timeframe = load_candles_from_db(
            venue=venue,
            symbols=resolved_symbols,
            as_of_ts_utc=resolved_as_of,
            candle_lookback_days=candle_lookback_days,
            database=database,
        )

    run_id = deterministic_run_id(
        venue=venue,
        symbols=resolved_symbols,
        as_of_ts_utc=resolved_as_of,
        native_short_rows_path=native_short_rows_path,
        candle_lookback_days=candle_lookback_days,
    )
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    registry = _registry()
    rows = build_snapshot_rows(
        symbols=resolved_symbols,
        venue=venue,
        as_of_ts_utc=resolved_as_of,
        native_rows={key.upper(): value for key, value in native_rows.items()},
        native_source_missing=native_source_missing,
        candles_by_timeframe=candles_by_timeframe,
    )
    coverage_summary = build_coverage_summary(rows, eligible_symbols=len(resolved_symbols))
    freshness_summary = build_freshness_summary(rows)

    artifact_paths = {
        "signal_registry.json": output_dir / "signal_registry.json",
        "signal_snapshot_rows.jsonl": output_dir / "signal_snapshot_rows.jsonl",
        "coverage_summary.csv": output_dir / "coverage_summary.csv",
        "freshness_summary.csv": output_dir / "freshness_summary.csv",
        "manifest.json": output_dir / "manifest.json",
    }
    _write_json(artifact_paths["signal_registry.json"], registry)
    _write_jsonl(artifact_paths["signal_snapshot_rows.jsonl"], rows)
    _write_csv(
        artifact_paths["coverage_summary.csv"],
        coverage_summary,
        [
            "signal_id",
            "timeframe",
            "eligible_symbols",
            "available_symbols",
            "partial_symbols",
            "stale_symbols",
            "unavailable_symbols",
            "error_symbols",
        ],
    )
    _write_csv(
        artifact_paths["freshness_summary.csv"],
        freshness_summary,
        [
            "signal_id",
            "timeframe",
            "freshest_timestamp",
            "oldest_available_timestamp",
            "stale_count",
            "missing_timestamp_count",
        ],
    )

    artifact_hashes = {
        name: _sha256_file(path)
        for name, path in artifact_paths.items()
        if name != "manifest.json"
    }
    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "runner_name": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "generated_at_ts_utc": format_ts((generated_at_ts_utc or resolved_as_of).astimezone(UTC).replace(microsecond=0)),
        "as_of_ts_utc": format_ts(resolved_as_of),
        "run_id": run_id,
        "venue": venue,
        "explicit_symbols": resolved_symbols,
        "source_artifact_paths": {
            "native_short_context_rows": str(native_short_rows_path),
            "obs_market_candle": "database:obs_market_candle",
        },
        "source_module_versions": {
            "src.research.build_market_signal_snapshot_inventory_v1": RUNNER_VERSION,
            SHORT_CONTEXT_SOURCE_NAME: SHORT_CONTEXT_VERSION,
            "src.market_context.local_ma_atr_context_v1": "canonical_constants",
            "src.market_context.impulse_health_state_v1": "canonical_constants",
            "src.market_context.market_context_builder_v1": "canonical_constants",
        },
        "row_counts": {
            "signal_registry": len(registry),
            "signal_snapshot_rows": len(rows),
            "coverage_summary": len(coverage_summary),
            "freshness_summary": len(freshness_summary),
        },
        "artifact_filenames": list(artifact_paths.keys()),
        "artifact_sha256": artifact_hashes,
        "manifest_hash_note": (
            "manifest.json hash is computed from the canonical manifest payload before embedding "
            "artifact_sha256.manifest.json, avoiding self-referential file-byte hash instability"
        ),
        "safety_statement": SAFETY_STATEMENT,
    }
    manifest_preimage = json.dumps(
        _json_safe(manifest_payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest_payload["artifact_sha256"]["manifest.json"] = hashlib.sha256(manifest_preimage).hexdigest()
    _write_json(artifact_paths["manifest.json"], manifest_payload)

    return SnapshotBuildResult(
        run_id=run_id,
        output_dir=output_dir,
        artifact_paths=artifact_paths,
        manifest=manifest_payload,
        rows=rows,
        registry=registry,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols(args.symbols)
    as_of_ts_utc = parse_ts_utc(args.as_of_ts_utc)
    result = build_inventory(
        symbols=symbols,
        venue=args.venue,
        as_of_ts_utc=as_of_ts_utc,
        native_short_rows_path=Path(args.native_short_context_rows),
        output_root=Path(args.output_dir),
        candle_lookback_days=args.candle_lookback_days,
        database=args.database,
    )
    print(f"report={RUNNER_NAME}")
    print(f"version={RUNNER_VERSION}")
    print(f"run_id={result.run_id}")
    print(f"output_dir={result.output_dir}")
    print(f"symbol_count={len(symbols)}")
    print(f"snapshot_row_count={len(result.rows)}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
