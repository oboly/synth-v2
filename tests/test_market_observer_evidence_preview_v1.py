from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.research.market_observer_evidence_preview_v1 import (
    MarketObserverEvidencePreviewAmbiguityError,
    MarketObserverEvidencePreviewMalformedTagsError,
    MarketObserverEvidencePreviewNoSourceError,
    MarketObserverEvidencePreviewTimestampError,
    build_market_observer_evidence_preview,
)


MODULE_PATH = Path("src/research/market_observer_evidence_preview_v1.py")


def _row(
    *,
    active_regime_observation_id: int = 101,
    venue: str = "bitvavo",
    interval_code: str = "4h",
    asof_ts_utc: datetime = datetime(2026, 5, 14, 12, 0, 0),
    source_candle_ts_utc: datetime | None = datetime(2026, 5, 14, 8, 0, 0),
    asset_class: str = "ETH",
    global_regime: str = "GLOBAL_ROTATION_WINDOW",
    global_regime_version: str = "1.1",
    asset_class_regime: str = "CLASS_LEADERSHIP",
    asset_class_regime_version: str = "1.1",
    global_class_regime: str = "GLOBAL_ROTATION_WINDOW|CLASS_LEADERSHIP",
    validation_status: str = "H1_CONTEXT_VALIDATED",
    validated_hypothesis_tags_json: str = '["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]',
) -> dict[str, Any]:
    return {
        "active_regime_observation_id": active_regime_observation_id,
        "venue": venue,
        "interval_code": interval_code,
        "asof_ts_utc": asof_ts_utc,
        "source_candle_ts_utc": source_candle_ts_utc,
        "asset_class": asset_class,
        "global_regime": global_regime,
        "global_regime_version": global_regime_version,
        "asset_class_regime": asset_class_regime,
        "asset_class_regime_version": asset_class_regime_version,
        "global_class_regime": global_class_regime,
        "validation_status": validation_status,
        "validated_hypothesis_tags_json": validated_hypothesis_tags_json,
    }


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self._conn = conn
        self._rows: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        assert params is not None
        self._conn.calls.append((sql, params))

        venue, interval_code, asset_class, venue2, interval_code2, asset_class2, event_ts_utc = params
        assert venue == venue2
        assert interval_code == interval_code2
        assert asset_class == asset_class2

        matching = [
            row
            for row in self._conn.rows
            if row["venue"] == venue
            and row["interval_code"] == interval_code
            and row["asset_class"] == asset_class
            and row["asof_ts_utc"] <= event_ts_utc
        ]
        if not matching:
            self._rows = []
            return

        latest_asof_ts_utc = max(row["asof_ts_utc"] for row in matching)
        self._rows = [
            dict(row)
            for row in matching
            if row["asof_ts_utc"] == latest_asof_ts_utc
        ]

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Any]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def test_forwards_exact_values_and_locator_identity() -> None:
    source_row = _row()
    conn = _FakeConnection([source_row])
    event_ts_utc = datetime(2026, 5, 14, 14, 30, tzinfo=timezone(timedelta(hours=2)))

    preview = build_market_observer_evidence_preview(
        conn=conn,
        venue="bitvavo",
        interval_code="4h",
        asset_class="ETH",
        event_ts_utc=event_ts_utc,
    )

    assert preview.schema_version == "1.0"
    assert preview.preview_kind == "MARKET_OBSERVER_EVIDENCE_PREVIEW"
    assert preview.research_only is True
    assert preview.partial is True
    assert preview.requested_event_ts_utc == datetime(2026, 5, 14, 12, 30, tzinfo=UTC)
    assert preview.requested_event_ts_utc.tzinfo == UTC
    assert preview.canonical_global_regime == source_row["global_regime"]
    assert preview.global_regime_version == source_row["global_regime_version"]
    assert preview.canonical_asset_class == source_row["asset_class"]
    assert preview.canonical_asset_class_regime == source_row["asset_class_regime"]
    assert preview.asset_class_regime_version == source_row["asset_class_regime_version"]
    assert preview.canonical_global_class_regime == source_row["global_class_regime"]
    assert preview.validation_status == source_row["validation_status"]
    assert preview.validated_hypothesis_tags == ("H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT",)
    assert preview.regime_freshness == "UNKNOWN"
    assert preview.warnings == ()

    locator = preview.source_locator
    assert locator.source_kind == "ACTIVE_REGIME_OBSERVATION"
    assert locator.active_regime_observation_id == source_row["active_regime_observation_id"]
    assert locator.venue == source_row["venue"]
    assert locator.interval_code == source_row["interval_code"]
    assert locator.asof_ts_utc == source_row["asof_ts_utc"].replace(tzinfo=UTC)
    assert locator.asof_ts_utc.tzinfo == UTC
    assert locator.asset_class == source_row["asset_class"]
    assert locator.global_regime_version == source_row["global_regime_version"]
    assert locator.asset_class_regime_version == source_row["asset_class_regime_version"]
    assert locator.source_candle_ts_utc == source_row["source_candle_ts_utc"].replace(tzinfo=UTC)
    assert locator.source_candle_ts_utc is not None
    assert locator.source_candle_ts_utc.tzinfo == UTC

    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert sql.lstrip().startswith("SELECT")
    assert "%s" in sql
    assert params[-1] == datetime(2026, 5, 14, 12, 30, 0)


