from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.market_data.native_short_map_lifecycle_v1 import (
    DATA_UNAVAILABLE_REASON_CODES,
    NativeShortMapGenerationEvent,
    NativeShortMapGenerationEventType,
    NativeShortMapLifecycleEvent,
    NativeShortMapLifecycleEventType,
    NativeShortMapLifecycleState,
    NativeShortMapLifecycleValidationError,
    NativeShortMapRecord,
    NativeShortMapScopeKey,
    NativeShortMapScopeSupport,
    NativeShortMapScopeSupportState,
    project_current_native_short_map_lifecycle,
    validate_native_short_map_write_intent,
)


def _ts(minutes: int) -> datetime:
    return datetime(2026, 6, 26, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)


def _scope(symbol: str = "BTC", *, quote_currency: str = "EUR") -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(venue="BITVAVO", symbol=symbol, quote_currency=quote_currency)


def _supported(symbol: str = "BTC", *, quote_currency: str = "EUR") -> NativeShortMapScopeSupport:
    return NativeShortMapScopeSupport(
        key=_scope(symbol, quote_currency=quote_currency),
        support_state=NativeShortMapScopeSupportState.SUPPORTED,
    )


def _not_applicable(symbol: str = "BTC", *, quote_currency: str = "EUR") -> NativeShortMapScopeSupport:
    return NativeShortMapScopeSupport(
        key=_scope(symbol, quote_currency=quote_currency),
        support_state=NativeShortMapScopeSupportState.NOT_APPLICABLE,
        reason_code="MARKET_SCOPE_UNSUPPORTED",
    )


def _map(
    map_id: int,
    minute: int,
    *,
    symbol: str = "BTC",
    quote_currency: str = "EUR",
    published_generation_attempt_id: str | None = None,
    previous_map_id: int | None = None,
) -> NativeShortMapRecord:
    ts = _ts(minute)
    return NativeShortMapRecord(
        map_id=map_id,
        key=_scope(symbol, quote_currency=quote_currency),
        published_at_utc=ts,
        structure_hash=f"hash-{symbol}-{quote_currency}-{map_id}",
        generator_name="native_short_map_generator",
        generator_version="v1",
        fib_model_name="fib_model",
        fib_model_version="v1",
        published_generation_attempt_id=published_generation_attempt_id or f"attempt-{map_id}",
        previous_map_id=previous_map_id,
        previous_map_cycle_id=None,
        map_cycle_id=f"cycle-{map_id}",
        market_snapshot_ts_utc=ts,
        anchor_low_ts_utc=ts,
        anchor_low_price=Decimal("100.0"),
        anchor_high_ts_utc=ts,
        anchor_high_price=Decimal("125.0"),
        retrace_ratio=Decimal("0.618"),
        retrace_price=Decimal("115.0"),
        fib_ratios_json='["0.382","0.5","0.618"]',
        target_levels_json='["130.0","140.0"]',
        invalidation_price=Decimal("98.0"),
        invalidation_rule="BREAK_ANCHOR_LOW",
        source_primary_candle_ts_utc=ts,
        source_support_candle_ts_utc=ts,
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        source_primary_candle_count=80,
        source_support_candle_count=240,
        map_payload_json='{"ok":true}',
    )


def _generation_event(
    generation_event_id: int,
    event_type: NativeShortMapGenerationEventType,
    minute: int,
    *,
    attempt_id: str = "attempt-1",
    reason_code: str | None = None,
    map_id: int | None = None,
    symbol: str = "BTC",
    quote_currency: str = "EUR",
) -> NativeShortMapGenerationEvent:
    return NativeShortMapGenerationEvent(
        generation_event_id=generation_event_id,
        key=_scope(symbol, quote_currency=quote_currency),
        attempt_id=attempt_id,
        event_type=event_type,
        event_ts_utc=_ts(minute),
        reason_code=reason_code,
        map_id=map_id,
    )


def _lifecycle_event(
    lifecycle_event_id: int,
    map_id: int,
    event_type: NativeShortMapLifecycleEventType,
    minute: int,
    *,
    reason_code: str | None = None,
    successor_map_id: int | None = None,
) -> NativeShortMapLifecycleEvent:
    return NativeShortMapLifecycleEvent(
        lifecycle_event_id=lifecycle_event_id,
        map_id=map_id,
        event_type=event_type,
        event_ts_utc=_ts(minute),
        reason_code=reason_code,
        successor_map_id=successor_map_id,
    )


