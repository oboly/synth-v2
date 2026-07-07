from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


SCHEMA_VERSION = "1.0"
PREVIEW_KIND = "MARKET_OBSERVER_EVIDENCE_PREVIEW"
SOURCE_KIND = "ACTIVE_REGIME_OBSERVATION"
REGIME_FRESHNESS_UNKNOWN = "UNKNOWN"

_SELECT_LATEST_ACTIVE_REGIME_OBSERVATION_SQL = """
    SELECT
        active_regime_observation_id,
        venue,
        interval_code,
        asof_ts_utc,
        asset_class,
        global_regime,
        global_regime_version,
        asset_class_regime,
        asset_class_regime_version,
        global_class_regime,
        validation_status,
        validated_hypothesis_tags_json,
        source_candle_ts_utc
    FROM active_regime_observation
    WHERE venue = %s
      AND interval_code = %s
      AND asset_class = %s
      AND asof_ts_utc = (
          SELECT MAX(asof_ts_utc)
          FROM active_regime_observation
          WHERE venue = %s
            AND interval_code = %s
            AND asset_class = %s
            AND asof_ts_utc <= %s
      )
"""


class MarketObserverEvidencePreviewError(RuntimeError):
    pass


class MarketObserverEvidencePreviewTimestampError(MarketObserverEvidencePreviewError):
    pass


class MarketObserverEvidencePreviewNoSourceError(MarketObserverEvidencePreviewError):
    pass


class MarketObserverEvidencePreviewAmbiguityError(MarketObserverEvidencePreviewError):
    pass


class MarketObserverEvidencePreviewMalformedTagsError(MarketObserverEvidencePreviewError):
    pass


@dataclass(frozen=True)
class ActiveRegimeObservationLocator:
    source_kind: Literal["ACTIVE_REGIME_OBSERVATION"] = field(default=SOURCE_KIND, init=False)
    active_regime_observation_id: int
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    asset_class: str
    global_regime_version: str
    asset_class_regime_version: str
    source_candle_ts_utc: datetime | None


@dataclass(frozen=True)
class MarketObserverEvidencePreview:
    schema_version: str
    preview_kind: Literal["MARKET_OBSERVER_EVIDENCE_PREVIEW"] = field(default=PREVIEW_KIND, init=False)
    research_only: bool = field(default=True, init=False)
    partial: bool = field(default=True, init=False)
    requested_event_ts_utc: datetime
    canonical_global_regime: str
    global_regime_version: str
    canonical_asset_class: str
    canonical_asset_class_regime: str
    asset_class_regime_version: str
    canonical_global_class_regime: str
    validation_status: str
    validated_hypothesis_tags: tuple[str, ...]
    regime_freshness: Literal["UNKNOWN"] = field(default=REGIME_FRESHNESS_UNKNOWN, init=False)
    source_locator: ActiveRegimeObservationLocator
    warnings: tuple[str, ...]


