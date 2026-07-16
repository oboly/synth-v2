from __future__ import annotations

"""Persisted market-only native SHORT context snapshot contract.

The projection consumes only current persisted native SHORT authorities.  It
does not select maps, calculate Fib geometry, evaluate candles, or derive
lifecycle/freshness from wall-clock time.
"""

import csv
import fcntl
import hashlib
import io
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.market_data.native_short_fib_context_v1 import (
    CSV_FIELDS as LEGACY_CSV_FIELDS,
    STATUS_AVAILABLE,
    STATUS_STALE_OR_INVALID,
    STATUS_SYMBOL_MISSING,
)


SCHEMA_VERSION = "native_short_fib_context_snapshot_v1"
ROW_SCHEMA_VERSION = "native_short_fib_context_snapshot_row_v1"
PRODUCER_NAME = "native_short_fib_context_snapshot_v1"
PRODUCER_VERSION = "0.1"
MANIFEST_NAME = "manifest_v1.json"
ROWS_NAME = "native_short_fib_context_rows_v1.csv"
BUNDLE_NAME = "snapshot_bundle_v1.json"
PUBLICATION_LOCK_NAME = ".native_short_context_snapshot_v1.publish.lock"

FRESH = "FRESH"
STALE = "STALE"
MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"
FRESHNESS_VALUES = (FRESH, STALE, MISSING, UNAVAILABLE)

SAFETY_MARKERS: dict[str, int | str | bool] = {
    "broker_private_calls": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "account_awareness": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "reporting_writes_market_truth": False,
    "new_scheduler": False,
}

PROVENANCE_FIELDS = [
    "native_map_id",
    "scope_id",
    "scope_status_id",
    "scope_support_state",
    "scope_status_code",
    "scope_status_reason_code",
    "source_freshness_state",
    "observation_freshness_state",
    "actionability_state",
    "projection_as_of_utc",
    "projection_rebuilt_at_utc",
    "map_published_at_utc",
    "map_structure_hash",
    "latest_observation_id",
    "latest_run_id",
    "latest_observed_at_utc",
    "latest_generation_event_id",
    "latest_generation_event_ts_utc",
    "latest_lifecycle_event_id",
    "latest_lifecycle_event_ts_utc",
    "level_status_ids_json",
    "level_status_as_of_utc",
    "field_availability_json",
]
CSV_FIELDS = [*LEGACY_CSV_FIELDS, *PROVENANCE_FIELDS]

_GEOMETRY_KEYS = (
    "breakout_gate",
    "ext_1_272",
    "ext_1_618",
    "ext_2_000",
    "reload_r382",
    "reload_r500",
    "reload_r618",
    "reload_r786",
)
_ROLE_TO_GEOMETRY = {
    "SELL_EXT_1_272": "ext_1_272",
    "SELL_EXT_1_618": "ext_1_618",
    "SELL_EXT_2_000": "ext_2_000",
}
_UNAVAILABLE_LEGACY_FIELDS = (
    "latest_primary_close_price",
    "supporting_1h_state",
    "max_primary_high_since_anchor",
    "min_primary_low_since_anchor",
    "current_map_status",
    "previous_map_lifecycle_state",
    "rollover_state",
)
_AUTHORITY_AVAILABILITY_FIELDS = (
    "native_map_id",
    "map_cycle_id",
    "anchor_start_ts_utc",
    "anchor_end_ts_utc",
    "anchor_low_price",
    "anchor_high_price",
    "breakout_gate_price",
    "ext_1_272_price",
    "ext_1_618_price",
    "ext_2_000_price",
    "active_target_levels_json",
    "previous_target_levels_json",
    "reload_r382_price",
    "reload_r500_price",
    "reload_r618_price",
    "reload_r786_price",
    "invalidation_price",
    "primary_4h_lifecycle_state",
    "latest_primary_close_ts_utc",
    "latest_support_close_ts_utc",
    "source_primary_ref",
    "source_support_ref",
    "previous_map_cycle_id",
    "latest_observation_id",
    "latest_run_id",
    "latest_generation_event_id",
    "latest_lifecycle_event_id",
)
_NON_SEMANTIC_ROW_FIELDS = frozenset(
    {
        "scope_status_id",
        "projection_rebuilt_at_utc",
        "level_status_ids_json",
    }
)


class SnapshotContractError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotBuild:
    rows: tuple[dict[str, str], ...]
    content_digest: str
    snapshot_id: str
    counts: dict[str, int]
    overall_freshness_state: str
    source_as_of_timestamps: dict[str, str]