def _published_attempt_events(
    *,
    map_id: int,
    started_event_id: int,
    published_event_id: int,
    start_minute: int,
    publish_minute: int,
    symbol: str = "BTC",
    quote_currency: str = "EUR",
    attempt_id: str | None = None,
) -> list[NativeShortMapGenerationEvent]:
    resolved_attempt_id = attempt_id or f"attempt-{map_id}"
    return [
        _generation_event(
            started_event_id,
            NativeShortMapGenerationEventType.ATTEMPT_STARTED,
            start_minute,
            attempt_id=resolved_attempt_id,
            symbol=symbol,
            quote_currency=quote_currency,
        ),
        _generation_event(
            published_event_id,
            NativeShortMapGenerationEventType.PUBLISHED,
            publish_minute,
            attempt_id=resolved_attempt_id,
            map_id=map_id,
            symbol=symbol,
            quote_currency=quote_currency,
        ),
    ]


def test_active_map_wins_precedence() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[_map(1, 1), _map(2, 10)],
        generation_events=[
            _generation_event(5, NativeShortMapGenerationEventType.FAILED, 11, attempt_id="attempt-2"),
        ],
        lifecycle_events=[
            _lifecycle_event(2, 1, NativeShortMapLifecycleEventType.SUPERSEDED, 9, successor_map_id=2),
        ],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_ACTIVE
    assert result.active_map_id == 2


def test_projection_scope_includes_quote_currency() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(quote_currency="EUR"),
        maps=[_map(1, 1, quote_currency="USD"), _map(2, 2, quote_currency="EUR")],
        generation_events=[],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_ACTIVE
    assert result.active_map_id == 2


def test_open_attempt_beats_failed_attempt() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[
            _generation_event(1, NativeShortMapGenerationEventType.FAILED, 2, attempt_id="attempt-1"),
            _generation_event(2, NativeShortMapGenerationEventType.ATTEMPT_STARTED, 5, attempt_id="attempt-2"),
        ],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_GENERATING
    assert result.open_attempt_id == "attempt-2"


def test_failed_attempt_projects_generation_failed() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[
            _generation_event(
                3,
                NativeShortMapGenerationEventType.FAILED,
                3,
                reason_code="UNHANDLED_EXCEPTION",
            ),
        ],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_GENERATION_FAILED
    assert result.authoritative_reason_code == "UNHANDLED_EXCEPTION"


def test_rejected_data_availability_projects_data_unavailable() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[
            _generation_event(
                4,
                NativeShortMapGenerationEventType.REJECTED,
                4,
                reason_code="CANDLE_GAPS_DETECTED",
            ),
        ],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_DATA_UNAVAILABLE


def test_rejected_non_data_reason_projects_rebuild_rejected() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[
            _generation_event(
                4,
                NativeShortMapGenerationEventType.REJECTED,
                4,
                reason_code="ANCHOR_SELECTION_REJECTED",
            ),
        ],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_REBUILD_REJECTED


def test_terminal_map_projects_rebuild_required() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[_map(1, 1)],
        generation_events=[],
        lifecycle_events=[
            _lifecycle_event(10, 1, NativeShortMapLifecycleEventType.COMPLETED, 6),
        ],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_REBUILD_REQUIRED
    assert result.terminal_map_id == 1


def test_supported_scope_without_authoritative_attempt_projects_rebuild_required() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_REBUILD_REQUIRED


def test_not_applicable_scope_projects_not_applicable() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_not_applicable(),
        maps=[],
        generation_events=[],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_NOT_APPLICABLE


def test_skipped_event_is_visible_but_does_not_override_failed_state() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[
            _generation_event(3, NativeShortMapGenerationEventType.FAILED, 3, attempt_id="attempt-1"),
            _generation_event(
                4,
                NativeShortMapGenerationEventType.SKIPPED,
                6,
                attempt_id="attempt-2",
                reason_code="THROTTLED",
            ),
        ],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_GENERATION_FAILED
    assert result.latest_skip_attempt_id == "attempt-2"
    assert result.latest_skip_reason_code == "THROTTLED"


def test_equal_published_timestamps_use_map_id_tiebreaker() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[_map(10, 1), _map(11, 1)],
        generation_events=[],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_ACTIVE
    assert result.active_map_id == 11


def test_equal_generation_timestamps_use_generation_event_id_tiebreaker() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[],
        generation_events=[
            _generation_event(
                10,
                NativeShortMapGenerationEventType.REJECTED,
                1,
                attempt_id="attempt-10",
                reason_code="ANCHOR_SELECTION_REJECTED",
            ),
            _generation_event(
                11,
                NativeShortMapGenerationEventType.FAILED,
                1,
                attempt_id="attempt-11",
                reason_code="GENERATOR_CRASH",
            ),
        ],
        lifecycle_events=[],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_GENERATION_FAILED
    assert result.authoritative_attempt_id == "attempt-11"


