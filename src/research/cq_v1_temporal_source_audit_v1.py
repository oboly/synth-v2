from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

MRP_MODEL_VERSION = "1.0"
SECTOR_MODEL_VERSION = "sector-rotation-v1.0.0"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    table_name: str
    timestamp_column: str
    pit_rule: str
    required_for_temporal_cq: bool
    where_sql: str
    where_params: tuple[Any, ...]


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        source_id="asset_interval_quality",
        table_name="asset_interval_quality",
        timestamp_column="asof_ts_utc",
        pit_rule="latest row at or before candidate as-of per asset+venue+interval_code",
        required_for_temporal_cq=True,
        where_sql="venue=%s AND interval_code IN ('1d','4h','1h')",
        where_params=("{venue}",),
    ),
    SourceSpec(
        source_id="signal_engine_state",
        table_name="signal_engine_state",
        timestamp_column="signal_ts_utc",
        pit_rule="latest row at or before candidate as-of per asset+venue+interval_code",
        required_for_temporal_cq=True,
        where_sql="venue=%s AND interval_code IN ('1d','4h','1h')",
        where_params=("{venue}",),
    ),
    SourceSpec(
        source_id="mrp_aggregate",
        table_name="market_rotation_pressure_snapshot_v1",
        timestamp_column="as_of_ts_utc",
        pit_rule="latest row at or before candidate as-of per venue+model_version",
        required_for_temporal_cq=True,
        where_sql="venue=%s AND model_version=%s",
        where_params=("{venue}", MRP_MODEL_VERSION),
    ),
    SourceSpec(
        source_id="mrp_asset",
        table_name="market_rotation_pressure_observation_v1",
        timestamp_column="as_of_ts_utc",
        pit_rule="latest row at or before candidate as-of per asset+model_version; venue bound through snapshot identity",
        required_for_temporal_cq=True,
        where_sql="model_version=%s",
        where_params=(MRP_MODEL_VERSION,),
    ),
    SourceSpec(
        source_id="sector_rotation",
        table_name="sector_rotation_snapshot",
        timestamp_column="asof_ts_utc",
        pit_rule="latest row at or before candidate as-of per sector+venue+4h+model_version",
        required_for_temporal_cq=False,
        where_sql="venue=%s AND window_code='4h' AND model_version=%s",
        where_params=("{venue}", SECTOR_MODEL_VERSION),
    ),
    SourceSpec(
        source_id="canonical_candles_15m",
        table_name="obs_market_candle",
        timestamp_column="close_ts_utc",
        pit_rule="exact persisted 15m candle close; future rows labels only",
        required_for_temporal_cq=True,
        where_sql="venue=%s AND interval_code='15m'",
        where_params=("{venue}",),
    ),
)


def bind_params(spec: SourceSpec, *, venue: str) -> tuple[Any, ...]:
    return tuple(venue if value == "{venue}" else value for value in spec.where_params)


def classify_history(*, row_count: int, distinct_ts_count: int) -> str:
    if row_count <= 0 or distinct_ts_count <= 0:
        return "UNAVAILABLE_NO_ROWS"
    if distinct_ts_count < 2:
        return "BLOCKED_SINGLE_TIMESTAMP_ONLY"
    return "REPLAYABLE_HISTORY_PRESENT"


def source_result(
    spec: SourceSpec,
    *,
    row_count: int,
    distinct_ts_count: int,
    first_ts: Any,
    last_ts: Any,
    indexes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    index_rows = [dict(row) for row in indexes]
    state = classify_history(row_count=row_count, distinct_ts_count=distinct_ts_count)
    return {
        "source_id": spec.source_id,
        "table_name": spec.table_name,
        "timestamp_column": spec.timestamp_column,
        "pit_rule": spec.pit_rule,
        "required_for_temporal_cq": spec.required_for_temporal_cq,
        "row_count": int(row_count),
        "distinct_timestamp_count": int(distinct_ts_count),
        "first_ts_utc": None if first_ts is None else str(first_ts),
        "last_ts_utc": None if last_ts is None else str(last_ts),
        "history_state": state,
        "indexes": index_rows,
    }


def overall_state(results: Iterable[Mapping[str, Any]]) -> tuple[str, list[str]]:
    blockers = [
        str(row["source_id"])
        for row in results
        if bool(row.get("required_for_temporal_cq"))
        and row.get("history_state") != "REPLAYABLE_HISTORY_PRESENT"
    ]
    if blockers:
        return "BLOCKED_SOURCE_HISTORY", blockers
    return "READY_TO_FREEZE_TEMPORAL_SAMPLING", []
