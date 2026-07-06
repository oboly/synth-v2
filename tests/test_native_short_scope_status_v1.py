from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NativeShortMaterializerRunRecord,
    NativeShortScopeActionabilityState,
    NativeShortScopeCadenceConfig,
    NativeShortScopeObservationRecord,
    NativeShortScopeObservationStatus,
    NativeShortScopeSourceState,
    NativeShortScopeStatusCode,
    NativeShortScopeStatusRecord,
    NativeShortScopeStatusValidationError,
    NativeShortScopeSupportEvent,
    NativeShortScopeSupportEventState,
    native_short_scope_key_from_parts,
    validate_native_short_scope_key,
)


_TS = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _key() -> NativeShortMapScopeKey:
    return native_short_scope_key_from_parts(
        venue="bitvavo",
        symbol="BTC",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def test_valid_full_key_records_construct() -> None:
    key = _key()

    NativeShortMaterializerRunRecord(
        run_uuid="00000000-0000-0000-0000-000000000001",
        runner_name="native_short_map_materializer_v1",
        runner_version="0.1",
        contract_version="native_short_scope_status_contract_v1",
        trigger_type="MANUAL",
        started_at_utc=_TS,
        requested_scope_count=1,
        terminal_status="FINISHED",
        finished_at_utc=_TS,
    )
    NativeShortScopeObservationRecord(
        key=key,
        run_uuid="00000000-0000-0000-0000-000000000001",
        observed_at_utc=_TS,
        cadence_contract_version="v1",
        observation_status=NativeShortScopeObservationStatus.EVALUATED,
        source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
        primary_source_freshness_limit_seconds=43200,
        supporting_source_freshness_limit_seconds=10800,
        geometry_action="UNCHANGED_GEOMETRY",
    )
    NativeShortScopeStatusRecord(
        key=key,
        scope_status_code=NativeShortScopeStatusCode.CURRENT_EVALUATION,
        map_lifecycle_state="MAP_ACTIVE",
        observation_freshness_state="OBSERVATION_CURRENT",
        source_freshness_state="SOURCE_CURRENT",
        actionability_state=NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP,
        primary_source_freshness_limit_seconds=43200,
        supporting_source_freshness_limit_seconds=10800,
        cadence_contract_version="v1",
        projection_as_of_utc=_TS,
        rebuilt_at_utc=_TS,
    )
    NativeShortScopeCadenceConfig(
        key=key,
        cadence_contract_version="v1",
        target_evaluation_interval="1h",
        primary_source_freshness_limit_seconds=43200,
        supporting_source_freshness_limit_seconds=10800,
        evaluation_grace_seconds=900,
        recent_scope_grace_seconds=3600,
        effective_from_utc=_TS,
    )
    NativeShortScopeSupportEvent(
        key=key,
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        event_ts_utc=_TS,
        source_name="migration",
        source_version="v1",
        created_at_utc=_TS,
    )


def test_symbol_only_or_partial_scope_identity_rejects() -> None:
    with pytest.raises(TypeError):
        native_short_scope_key_from_parts(symbol="BTC")  # type: ignore[call-arg]

    with pytest.raises(NativeShortScopeStatusValidationError, match="venue"):
        validate_native_short_scope_key(
            NativeShortMapScopeKey(
                venue="",
                symbol="BTC",
                quote_currency="EUR",
                fib_trading_horizon="SHORT",
                primary_interval="4h",
                supporting_interval="1h",
            )
        )


def test_short_tactical_horizon_is_explicitly_validated() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="INVALID_FIB_TRADING_HORIZON"):
        validate_native_short_scope_key(
            NativeShortMapScopeKey(
                venue="bitvavo",
                symbol="BTC",
                quote_currency="EUR",
                fib_trading_horizon="LONG",
                primary_interval="4h",
                supporting_interval="1h",
            )
        )


def test_invalid_enum_values_reject() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="INVALID_ENUM"):
        NativeShortScopeSupportEvent(
            key=_key(),
            scope_support_state="ACTIVE",
            event_ts_utc=_TS,
            source_name="migration",
            source_version="v1",
            created_at_utc=_TS,
        )


def test_naive_timestamps_reject_and_utc_timestamps_pass() -> None:
    NativeShortMaterializerRunRecord(
        run_uuid="00000000-0000-0000-0000-000000000001",
        runner_name="native_short_map_materializer_v1",
        runner_version="0.1",
        contract_version="native_short_scope_status_contract_v1",
        trigger_type="MANUAL",
        started_at_utc=_TS,
        requested_scope_count=1,
    )

    with pytest.raises(NativeShortScopeStatusValidationError, match="TIMESTAMP_NOT_UTC"):
        NativeShortMaterializerRunRecord(
            run_uuid="00000000-0000-0000-0000-000000000001",
            runner_name="native_short_map_materializer_v1",
            runner_version="0.1",
            contract_version="native_short_scope_status_contract_v1",
            trigger_type="MANUAL",
            started_at_utc=datetime(2026, 7, 6, 12, 0),
            requested_scope_count=1,
        )


def test_status_row_requires_projection_as_of_utc() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="projection_as_of_utc"):
        NativeShortScopeStatusRecord(
            key=_key(),
            scope_status_code="CURRENT_EVALUATION",
            map_lifecycle_state="MAP_ACTIVE",
            observation_freshness_state="OBSERVATION_CURRENT",
            source_freshness_state="SOURCE_CURRENT",
            actionability_state="ACTIONABLE_ACTIVE_MAP",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            cadence_contract_version="v1",
            projection_as_of_utc=None,  # type: ignore[arg-type]
            rebuilt_at_utc=_TS,
        )