def test_equal_lifecycle_timestamps_use_lifecycle_event_id_tiebreaker() -> None:
    result = project_current_native_short_map_lifecycle(
        scope_support=_supported(),
        maps=[_map(1, 1)],
        generation_events=[],
        lifecycle_events=[
            _lifecycle_event(1, 1, NativeShortMapLifecycleEventType.ACTIVATED, 2),
            _lifecycle_event(2, 1, NativeShortMapLifecycleEventType.COMPLETED, 2),
        ],
    )

    assert result.lifecycle_state == NativeShortMapLifecycleState.MAP_REBUILD_REQUIRED
    assert result.terminal_map_id == 1


def test_validator_accepts_valid_sequence() -> None:
    validate_native_short_map_write_intent(
        scope_support=_supported(),
        maps=[_map(1, 1)],
        generation_events=[
            _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED, 1, attempt_id="attempt-1"),
            _generation_event(
                2,
                NativeShortMapGenerationEventType.PUBLISHED,
                2,
                attempt_id="attempt-1",
                map_id=1,
            ),
        ],
        lifecycle_events=[
            _lifecycle_event(1, 1, NativeShortMapLifecycleEventType.ACTIVATED, 2),
        ],
    )


def test_validator_rejects_activated_after_terminal_event() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="LIFECYCLE_EVENT_AFTER_TERMINAL"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[_map(1, 1)],
            generation_events=_published_attempt_events(
                map_id=1,
                started_event_id=10,
                published_event_id=11,
                start_minute=0,
                publish_minute=1,
            ),
            lifecycle_events=[
                _lifecycle_event(1, 1, NativeShortMapLifecycleEventType.COMPLETED, 1),
                _lifecycle_event(2, 1, NativeShortMapLifecycleEventType.ACTIVATED, 2),
            ],
        )


def test_validator_rejects_second_lifecycle_event_after_terminal_event() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="LIFECYCLE_EVENT_AFTER_TERMINAL"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[_map(1, 1)],
            generation_events=_published_attempt_events(
                map_id=1,
                started_event_id=10,
                published_event_id=11,
                start_minute=0,
                publish_minute=1,
            ),
            lifecycle_events=[
                _lifecycle_event(1, 1, NativeShortMapLifecycleEventType.EXPIRED, 1),
                _lifecycle_event(2, 1, NativeShortMapLifecycleEventType.INVALIDATED, 2),
            ],
        )


def test_validator_rejects_superseded_without_successor_map() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="SUPERSEDED_REQUIRES_SUCCESSOR"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[_map(1, 1)],
            generation_events=_published_attempt_events(
                map_id=1,
                started_event_id=10,
                published_event_id=11,
                start_minute=0,
                publish_minute=1,
            ),
            lifecycle_events=[
                _lifecycle_event(1, 1, NativeShortMapLifecycleEventType.SUPERSEDED, 1),
            ],
        )


def test_validator_rejects_lifecycle_event_outside_scope() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="LIFECYCLE_EVENT_SCOPE_MISMATCH"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[_map(1, 1, quote_currency="USD")],
            generation_events=[],
            lifecycle_events=[
                _lifecycle_event(1, 1, NativeShortMapLifecycleEventType.ACTIVATED, 1),
            ],
        )


def test_validator_rejects_terminal_generation_event_without_start() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="TERMINAL_GENERATION_EVENT_WITHOUT_START"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[],
            generation_events=[
                _generation_event(2, NativeShortMapGenerationEventType.FAILED, 2, attempt_id="attempt-2"),
            ],
            lifecycle_events=[],
        )


def test_validator_rejects_published_event_with_cross_scope_map() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="PUBLISHED_MAP_SCOPE_MISMATCH"):
        validate_native_short_map_write_intent(
            scope_support=_supported(quote_currency="EUR"),
            maps=[_map(1, 1, quote_currency="USD")],
            generation_events=[
                _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED, 1, attempt_id="attempt-1"),
                _generation_event(
                    2,
                    NativeShortMapGenerationEventType.PUBLISHED,
                    2,
                    attempt_id="attempt-1",
                    map_id=1,
                    quote_currency="EUR",
                ),
            ],
            lifecycle_events=[],
        )


def test_validator_rejects_multiple_terminal_generation_events_for_one_attempt() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="MULTIPLE_TERMINAL_GENERATION_EVENTS"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[],
            generation_events=[
                _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED, 1, attempt_id="attempt-1"),
                _generation_event(2, NativeShortMapGenerationEventType.REJECTED, 2, attempt_id="attempt-1"),
                _generation_event(3, NativeShortMapGenerationEventType.FAILED, 3, attempt_id="attempt-1"),
            ],
            lifecycle_events=[],
        )


def test_validator_rejects_map_without_matching_attempt_started_for_published_generation_attempt() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="MAP_PUBLISHED_ATTEMPT_START_MISSING"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[_map(1, 1)],
            generation_events=[
                _generation_event(
                    2,
                    NativeShortMapGenerationEventType.PUBLISHED,
                    2,
                    attempt_id="attempt-1",
                    map_id=1,
                ),
            ],
            lifecycle_events=[],
        )


