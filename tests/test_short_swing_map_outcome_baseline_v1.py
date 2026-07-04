from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.research import run_short_swing_map_outcome_baseline_v1 as baseline


MODULE_PATH = Path("src/research/run_short_swing_map_outcome_baseline_v1.py")
T0 = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _ts(hours: int) -> datetime:
    return T0 + timedelta(hours=hours)


def _map(
    map_id: int,
    *,
    symbol: str = "WLD",
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    attempt_id: str | None = None,
    cycle_id: str | None = None,
    targets: str = '["130","140"]',
    payload: str = '{"reload_r382_price":"118","reload_r500_price":"115","reload_r618_price":"112","reload_r786_price":"108"}',
    invalidation: Decimal | None = Decimal("98"),
    previous_map_id: int | None = None,
) -> baseline.NativeMapHistoryRow:
    return baseline.NativeMapHistoryRow(
        map_id=map_id,
        venue="bitvavo",
        symbol=symbol,
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        published_at_utc=published_at or _ts(0),
        created_at_utc=created_at or _ts(0),
        structure_hash=f"hash-{map_id}",
        published_generation_attempt_id=attempt_id or f"attempt-{map_id}",
        map_cycle_id=cycle_id or f"cycle-{map_id}",
        previous_map_id=previous_map_id,
        previous_map_cycle_id=None if previous_map_id is None else f"cycle-{previous_map_id}",
        anchor_low_ts_utc=_ts(-8),
        anchor_low_price=Decimal("100"),
        anchor_high_ts_utc=_ts(-4),
        anchor_high_price=Decimal("125"),
        target_levels_json=targets,
        invalidation_price=invalidation,
        invalidation_rule="BREAK_ANCHOR_LOW",
        map_payload_json=payload,
    )


def _published_event(
    map_id: int,
    *,
    event_id: int | None = None,
    symbol: str = "WLD",
    event_ts: datetime | None = None,
    created_at: datetime | None = None,
    attempt_id: str | None = None,
) -> baseline.GenerationHistoryEvent:
    return baseline.GenerationHistoryEvent(
        generation_event_id=event_id or map_id,
        venue="bitvavo",
        symbol=symbol,
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        generation_attempt_id=attempt_id or f"attempt-{map_id}",
        event_type="PUBLISHED",
        event_ts_utc=event_ts or _ts(0),
        created_at_utc=created_at or _ts(0),
        map_id=map_id,
        reason_code=None,
    )


def _lifecycle_event(
    event_id: int,
    map_id: int,
    event_type: str,
    *,
    event_ts: datetime,
    created_at: datetime,
    successor_map_id: int | None = None,
) -> baseline.LifecycleHistoryEvent:
    return baseline.LifecycleHistoryEvent(
        lifecycle_event_id=event_id,
        map_id=map_id,
        lifecycle_event_type=event_type,
        event_ts_utc=event_ts,
        created_at_utc=created_at,
        successor_map_id=successor_map_id,
        reason_code=None,
    )