@dataclass(frozen=True)
class PublicationResult:
    status: str
    snapshot_id: str
    content_digest: str
    manifest_path: Path
    rows_path: Path
    bundle_path: Path


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _iso(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise SnapshotContractError(f"invalid timestamp: {value}") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise SnapshotContractError(f"invalid timestamp type: {type(value).__name__}")
    if parsed.tzinfo is None:
        raise SnapshotContractError(f"timestamp must be absolute: {value}")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def persisted_db_datetime_utc(value: Any, *, table: str, field: str) -> datetime | None:
    """Type a MariaDB UTC DATETIME value without inventing a missing timestamp."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise SnapshotContractError(f"{table}.{field} must be a persisted datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SnapshotContractError(f"invalid decimal: {value}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise SnapshotContractError(f"decimal must be finite and positive: {value}")
    text = format(parsed, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _json_object(value: Any, *, field: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(_text(value) or "{}")
    except json.JSONDecodeError as exc:
        raise SnapshotContractError(f"{field} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SnapshotContractError(f"{field} must be a JSON object")
    return parsed


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def _blank_row(scope: Mapping[str, Any]) -> dict[str, str]:
    row = {field: "" for field in CSV_FIELDS}
    row.update(
        {
            "symbol": _text(scope.get("symbol")).upper(),
            "venue": _text(scope.get("venue")),
            "quote_currency": _text(scope.get("quote_currency")),
            "fib_trading_horizon": _text(scope.get("fib_trading_horizon")),
            "primary_interval": _text(scope.get("primary_interval")),
            "supporting_interval": _text(scope.get("supporting_interval")),
            "source_name": PRODUCER_NAME,
            "source_version": PRODUCER_VERSION,
            "scope_id": _text(scope.get("scope_id")),
            "scope_support_state": _text(scope.get("scope_support_state")),
            "scope_status_id": _text(scope.get("scope_status_id")),
            "scope_status_code": _text(scope.get("scope_status_code")),
            "scope_status_reason_code": _text(scope.get("scope_status_reason_code")),
            "source_freshness_state": _text(scope.get("source_freshness_state")),
            "observation_freshness_state": _text(scope.get("observation_freshness_state")),
            "actionability_state": _text(scope.get("actionability_state")),
            "selection_reason": _text(scope.get("scope_status_reason_code")),
            "primary_4h_lifecycle_state": _text(scope.get("map_lifecycle_state")) or UNAVAILABLE,
            "supporting_1h_state": UNAVAILABLE,
            "current_map_status": UNAVAILABLE,
            "previous_map_lifecycle_state": UNAVAILABLE,
            "rollover_state": UNAVAILABLE,
        }
    )
    for source, target in (
        ("projection_as_of_utc", "projection_as_of_utc"),
        ("rebuilt_at_utc", "projection_rebuilt_at_utc"),
        ("latest_observed_at_utc", "latest_observed_at_utc"),
        ("primary_latest_candle_ts_utc", "latest_primary_close_ts_utc"),
        ("supporting_latest_candle_ts_utc", "latest_support_close_ts_utc"),
    ):
        row[target] = _iso(scope.get(source)) if scope.get(source) is not None else ""
    for field in (
        "latest_observation_id",
        "latest_run_id",
        "latest_generation_event_id",
        "latest_lifecycle_event_id",
    ):
        row[field] = _text(scope.get(field))
    return row


def _base_freshness(scope: Mapping[str, Any]) -> str:
    if _text(scope.get("scope_support_state")) != "SUPPORTED":
        return UNAVAILABLE
    if not scope.get("scope_status_id"):
        return MISSING
    if not scope.get("projection_as_of_utc"):
        return MISSING
    code = _text(scope.get("scope_status_code"))
    source = _text(scope.get("source_freshness_state"))
    observation = _text(scope.get("observation_freshness_state"))
    if code in {"CONFIGURATION_UNAVAILABLE", "SOURCE_UNAVAILABLE"}:
        return UNAVAILABLE
    if not scope.get("primary_latest_candle_ts_utc") or not scope.get("supporting_latest_candle_ts_utc"):
        return MISSING
    if code in {"SOURCE_STALE", "SCOPE_RECENTLY_ADDED", "OBSERVATION_OVERDUE"}:
        return STALE
    if source != "SOURCE_CURRENT" or observation != "OBSERVATION_CURRENT":
        return STALE
    return FRESH


def _geometry(map_row: Mapping[str, Any]) -> dict[str, str]:
    ratios = _json_object(map_row.get("fib_ratios_json"), field="fib_ratios_json")
    geometry = {key: _decimal_text(ratios.get(key)) for key in _GEOMETRY_KEYS}
    geometry.update(
        {
            "anchor_start_ts_utc": _iso(map_row.get("anchor_low_ts_utc")),
            "anchor_end_ts_utc": _iso(map_row.get("anchor_high_ts_utc")),
            "anchor_low_price": _decimal_text(map_row.get("anchor_low_price")),
            "anchor_high_price": _decimal_text(map_row.get("anchor_high_price")),
            "invalidation_price": _decimal_text(map_row.get("invalidation_price")),
        }
    )
    if any(not value for value in geometry.values()):
        raise SnapshotContractError("selected map geometry is incomplete")
    return geometry


def _target_groups(
    levels: Sequence[Mapping[str, Any]],
    *,
    map_id: str,
    map_cycle_id: str,
    projection_as_of_utc: str,
    geometry: Mapping[str, str],
) -> tuple[list[str], list[str], list[str], str]:
    by_role: dict[str, Mapping[str, Any]] = {}
    for level in levels:
        role = _text(level.get("canonical_map_level_role"))
        if role in by_role:
            raise SnapshotContractError(f"duplicate map-level role: {role}")
        by_role[role] = level
    if set(by_role) != set(_ROLE_TO_GEOMETRY):
        raise SnapshotContractError("selected map must have exactly the three V1 SELL level roles")
    active: list[str] = []
    previous: list[str] = []
    ids: list[str] = []
    level_as_of_values: set[str] = set()
    for role in _ROLE_TO_GEOMETRY:
        level = by_role[role]
        if _text(level.get("current_map_id")) != map_id or _text(level.get("map_cycle_id")) != map_cycle_id:
            raise SnapshotContractError("map-level identity does not match selected projection map")
        level_as_of = _iso(level.get("level_status_as_of_utc"))
        if level_as_of != projection_as_of_utc:
            raise SnapshotContractError("map-level as-of does not match projection as-of")
        level_as_of_values.add(level_as_of)
        price = _decimal_text(level.get("canonical_unrounded_price"))
        if price != geometry[_ROLE_TO_GEOMETRY[role]]:
            raise SnapshotContractError(f"map-level price does not match immutable named geometry: {role}")
        state = _text(level.get("level_lifecycle_state"))
        if state == "ACTIVE":
            active.append(price)
        elif state in {"REACHED", "PASSED", "COMPLETED"}:
            previous.append(price)
        elif state != "HISTORICAL":
            raise SnapshotContractError(f"unsupported map-level lifecycle state: {state}")
        ids.append(_text(level.get("map_level_status_id")))
    return active, previous, ids, next(iter(level_as_of_values))


def build_snapshot(
    *,
    scopes: Sequence[Mapping[str, Any]],
    maps_by_id: Mapping[int, Mapping[str, Any]],
    levels_by_map_id: Mapping[int, Sequence[Mapping[str, Any]]],
    generation_event_ts_by_id: Mapping[int, Any] | None = None,
    lifecycle_event_ts_by_id: Mapping[int, Any] | None = None,
) -> SnapshotBuild:
    generation_times = generation_event_ts_by_id or {}
    lifecycle_times = lifecycle_event_ts_by_id or {}
    rows: list[dict[str, str]] = []
    seen_symbols: set[str] = set()

    for scope in sorted(scopes, key=lambda item: (_text(item.get("symbol")).upper(), _text(item.get("venue")))):
        row = _blank_row(scope)
        symbol = row["symbol"]
        if not symbol or symbol in seen_symbols:
            raise SnapshotContractError(f"scope symbols must be non-empty and unique: {symbol}")
        seen_symbols.add(symbol)
        availability = {field: MISSING for field in _AUTHORITY_AVAILABILITY_FIELDS}
        availability.update({field: UNAVAILABLE for field in _UNAVAILABLE_LEGACY_FIELDS})
        freshness = _base_freshness(scope)
        row["context_freshness_status"] = freshness

        if row["scope_support_state"] != "SUPPORTED":
            availability.update({field: UNAVAILABLE for field in _AUTHORITY_AVAILABILITY_FIELDS})
            availability.update({field: UNAVAILABLE for field in _UNAVAILABLE_LEGACY_FIELDS})
            row["context_status"] = STATUS_SYMBOL_MISSING
            row["selection_reason"] = _text(scope.get("scope_reason_code")) or "SCOPE_NOT_SUPPORTED"
            row["field_availability_json"] = json.dumps(availability, sort_keys=True, separators=(",", ":"))
            rows.append(row)
            continue

        map_id_value = scope.get("current_map_id")
        if map_id_value is None:
            row["context_status"] = STATUS_STALE_OR_INVALID
            row["context_freshness_status"] = MISSING if freshness == FRESH else freshness
            row["selection_reason"] = row["selection_reason"] or "NO_CURRENT_MAP"
            row["field_availability_json"] = json.dumps(availability, sort_keys=True, separators=(",", ":"))
            rows.append(row)
            continue

        map_id = int(map_id_value)
        map_row = maps_by_id.get(map_id)
        row["native_map_id"] = str(map_id)
        row["map_cycle_id"] = _text(scope.get("current_map_cycle_id"))
        if map_row is None:
            row["context_status"] = STATUS_STALE_OR_INVALID
            row["context_freshness_status"] = MISSING
            row["selection_reason"] = "SELECTED_MAP_GEOMETRY_MISSING"
            row["field_availability_json"] = json.dumps(availability, sort_keys=True, separators=(",", ":"))
            rows.append(row)
            continue

        try:
            for field in (
                "map_id",
                "map_cycle_id",
                "published_at_utc",
                "structure_hash",
                "source_primary_ref",
                "source_support_ref",
                "source_primary_candle_count",
                "source_support_candle_count",
            ):
                if map_row.get(field) is None or _text(map_row.get(field)) == "":
                    raise SnapshotContractError(f"selected map provenance is incomplete: {field}")
            if int(map_row["map_id"]) != map_id:
                raise SnapshotContractError("selected projection/map id mismatch")
            for field in (
                "venue",
                "symbol",
                "quote_currency",
                "fib_trading_horizon",
                "primary_interval",
                "supporting_interval",
            ):
                if field in map_row and _text(map_row.get(field)) != row[field]:
                    raise SnapshotContractError(f"selected projection/map scope mismatch: {field}")
            if _text(map_row.get("map_cycle_id")) != row["map_cycle_id"]:
                raise SnapshotContractError("selected projection/map cycle mismatch")
            geometry = _geometry(map_row)
            projection_as_of = row["projection_as_of_utc"]
            active, previous, level_ids, level_as_of = _target_groups(
                levels_by_map_id.get(map_id, ()),
                map_id=str(map_id),
                map_cycle_id=row["map_cycle_id"],
                projection_as_of_utc=projection_as_of,
                geometry=geometry,
            )
            generation_id = scope.get("latest_generation_event_id")
            lifecycle_id = scope.get("latest_lifecycle_event_id")
            if not scope.get("latest_observation_id") or not scope.get("latest_run_id"):
                raise SnapshotContractError("selected scope observation provenance is missing")
            if not scope.get("latest_observed_at_utc"):
                raise SnapshotContractError("selected scope observation timestamp is missing")
            if not generation_id or int(generation_id) not in generation_times:
                raise SnapshotContractError("selected map generation provenance is missing")
            if not lifecycle_id or int(lifecycle_id) not in lifecycle_times:
                raise SnapshotContractError("selected map lifecycle provenance is missing")
        except SnapshotContractError as exc:
            row["context_status"] = STATUS_STALE_OR_INVALID
            row["context_freshness_status"] = MISSING if freshness == FRESH else freshness
            row["selection_reason"] = str(exc).upper().replace(" ", "_")
            row["field_availability_json"] = json.dumps(availability, sort_keys=True, separators=(",", ":"))
            rows.append(row)
            continue

        row.update(
            {
                "anchor_start_ts_utc": geometry["anchor_start_ts_utc"],
                "anchor_end_ts_utc": geometry["anchor_end_ts_utc"],
                "anchor_low_price": geometry["anchor_low_price"],
                "anchor_high_price": geometry["anchor_high_price"],
                "breakout_gate_price": geometry["breakout_gate"],
                "ext_1_272_price": geometry["ext_1_272"],
                "ext_1_618_price": geometry["ext_1_618"],
                "ext_2_000_price": geometry["ext_2_000"],
                "active_target_levels_json": json.dumps(active, separators=(",", ":")),
                "previous_target_levels_json": json.dumps(previous, separators=(",", ":")),
                "reload_r382_price": geometry["reload_r382"],
                "reload_r500_price": geometry["reload_r500"],
                "reload_r618_price": geometry["reload_r618"],
                "reload_r786_price": geometry["reload_r786"],
                "invalidation_price": geometry["invalidation_price"],
                "source_primary_ref": _text(map_row.get("source_primary_ref")),
                "source_support_ref": _text(map_row.get("source_support_ref")),
                "source_primary_candle_count": _text(map_row.get("source_primary_candle_count")),
                "source_support_candle_count": _text(map_row.get("source_support_candle_count")),
                "previous_map_cycle_id": _text(map_row.get("previous_map_cycle_id")),
                "map_published_at_utc": _iso(map_row.get("published_at_utc")),
                "map_structure_hash": _text(map_row.get("structure_hash")),
                "level_status_ids_json": json.dumps(level_ids, separators=(",", ":")),
                "level_status_as_of_utc": level_as_of,
            }
        )
        for field in (
            "anchor_start_ts_utc",
            "anchor_end_ts_utc",
            "anchor_low_price",
            "anchor_high_price",
            "breakout_gate_price",
            "ext_1_272_price",
            "ext_1_618_price",
            "ext_2_000_price",
            "active_target_levels_json",
            "previous_target_levels_json",
            "reload_r382_price",
            "reload_r500_price",
            "reload_r618_price",
            "reload_r786_price",
            "invalidation_price",
            "native_map_id",
            "map_cycle_id",
        ):
            availability[field] = FRESH
        for field in (
            "primary_4h_lifecycle_state",
            "latest_primary_close_ts_utc",
            "latest_support_close_ts_utc",
            "source_primary_ref",
            "source_support_ref",
            "latest_observation_id",
            "latest_run_id",
            "latest_generation_event_id",
            "latest_lifecycle_event_id",
        ):
            availability[field] = FRESH
        availability["previous_map_cycle_id"] = FRESH if row["previous_map_cycle_id"] else UNAVAILABLE
        generation_id = scope.get("latest_generation_event_id")
        lifecycle_id = scope.get("latest_lifecycle_event_id")
        row["latest_generation_event_ts_utc"] = _iso(generation_times[int(generation_id)])
        row["latest_lifecycle_event_ts_utc"] = _iso(lifecycle_times[int(lifecycle_id)])

        lifecycle = row["primary_4h_lifecycle_state"]
        context_eligible = freshness == FRESH and lifecycle in {"MAP_ACTIVE", "MAP_COMPLETED"}
        row["context_status"] = STATUS_AVAILABLE if context_eligible else STATUS_STALE_OR_INVALID
        row["field_availability_json"] = json.dumps(availability, sort_keys=True, separators=(",", ":"))
        rows.append(row)

    validate_rows(rows)
    semantic_rows = [
        {key: value for key, value in row.items() if key not in _NON_SEMANTIC_ROW_FIELDS}
        for row in rows
    ]
    semantic_payload = {"row_schema_version": ROW_SCHEMA_VERSION, "rows": semantic_rows}
    digest = hashlib.sha256(canonical_json_bytes(semantic_payload)).hexdigest()
    counts = {state.lower(): 0 for state in FRESHNESS_VALUES}
    counts["supported"] = 0
    for row in rows:
        counts[row["context_freshness_status"].lower()] += 1
        if row["scope_support_state"] == "SUPPORTED":
            counts["supported"] += 1
    supported_rows = [row for row in rows if row["scope_support_state"] == "SUPPORTED"]
    overall = max(
        (row["context_freshness_status"] for row in supported_rows),
        key={FRESH: 0, STALE: 1, UNAVAILABLE: 2, MISSING: 3}.get,
        default=UNAVAILABLE,
    )
    timestamp_fields = {
        "projection_as_of_max_utc": _max_timestamp(rows, "projection_as_of_utc"),
        "latest_observed_max_utc": _max_timestamp(rows, "latest_observed_at_utc"),
        "primary_candle_max_utc": _max_timestamp(rows, "latest_primary_close_ts_utc"),
        "supporting_candle_max_utc": _max_timestamp(rows, "latest_support_close_ts_utc"),
        "map_published_max_utc": _max_timestamp(rows, "map_published_at_utc"),
        "level_status_as_of_max_utc": _max_timestamp(rows, "level_status_as_of_utc"),
    }
    return SnapshotBuild(
        rows=tuple(rows),
        content_digest=digest,
        snapshot_id=f"nsctx-v1-{digest[:24]}",
        counts=counts,
        overall_freshness_state=overall,
        source_as_of_timestamps=timestamp_fields,
    )


def _max_timestamp(rows: Sequence[Mapping[str, str]], field: str) -> str:
    values = [row[field] for row in rows if row.get(field)]
    return max(values) if values else ""


def validate_rows(rows: Sequence[Mapping[str, str]]) -> None:
    symbols: list[str] = []
    for row in rows:
        missing = [field for field in CSV_FIELDS if field not in row]
        if missing:
            raise SnapshotContractError(f"row missing schema fields: {missing}")
        freshness = row["context_freshness_status"]
        if freshness not in FRESHNESS_VALUES:
            raise SnapshotContractError(f"invalid freshness status: {freshness}")
        for field in (
            "projection_as_of_utc",
            "projection_rebuilt_at_utc",
            "latest_observed_at_utc",
            "latest_primary_close_ts_utc",
            "latest_support_close_ts_utc",
            "map_published_at_utc",
            "level_status_as_of_utc",
        ):
            if row[field]:
                _iso(row[field])
        symbols.append(row["symbol"])
    if symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
        raise SnapshotContractError("rows must be uniquely sorted by symbol")


def render_rows_csv(rows: Sequence[Mapping[str, str]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def build_envelope(
    build: SnapshotBuild,
    *,
    generated_ts_utc: datetime,
    publication_ts_utc: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "row_schema_version": ROW_SCHEMA_VERSION,
        "snapshot_id": build.snapshot_id,
        "content_digest": f"sha256:{build.content_digest}",
        "generated_ts_utc": _iso(generated_ts_utc),
        "publication_ts_utc": _iso(publication_ts_utc),
        "source_as_of_timestamps": build.source_as_of_timestamps,
        "row_count": len(build.rows),
        "counts": build.counts,
        "overall_freshness_state": build.overall_freshness_state,
        "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
        "safety": SAFETY_MARKERS,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise SnapshotContractError(f"immutable snapshot collision: {path}")
        return
    atomic_write_bytes(path, payload)


@contextmanager
def publication_lock(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / PUBLICATION_LOCK_NAME
    handle = lock_path.open("a+b")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SnapshotContractError("native SHORT snapshot publisher lock is already held") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def resolve_manifest_artifact_paths(
    output_dir: Path,
    manifest: Mapping[str, Any],
) -> tuple[Path, Path]:
    snapshot_id = _text(manifest.get("snapshot_id"))
    if not snapshot_id.startswith("nsctx-v1-") or "/" in snapshot_id or "\\" in snapshot_id:
        raise SnapshotContractError("manifest snapshot_id is invalid")
    expected_rows = Path("snapshots") / snapshot_id / ROWS_NAME
    expected_bundle = Path("snapshots") / snapshot_id / BUNDLE_NAME
    resolved_paths: list[Path] = []
    for field, expected in (("rows_csv", expected_rows), ("snapshot_bundle", expected_bundle)):
        raw = _text(manifest.get(field))
        candidate = Path(raw)
        if not raw or candidate.is_absolute() or ".." in candidate.parts:
            raise SnapshotContractError(f"manifest {field} must be a safe relative path")
        if candidate != expected:
            raise SnapshotContractError(f"manifest {field} does not match snapshot identity")
        resolved = (output_dir / candidate).resolve()
        if not resolved.is_relative_to(output_dir.resolve()):
            raise SnapshotContractError(f"manifest {field} escapes output directory")
        resolved_paths.append(resolved)
    return resolved_paths[0], resolved_paths[1]


def publish_snapshot(
    build: SnapshotBuild,
    *,
    output_dir: Path,
    generated_ts_utc: datetime,
    publication_ts_utc: datetime,
) -> PublicationResult:
    with publication_lock(output_dir):
        return _publish_snapshot_locked(
            build,
            output_dir=output_dir,
            generated_ts_utc=generated_ts_utc,
            publication_ts_utc=publication_ts_utc,
        )


def _publish_snapshot_locked(
    build: SnapshotBuild,
    *,
    output_dir: Path,
    generated_ts_utc: datetime,
    publication_ts_utc: datetime,
) -> PublicationResult:
    manifest_path = output_dir / MANIFEST_NAME
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotContractError("current snapshot manifest is unreadable") from exc
        if current.get("content_digest") == f"sha256:{build.content_digest}":
            if current.get("schema_version") != SCHEMA_VERSION:
                raise SnapshotContractError("current manifest schema version mismatch")
            if current.get("snapshot_id") != build.snapshot_id:
                raise SnapshotContractError("current manifest snapshot identity mismatch")
            rows_path, bundle_path = resolve_manifest_artifact_paths(output_dir, current)
            if not rows_path.is_file() or not bundle_path.is_file():
                raise SnapshotContractError("current manifest references missing immutable files")
            rows_payload = rows_path.read_bytes()
            rows_digest = f"sha256:{hashlib.sha256(rows_payload).hexdigest()}"
            if rows_digest != current.get("rows_csv_digest"):
                raise SnapshotContractError("current manifest rows digest mismatch")
            if rows_payload != render_rows_csv(build.rows):
                raise SnapshotContractError("current immutable rows do not match semantic snapshot")
            try:
                bundle_payload = bundle_path.read_bytes()
                bundle = json.loads(bundle_payload)
            except (OSError, json.JSONDecodeError) as exc:
                raise SnapshotContractError("current snapshot bundle is unreadable") from exc
            bundle_digest = f"sha256:{hashlib.sha256(bundle_payload).hexdigest()}"
            if bundle_digest != current.get("snapshot_bundle_digest"):
                raise SnapshotContractError("current manifest bundle digest mismatch")
            envelope = bundle.get("envelope", {})
            if envelope.get("snapshot_id") != build.snapshot_id:
                raise SnapshotContractError("current manifest/bundle snapshot identity mismatch")
            if envelope.get("content_digest") != f"sha256:{build.content_digest}":
                raise SnapshotContractError("current manifest/bundle content digest mismatch")
            if (
                envelope.get("schema_version") != SCHEMA_VERSION
                or envelope.get("row_schema_version") != ROW_SCHEMA_VERSION
            ):
                raise SnapshotContractError("current manifest/bundle schema version mismatch")
            if envelope.get("row_count") != len(build.rows) or bundle.get("rows") != list(build.rows):
                raise SnapshotContractError("current bundle does not match semantic snapshot")
            return PublicationResult(
                "UNCHANGED",
                build.snapshot_id,
                build.content_digest,
                manifest_path,
                rows_path,
                bundle_path,
            )

    envelope = build_envelope(
        build,
        generated_ts_utc=generated_ts_utc,
        publication_ts_utc=publication_ts_utc,
    )
    relative_dir = Path("snapshots") / build.snapshot_id
    snapshot_dir = output_dir / relative_dir
    rows_path = snapshot_dir / ROWS_NAME
    bundle_path = snapshot_dir / BUNDLE_NAME
    rows_payload = render_rows_csv(build.rows)
    rows_digest = hashlib.sha256(rows_payload).hexdigest()
    bundle_payload = canonical_json_bytes({"envelope": envelope, "rows": build.rows})
    bundle_digest = hashlib.sha256(bundle_payload).hexdigest()

    _write_immutable(rows_path, rows_payload)
    _write_immutable(bundle_path, bundle_payload)
    _fsync_directory(snapshot_dir)
    _fsync_directory(snapshot_dir.parent)
    if hashlib.sha256(rows_path.read_bytes()).hexdigest() != rows_digest:
        raise SnapshotContractError("published immutable rows digest mismatch")
    if bundle_path.read_bytes() != bundle_payload:
        raise SnapshotContractError("published immutable bundle digest mismatch")
    manifest = {
        **envelope,
        "rows_csv": str(relative_dir / ROWS_NAME),
        "rows_csv_digest": f"sha256:{rows_digest}",
        "snapshot_bundle": str(relative_dir / BUNDLE_NAME),
        "snapshot_bundle_digest": f"sha256:{bundle_digest}",
        "publication_result": "PUBLISHED",
    }
    atomic_write_bytes(manifest_path, canonical_json_bytes(manifest))
    return PublicationResult(
        "PUBLISHED",
        build.snapshot_id,
        build.content_digest,
        manifest_path,
        rows_path,
        bundle_path,
    )


def _fetch_all(conn: Any, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(params))
        return list(cursor.fetchall())


def load_persisted_authorities(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    fib_trading_horizon: str,
    primary_interval: str,
    supporting_interval: str,
) -> tuple[
    list[dict[str, Any]],
    dict[int, dict[str, Any]],
    dict[int, list[dict[str, Any]]],
    dict[int, Any],
    dict[int, Any],
]:
    key_params = (venue, quote_currency, fib_trading_horizon, primary_interval, supporting_interval)
    scopes = _fetch_all(
        conn,
        """
        SELECT s.scope_id, s.venue, s.symbol, s.quote_currency, s.fib_trading_horizon,
               s.primary_interval, s.supporting_interval, s.scope_support_state,
               s.scope_reason_code, s.scope_reason_detail,
               st.scope_status_id, st.scope_status_code, st.scope_status_reason_code,
               st.map_lifecycle_state, st.observation_freshness_state,
               st.source_freshness_state, st.actionability_state,
               st.current_map_id, st.current_map_cycle_id,
               st.latest_generation_event_id, st.latest_lifecycle_event_id,
               st.latest_observation_id, st.latest_run_id, st.latest_observed_at_utc,
               st.primary_latest_candle_ts_utc, st.supporting_latest_candle_ts_utc,
               st.projection_as_of_utc, st.rebuilt_at_utc
        FROM native_short_map_scope_v1 s
        LEFT JOIN native_short_scope_status_v1 st
          ON st.venue=s.venue AND st.symbol=s.symbol AND st.quote_currency=s.quote_currency
         AND st.fib_trading_horizon=s.fib_trading_horizon
         AND st.primary_interval=s.primary_interval AND st.supporting_interval=s.supporting_interval
        WHERE s.venue=%s AND s.quote_currency=%s AND s.fib_trading_horizon=%s
          AND s.primary_interval=%s AND s.supporting_interval=%s
        ORDER BY s.symbol, s.scope_id
        """,
        key_params,
    )
    maps = _fetch_all(
        conn,
        """
        SELECT m.map_id, m.venue, m.symbol, m.quote_currency, m.fib_trading_horizon,
               m.primary_interval, m.supporting_interval, m.map_cycle_id,
               m.previous_map_id, m.previous_map_cycle_id, m.published_at_utc,
               m.structure_hash, m.anchor_low_ts_utc, m.anchor_low_price,
               m.anchor_high_ts_utc, m.anchor_high_price, m.fib_ratios_json,
               m.invalidation_price, m.source_primary_ref, m.source_support_ref,
               m.source_primary_candle_count, m.source_support_candle_count
        FROM native_short_scope_status_v1 st
        JOIN native_short_map_v1 m
          ON m.map_id=st.current_map_id AND m.venue=st.venue AND m.symbol=st.symbol
         AND m.quote_currency=st.quote_currency AND m.fib_trading_horizon=st.fib_trading_horizon
         AND m.primary_interval=st.primary_interval AND m.supporting_interval=st.supporting_interval
        WHERE st.venue=%s AND st.quote_currency=%s AND st.fib_trading_horizon=%s
          AND st.primary_interval=%s AND st.supporting_interval=%s
        ORDER BY m.map_id
        """,
        key_params,
    )
    levels = _fetch_all(
        conn,
        """
        SELECT l.map_level_status_id, l.current_map_id, l.map_cycle_id,
               l.canonical_map_level_role, l.side, l.canonical_unrounded_price,
               l.level_lifecycle_state, l.level_status_as_of_utc,
               l.projection_scope_status_code, l.projection_map_lifecycle_state,
               l.projection_actionability_state
        FROM native_short_scope_status_v1 st
        JOIN native_short_map_level_status_v1 l
          ON l.current_map_id=st.current_map_id AND l.venue=st.venue AND l.symbol=st.symbol
         AND l.quote_currency=st.quote_currency AND l.fib_trading_horizon=st.fib_trading_horizon
         AND l.primary_interval=st.primary_interval AND l.supporting_interval=st.supporting_interval
        WHERE st.venue=%s AND st.quote_currency=%s AND st.fib_trading_horizon=%s
          AND st.primary_interval=%s AND st.supporting_interval=%s
        ORDER BY l.current_map_id, l.canonical_map_level_role, l.map_level_status_id
        """,
        key_params,
    )
    generation_events = _fetch_all(
        conn,
        """
        SELECT e.generation_event_id, e.event_ts_utc
        FROM native_short_scope_status_v1 st
        JOIN native_short_map_generation_event_v1 e
          ON e.generation_event_id=st.latest_generation_event_id
        WHERE st.venue=%s AND st.quote_currency=%s AND st.fib_trading_horizon=%s
          AND st.primary_interval=%s AND st.supporting_interval=%s
        """,
        key_params,
    )
    lifecycle_events = _fetch_all(
        conn,
        """
        SELECT e.lifecycle_event_id, e.event_ts_utc
        FROM native_short_scope_status_v1 st
        JOIN native_short_map_lifecycle_event_v1 e
          ON e.lifecycle_event_id=st.latest_lifecycle_event_id AND e.map_id=st.current_map_id
        WHERE st.venue=%s AND st.quote_currency=%s AND st.fib_trading_horizon=%s
          AND st.primary_interval=%s AND st.supporting_interval=%s
        """,
        key_params,
    )
    for row in scopes:
        for field in (
            "latest_observed_at_utc",
            "primary_latest_candle_ts_utc",
            "supporting_latest_candle_ts_utc",
            "projection_as_of_utc",
            "rebuilt_at_utc",
        ):
            row[field] = persisted_db_datetime_utc(
                row.get(field),
                table="native_short_scope_status_v1",
                field=field,
            )
    for row in maps:
        for field in ("published_at_utc", "anchor_low_ts_utc", "anchor_high_ts_utc"):
            row[field] = persisted_db_datetime_utc(
                row.get(field),
                table="native_short_map_v1",
                field=field,
            )
    for row in levels:
        row["level_status_as_of_utc"] = persisted_db_datetime_utc(
            row.get("level_status_as_of_utc"),
            table="native_short_map_level_status_v1",
            field="level_status_as_of_utc",
        )
    for row in generation_events:
        row["event_ts_utc"] = persisted_db_datetime_utc(
            row.get("event_ts_utc"),
            table="native_short_map_generation_event_v1",
            field="event_ts_utc",
        )
    for row in lifecycle_events:
        row["event_ts_utc"] = persisted_db_datetime_utc(
            row.get("event_ts_utc"),
            table="native_short_map_lifecycle_event_v1",
            field="event_ts_utc",
        )
    maps_by_id = {int(row["map_id"]): row for row in maps}
    levels_by_map_id: dict[int, list[dict[str, Any]]] = {}
    for row in levels:
        levels_by_map_id.setdefault(int(row["current_map_id"]), []).append(row)
    return (
        scopes,
        maps_by_id,
        levels_by_map_id,
        {int(row["generation_event_id"]): row["event_ts_utc"] for row in generation_events},
        {int(row["lifecycle_event_id"]): row["event_ts_utc"] for row in lifecycle_events},
    )