def test_validator_rejects_map_without_matching_published_event_for_exact_map_id() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="MAP_PUBLISHED_EVENT_MISSING"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[
                _map(1, 1, published_generation_attempt_id="attempt-1"),
                _map(2, 2, published_generation_attempt_id="attempt-1"),
            ],
            generation_events=[
                _generation_event(1, NativeShortMapGenerationEventType.ATTEMPT_STARTED, 1, attempt_id="attempt-1"),
                _generation_event(
                    2,
                    NativeShortMapGenerationEventType.PUBLISHED,
                    2,
                    attempt_id="attempt-1",
                    map_id=2,
                ),
            ],
            lifecycle_events=[],
        )


def test_validator_rejects_previous_map_id_missing_from_supplied_maps() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="PREVIOUS_MAP_ID_MISSING"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[
                _map(
                    2,
                    2,
                    published_generation_attempt_id="attempt-2",
                    previous_map_id=1,
                ),
            ],
            generation_events=_published_attempt_events(
                map_id=2,
                started_event_id=20,
                published_event_id=21,
                start_minute=1,
                publish_minute=2,
                attempt_id="attempt-2",
            ),
            lifecycle_events=[],
        )


def test_validator_rejects_previous_map_id_outside_scope() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="PREVIOUS_MAP_SCOPE_MISMATCH"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[
                _map(1, 1, quote_currency="USD", published_generation_attempt_id="attempt-1"),
                _map(
                    2,
                    2,
                    published_generation_attempt_id="attempt-2",
                    previous_map_id=1,
                ),
            ],
            generation_events=_published_attempt_events(
                map_id=2,
                started_event_id=20,
                published_event_id=21,
                start_minute=1,
                publish_minute=2,
                attempt_id="attempt-2",
            ),
            lifecycle_events=[],
        )


def test_validator_rejects_superseded_successor_missing_from_supplied_maps() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="SUPERSEDED_SUCCESSOR_MISSING"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[_map(1, 1)],
            generation_events=_published_attempt_events(
                map_id=1,
                started_event_id=10,
                published_event_id=11,
                start_minute=0,
                publish_minute=1,
            ),
            lifecycle_events=[
                _lifecycle_event(
                    1,
                    1,
                    NativeShortMapLifecycleEventType.SUPERSEDED,
                    2,
                    successor_map_id=2,
                ),
            ],
        )


def test_validator_rejects_superseded_successor_outside_scope() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="SUPERSEDED_SUCCESSOR_SCOPE_MISMATCH"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[
                _map(1, 1, published_generation_attempt_id="attempt-1"),
                _map(2, 2, quote_currency="USD", published_generation_attempt_id="attempt-2"),
            ],
            generation_events=_published_attempt_events(
                map_id=1,
                started_event_id=10,
                published_event_id=11,
                start_minute=0,
                publish_minute=1,
                attempt_id="attempt-1",
            ),
            lifecycle_events=[
                _lifecycle_event(
                    1,
                    1,
                    NativeShortMapLifecycleEventType.SUPERSEDED,
                    3,
                    successor_map_id=2,
                ),
            ],
        )


def test_validator_rejects_superseded_successor_not_newer_than_superseded_map() -> None:
    with pytest.raises(NativeShortMapLifecycleValidationError, match="SUPERSEDED_SUCCESSOR_NOT_NEWER"):
        validate_native_short_map_write_intent(
            scope_support=_supported(),
            maps=[
                _map(2, 2, published_generation_attempt_id="attempt-2"),
                _map(1, 2, published_generation_attempt_id="attempt-1"),
            ],
            generation_events=[
                *_published_attempt_events(
                    map_id=2,
                    started_event_id=20,
                    published_event_id=21,
                    start_minute=1,
                    publish_minute=2,
                    attempt_id="attempt-2",
                ),
                *_published_attempt_events(
                    map_id=1,
                    started_event_id=10,
                    published_event_id=11,
                    start_minute=1,
                    publish_minute=2,
                    attempt_id="attempt-1",
                ),
            ],
            lifecycle_events=[
                _lifecycle_event(
                    1,
                    2,
                    NativeShortMapLifecycleEventType.SUPERSEDED,
                    3,
                    successor_map_id=1,
                ),
            ],
        )


def test_data_unavailable_reason_codes_match_contract() -> None:
    assert DATA_UNAVAILABLE_REASON_CODES == {
        "CANDLES_INSUFFICIENT",
        "CANDLE_GAPS_DETECTED",
        "CANDLE_SNAPSHOT_STALE",
        "ASSET_HISTORY_TOO_SHORT",
        "INGEST_LOOKBACK_LIMIT",
        "NO_CLOSED_DAILY_CANDLES",
    }