def _candle(hours: int, high: str, low: str, close: str = "120") -> baseline.OutcomeCandle:
    return baseline.OutcomeCandle(
        symbol="WLD",
        close_ts_utc=_ts(hours),
        open_price=Decimal("120"),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def test_source_table_inventory_identifies_append_only_history_tables() -> None:
    used = {
        item["table"]: item
        for item in baseline.SOURCE_TABLE_INVENTORY
        if item["used_for_historical_reconstruction"]
    }
    assert set(used) == {
        "native_short_map_v1",
        "native_short_map_generation_event_v1",
        "native_short_map_lifecycle_event_v1",
    }
    assert used["native_short_map_v1"]["primary_key"] == ("map_id",)
    assert used["native_short_map_generation_event_v1"]["primary_key"] == ("generation_event_id",)
    assert used["native_short_map_lifecycle_event_v1"]["primary_key"] == ("lifecycle_event_id",)
    assert "created_at_utc" in baseline.KNOWN_BY_T_RULE
    assert "effective/event timestamp is <= T" in baseline.KNOWN_BY_T_RULE


def test_post_t_revision_does_not_alter_as_of_t_map_choice() -> None:
    as_of = _ts(1)
    map_one = _map(1, published_at=_ts(0), created_at=_ts(0))
    # This row looks older by effective time, but was only recorded after T.
    post_t_map = _map(2, published_at=_ts(0), created_at=_ts(2), previous_map_id=1)
    post_t_supersede = _lifecycle_event(
        10,
        1,
        "SUPERSEDED",
        event_ts=_ts(0),
        created_at=_ts(2),
        successor_map_id=2,
    )

    choice = baseline.choose_native_map_as_of(
        symbol="WLD",
        venue="bitvavo",
        quote_currency="EUR",
        as_of_ts_utc=as_of,
        maps=[map_one, post_t_map],
        generation_events=[
            _published_event(1, event_ts=_ts(0), created_at=_ts(0)),
            _published_event(2, event_id=2, event_ts=_ts(0), created_at=_ts(2)),
        ],
        lifecycle_events=[post_t_supersede],
    )

    assert choice.status == baseline.STATUS_OK
    assert choice.map_row is not None
    assert choice.map_row.map_id == 1


def test_map_missing_published_generation_event_is_history_incomplete() -> None:
    choice = baseline.choose_native_map_as_of(
        symbol="WLD",
        venue="bitvavo",
        quote_currency="EUR",
        as_of_ts_utc=_ts(1),
        maps=[_map(1)],
        generation_events=[],
        lifecycle_events=[],
    )

    assert choice.status == baseline.STATUS_HISTORY_INCOMPLETE
    assert choice.reason_code == "PUBLISHED_GENERATION_EVENT_MISSING_BY_T"


def test_post_t_published_generation_event_does_not_create_sample_point() -> None:
    events = [
        _published_event(1, event_id=1, event_ts=_ts(1), created_at=_ts(1)),
        _published_event(2, event_id=2, event_ts=_ts(2), created_at=_ts(3)),
    ]

    samples = baseline.build_sample_points_from_generation_events(
        generation_events=events,
        venue="bitvavo",
        quote_currency="EUR",
        symbols=["WLD"],
        start_ts=_ts(0),
        end_ts=_ts(4),
        max_samples=0,
    )

    assert samples == [("WLD", _ts(1))]


def test_default_symbol_discovery_excludes_future_only_symbols() -> None:
    events = [
        _published_event(1, symbol="AAA", event_id=1, event_ts=_ts(1), created_at=_ts(1)),
        _published_event(2, symbol="ZZZ", event_id=2, event_ts=_ts(6), created_at=_ts(6)),
        _published_event(3, symbol="BBB", event_id=3, event_ts=_ts(2), created_at=_ts(5)),
    ]

    symbols = baseline.discover_default_symbols_from_generation_events(
        generation_events=events,
        venue="bitvavo",
        quote_currency="EUR",
        start_ts=_ts(0),
        end_ts=_ts(4),
        max_symbols=1,
    )

    assert symbols == ["AAA"]


def test_missing_reload_payload_emits_history_incomplete_without_fallback() -> None:
    rows = baseline.build_baseline_rows(
        sample_points=[("WLD", _ts(1))],
        venue="bitvavo",
        quote_currency="EUR",
        maps=[_map(1, payload='{"ok":true}')],
        generation_events=[_published_event(1)],
        lifecycle_events=[],
        candles_by_symbol={"WLD": [_candle(2, "131", "110")]},
        forward_candles=3,
    )

    assert rows[0]["history_status"] == baseline.STATUS_HISTORY_INCOMPLETE
    assert rows[0]["history_reason_code"] == "RELOAD_LEVELS_MISSING_IN_NATIVE_HISTORY"
    assert rows[0]["target_levels_json"] == ""
    assert rows[0]["outcome_state"] == baseline.OUTCOME_DATA_UNAVAILABLE
    assert rows[0]["published_generation_source_table"] == "native_short_map_generation_event_v1"
    assert rows[0]["published_generation_row_id"] == 1
    assert rows[0]["published_generation_event_ts_utc"] == baseline.fmt_ts(_ts(0))
    assert rows[0]["published_generation_recorded_ts_utc"] == baseline.fmt_ts(_ts(0))
    assert rows[0]["lifecycle_source_table"] == ""
    assert rows[0]["lifecycle_row_id"] == ""
    assert rows[0]["lifecycle_provenance_status"] == "NO_LIFECYCLE_ROW_KNOWN_BY_T"
    assert rows[0]["lifecycle_provenance_reason"] == "ACTIVE_BY_ABSENCE_OF_LIFECYCLE_EVENT_KNOWN_BY_T"
    assert rows[0]["selection_reason"] == "ACTIVE_NATIVE_MAP_KNOWN_BY_T"


def test_target_first_outcome_uses_only_forward_candles_after_t() -> None:
    rows = baseline.build_baseline_rows(
        sample_points=[("WLD", _ts(1))],
        venue="bitvavo",
        quote_currency="EUR",
        maps=[_map(1)],
        generation_events=[_published_event(1)],
        lifecycle_events=[],
        candles_by_symbol={
            "WLD": [
                _candle(1, "200", "50"),  # At T, not after T, must be ignored.
                _candle(2, "129", "110"),
                _candle(3, "131", "111"),
            ]
        },
        forward_candles=3,
    )

    assert rows[0]["history_status"] == baseline.STATUS_OK
    assert rows[0]["outcome_state"] == baseline.OUTCOME_TARGET_FIRST
    assert rows[0]["first_touch_ts_utc"] == baseline.fmt_ts(_ts(3))
    assert rows[0]["first_target_price"] == "130"
    assert rows[0]["published_generation_source_table"] == "native_short_map_generation_event_v1"
    assert rows[0]["published_generation_row_id"] == 1
    assert rows[0]["lifecycle_source_table"] == ""
    assert rows[0]["lifecycle_row_id"] == ""
    assert rows[0]["selection_reason"] == "ACTIVE_NATIVE_MAP_KNOWN_BY_T"


def test_selected_context_provenance_includes_lifecycle_row_when_used() -> None:
    rows = baseline.build_baseline_rows(
        sample_points=[("WLD", _ts(1))],
        venue="bitvavo",
        quote_currency="EUR",
        maps=[_map(1)],
        generation_events=[_published_event(1, event_id=9)],
        lifecycle_events=[
            _lifecycle_event(17, 1, "ACTIVATED", event_ts=_ts(0), created_at=_ts(0)),
        ],
        candles_by_symbol={"WLD": [_candle(2, "131", "111")]},
        forward_candles=3,
    )

    assert rows[0]["history_status"] == baseline.STATUS_OK
    assert rows[0]["published_generation_source_table"] == "native_short_map_generation_event_v1"
    assert rows[0]["published_generation_row_id"] == 9
    assert rows[0]["published_generation_event_ts_utc"] == baseline.fmt_ts(_ts(0))
    assert rows[0]["published_generation_recorded_ts_utc"] == baseline.fmt_ts(_ts(0))
    assert rows[0]["lifecycle_source_table"] == "native_short_map_lifecycle_event_v1"
    assert rows[0]["lifecycle_row_id"] == 17
    assert rows[0]["lifecycle_event_ts_utc"] == baseline.fmt_ts(_ts(0))
    assert rows[0]["lifecycle_recorded_ts_utc"] == baseline.fmt_ts(_ts(0))
    assert rows[0]["lifecycle_provenance_status"] == "LIFECYCLE_ROW_KNOWN_BY_T"
    assert rows[0]["lifecycle_provenance_reason"] == "ACTIVATED"


def test_unavailable_context_provenance_includes_terminal_lifecycle_row() -> None:
    rows = baseline.build_baseline_rows(
        sample_points=[("WLD", _ts(1))],
        venue="bitvavo",
        quote_currency="EUR",
        maps=[_map(1)],
        generation_events=[_published_event(1, event_id=9)],
        lifecycle_events=[
            _lifecycle_event(18, 1, "COMPLETED", event_ts=_ts(0), created_at=_ts(0)),
        ],
        candles_by_symbol={"WLD": [_candle(2, "131", "111")]},
        forward_candles=3,
    )

    assert rows[0]["history_status"] == baseline.STATUS_DATA_UNAVAILABLE
    assert rows[0]["history_reason_code"] == "NO_ACTIVE_NATIVE_MAP_BY_T"
    assert rows[0]["published_generation_row_id"] == 9
    assert rows[0]["lifecycle_source_table"] == "native_short_map_lifecycle_event_v1"
    assert rows[0]["lifecycle_row_id"] == 18
    assert rows[0]["lifecycle_provenance_status"] == "LIFECYCLE_ROW_KNOWN_BY_T"
    assert rows[0]["lifecycle_provenance_reason"] == "COMPLETED"


def test_same_candle_target_and_invalidation_is_ambiguous() -> None:
    levels = baseline.ExtractedMapLevels(
        target_levels=(Decimal("130"),),
        reload_levels=(Decimal("115"),),
        invalidation_price=Decimal("98"),
        direction="BULLISH",
    )

    result = baseline.evaluate_outcome(levels=levels, candles_after_t=[_candle(2, "131", "97")])

    assert result["outcome_state"] == baseline.OUTCOME_AMBIGUOUS
    assert result["outcome_reason_code"] == "TARGET_AND_INVALIDATION_IN_SAME_CANDLE"


def test_contract_bans_current_snapshot_csv_for_reconstruction() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "load_native_short_context_rows" not in source
    assert "DEFAULT_ROWS_CSV" not in source
    assert "read_csv_rows" not in source
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    joined = "\n".join(imported_modules)
    assert "reporting" not in joined
    assert "decision_gate" not in joined
    assert "execution_planner" not in joined
    assert "executor" not in joined


def test_manifest_records_safety_and_no_csv_diagnostic() -> None:
    out = Path("/tmp/short-swing-baseline-test")
    rows = [{"history_status": baseline.STATUS_OK, "outcome_state": baseline.OUTCOME_TARGET_FIRST}]
    manifest = baseline.build_manifest(
        run_id="run_test",
        output_dir=out,
        symbols=["WLD"],
        start_ts=_ts(0),
        end_ts=_ts(4),
        venue="bitvavo",
        quote_currency="EUR",
        forward_candles=3,
        rows=rows,
        artifact_paths={},
        generated_at_ts_utc=_ts(5),
    )

    assert manifest["current_snapshot_csv_usage"] == "PROHIBITED_FOR_HISTORICAL_RECONSTRUCTION"
    assert manifest["non_historical_diagnostic_cross_check_used"] is False
    assert manifest["safety_markers"]["db_writes"] == 0
    assert manifest["safety_markers"]["decision_gate"] == "none"