def test_latest_at_or_before_event_timestamp_is_selected() -> None:
    older_row = _row(
        active_regime_observation_id=201,
        asof_ts_utc=datetime(2026, 5, 14, 8, 0, 0),
        global_regime="GLOBAL_NEUTRAL",
    )
    latest_row = _row(
        active_regime_observation_id=202,
        asof_ts_utc=datetime(2026, 5, 14, 12, 0, 0),
        global_regime="GLOBAL_RISK_ON",
    )
    future_row = _row(
        active_regime_observation_id=203,
        asof_ts_utc=datetime(2026, 5, 14, 16, 0, 0),
        global_regime="GLOBAL_BTC_OVERHEATED",
    )
    conn = _FakeConnection([future_row, latest_row, older_row])

    preview = build_market_observer_evidence_preview(
        conn=conn,
        venue="bitvavo",
        interval_code="4h",
        asset_class="ETH",
        event_ts_utc=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
    )

    assert preview.source_locator.active_regime_observation_id == 202
    assert preview.canonical_global_regime == "GLOBAL_RISK_ON"


def test_null_source_candle_timestamp_remains_none() -> None:
    conn = _FakeConnection([_row(source_candle_ts_utc=None)])

    preview = build_market_observer_evidence_preview(
        conn=conn,
        venue="bitvavo",
        interval_code="4h",
        asset_class="ETH",
        event_ts_utc=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
    )

    assert preview.source_locator.source_candle_ts_utc is None


def test_no_row_fails_closed() -> None:
    conn = _FakeConnection([])

    with pytest.raises(MarketObserverEvidencePreviewNoSourceError):
        build_market_observer_evidence_preview(
            conn=conn,
            venue="bitvavo",
            interval_code="4h",
            asset_class="ETH",
            event_ts_utc=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
        )


def test_ambiguity_at_selected_latest_asof_fails_closed() -> None:
    asof_ts_utc = datetime(2026, 5, 14, 12, 0, 0)
    conn = _FakeConnection(
        [
            _row(
                active_regime_observation_id=301,
                asof_ts_utc=asof_ts_utc,
                global_regime_version="1.0",
            ),
            _row(
                active_regime_observation_id=302,
                asof_ts_utc=asof_ts_utc,
                global_regime_version="1.1",
            ),
        ]
    )

    with pytest.raises(MarketObserverEvidencePreviewAmbiguityError):
        build_market_observer_evidence_preview(
            conn=conn,
            venue="bitvavo",
            interval_code="4h",
            asset_class="ETH",
            event_ts_utc=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
        )


def test_malformed_tags_fail_closed() -> None:
    conn = _FakeConnection(
        [
            _row(validated_hypothesis_tags_json='{"not":"a-list"}'),
        ]
    )

    with pytest.raises(MarketObserverEvidencePreviewMalformedTagsError):
        build_market_observer_evidence_preview(
            conn=conn,
            venue="bitvavo",
            interval_code="4h",
            asset_class="ETH",
            event_ts_utc=datetime(2026, 5, 14, 12, 30, tzinfo=UTC),
        )


def test_naive_event_timestamp_is_rejected() -> None:
    conn = _FakeConnection([_row()])

    with pytest.raises(MarketObserverEvidencePreviewTimestampError):
        build_market_observer_evidence_preview(
            conn=conn,
            venue="bitvavo",
            interval_code="4h",
            asset_class="ETH",
            event_ts_utc=datetime(2026, 5, 14, 12, 30),
        )


def test_boundary_scan_blocks_forbidden_references_and_write_sql() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    upper_source = source.upper()

    forbidden_references = (
        "MarketObserverSnapshot",
        "MarketNavigationState",
        "selection_engine",
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "dashboard",
        "account",
        "portfolio",
        "order",
        "FFG",
        "narrative",
        "fib map",
        "btc structure",
        "sector",
    )
    for forbidden in forbidden_references:
        assert forbidden not in source

    forbidden_write_sql = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "REPLACE ",
        "CREATE TABLE",
        "ALTER TABLE",
        "DROP TABLE",
        "TRUNCATE ",
    )
    for forbidden in forbidden_write_sql:
        assert forbidden not in upper_source