def build_market_observer_evidence_preview(
    conn: Any,
    venue: str,
    interval_code: str,
    asset_class: str,
    event_ts_utc: datetime,
) -> MarketObserverEvidencePreview:
    requested_event_ts_utc = _require_utc_aware_datetime(
        value=event_ts_utc,
        field_name="event_ts_utc",
    )
    query_event_ts_utc = requested_event_ts_utc.replace(tzinfo=None)

    with conn.cursor() as cur:
        cur.execute(
            _SELECT_LATEST_ACTIVE_REGIME_OBSERVATION_SQL,
            (
                venue,
                interval_code,
                asset_class,
                venue,
                interval_code,
                asset_class,
                query_event_ts_utc,
            ),
        )
        rows = cur.fetchall()

    if not rows:
        raise MarketObserverEvidencePreviewNoSourceError(
            "No active_regime_observation row found at-or-before the requested event timestamp."
        )
    if len(rows) != 1:
        selected_asof = rows[0].get("asof_ts_utc")
        raise MarketObserverEvidencePreviewAmbiguityError(
            "Multiple active_regime_observation rows matched the selected latest asof_ts_utc: "
            f"venue={venue} interval_code={interval_code} asset_class={asset_class} "
            f"asof_ts_utc={selected_asof!r} row_count={len(rows)}"
        )

    row = rows[0]
    tags = _decode_validated_hypothesis_tags(row.get("validated_hypothesis_tags_json"))

    locator = ActiveRegimeObservationLocator(
        active_regime_observation_id=_require_int(row, "active_regime_observation_id"),
        venue=_require_str(row, "venue"),
        interval_code=_require_str(row, "interval_code"),
        asof_ts_utc=_require_datetime(row, "asof_ts_utc"),
        asset_class=_require_str(row, "asset_class"),
        global_regime_version=_require_str(row, "global_regime_version"),
        asset_class_regime_version=_require_str(row, "asset_class_regime_version"),
        source_candle_ts_utc=_require_optional_datetime(row, "source_candle_ts_utc"),
    )

    return MarketObserverEvidencePreview(
        schema_version=SCHEMA_VERSION,
        requested_event_ts_utc=requested_event_ts_utc,
        canonical_global_regime=_require_str(row, "global_regime"),
        global_regime_version=locator.global_regime_version,
        canonical_asset_class=locator.asset_class,
        canonical_asset_class_regime=_require_str(row, "asset_class_regime"),
        asset_class_regime_version=locator.asset_class_regime_version,
        canonical_global_class_regime=_require_str(row, "global_class_regime"),
        validation_status=_require_str(row, "validation_status"),
        validated_hypothesis_tags=tags,
        source_locator=locator,
        warnings=(),
    )


def _require_utc_aware_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise MarketObserverEvidencePreviewTimestampError(
            f"{field_name} must be a datetime, got {type(value).__name__}."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketObserverEvidencePreviewTimestampError(
            f"{field_name} must be timezone-aware and UTC-compatible."
        )
    return value.astimezone(UTC)


def _require_datetime(row: dict[str, Any], field_name: str) -> datetime:
    value = row.get(field_name)
    if not isinstance(value, datetime):
        raise MarketObserverEvidencePreviewError(
            f"{field_name} must be a datetime in active_regime_observation."
        )
    return _normalize_db_utc_datetime(value=value, field_name=field_name)


def _require_optional_datetime(row: dict[str, Any], field_name: str) -> datetime | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise MarketObserverEvidencePreviewError(
            f"{field_name} must be a datetime or null in active_regime_observation."
        )
    return _normalize_db_utc_datetime(value=value, field_name=field_name)


def _normalize_db_utc_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    try:
        return value.astimezone(UTC)
    except ValueError as exc:
        raise MarketObserverEvidencePreviewError(
            f"{field_name} must be a UTC-compatible datetime in active_regime_observation."
        ) from exc


def _require_int(row: dict[str, Any], field_name: str) -> int:
    value = row.get(field_name)
    if not isinstance(value, int):
        raise MarketObserverEvidencePreviewError(
            f"{field_name} must be an int in active_regime_observation."
        )
    return value


def _require_str(row: dict[str, Any], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str):
        raise MarketObserverEvidencePreviewError(
            f"{field_name} must be a str in active_regime_observation."
        )
    return value


def _decode_validated_hypothesis_tags(raw_value: Any) -> tuple[str, ...]:
    if raw_value is None:
        raise MarketObserverEvidencePreviewMalformedTagsError(
            "validated_hypothesis_tags_json is null."
        )
    if not isinstance(raw_value, str):
        raise MarketObserverEvidencePreviewMalformedTagsError(
            "validated_hypothesis_tags_json must be a JSON string."
        )
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise MarketObserverEvidencePreviewMalformedTagsError(
            f"validated_hypothesis_tags_json is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(decoded, list):
        raise MarketObserverEvidencePreviewMalformedTagsError(
            "validated_hypothesis_tags_json must decode to a JSON array."
        )
    if any(not isinstance(tag, str) for tag in decoded):
        raise MarketObserverEvidencePreviewMalformedTagsError(
            "validated_hypothesis_tags_json must contain only strings."
        )
    return tuple(decoded)
