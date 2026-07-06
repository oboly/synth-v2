from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    NativeShortMaterializerRunRecord,
    NativeShortObservationFreshnessState,
    NativeShortScopeActionabilityState,
    NativeShortScopeCadenceConfig,
    NativeShortScopeGeometryAction,
    NativeShortScopeMapLifecycleState,
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
        run_id=1,
        run_uuid="00000000-0000-0000-0000-000000000001",
        observed_at_utc=_TS,
        cadence_contract_version="v1",
        observation_status=NativeShortScopeObservationStatus.EVALUATED,
        source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
        primary_source_freshness_limit_seconds=43200,
        supporting_source_freshness_limit_seconds=10800,
        geometry_action=NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY,
    )
    NativeShortScopeStatusRecord(
        key=key,
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        scope_status_code=NativeShortScopeStatusCode.CURRENT_EVALUATION,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_ACTIVE,
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


def test_invalid_geometry_action_rejects() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="geometry_action"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            cadence_contract_version="v1",
            observation_status="EVALUATED",
            source_state="SOURCE_CURRENT",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            geometry_action="HEARTBEAT",
        )


@pytest.mark.parametrize("run_id", [0, -1])
def test_zero_or_negative_observation_run_id_rejects(run_id: int) -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="run_id"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=run_id,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            cadence_contract_version="v1",
            observation_status="EVALUATED",
            source_state="SOURCE_CURRENT",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            geometry_action="UNCHANGED_GEOMETRY",
        )


def test_invalid_selected_map_lifecycle_state_rejects() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="map_lifecycle_state"):
        NativeShortScopeStatusRecord(
            key=_key(),
            scope_support_state="SUPPORTED",
            scope_status_code="CURRENT_EVALUATION",
            map_lifecycle_state="MAP_SUPERSEDED",
            observation_freshness_state="OBSERVATION_CURRENT",
            source_freshness_state="SOURCE_CURRENT",
            actionability_state="ACTIONABLE_ACTIVE_MAP",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            cadence_contract_version="v1",
            projection_as_of_utc=_TS,
            rebuilt_at_utc=_TS,
        )


def test_status_row_rejects_not_applicable_scope_support() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="INVALID_SCOPE_SUPPORT_STATE_FOR_STATUS"):
        NativeShortScopeStatusRecord(
            key=_key(),
            scope_support_state="NOT_APPLICABLE",
            scope_status_code="CURRENT_EVALUATION",
            map_lifecycle_state="MAP_ACTIVE",
            observation_freshness_state="OBSERVATION_CURRENT",
            source_freshness_state="SOURCE_CURRENT",
            actionability_state="ACTIONABLE_ACTIVE_MAP",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            cadence_contract_version="v1",
            projection_as_of_utc=_TS,
            rebuilt_at_utc=_TS,
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
            scope_support_state="SUPPORTED",
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


# --- PR A1b: cadence-configuration-unavailable state -----------------------


def test_valid_configuration_unavailable_observation_is_accepted() -> None:
    NativeShortScopeObservationRecord(
        key=_key(),
        run_id=1,
        run_uuid="00000000-0000-0000-0000-000000000001",
        observed_at_utc=_TS,
        observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
        observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    )


def test_valid_configuration_unavailable_status_is_accepted() -> None:
    NativeShortScopeStatusRecord(
        key=_key(),
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        scope_status_code=NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.NO_CURRENT_MAP,
        observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
        actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
        projection_as_of_utc=_TS,
        rebuilt_at_utc=_TS,
        scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    )


def test_configuration_unavailable_status_preserves_independently_known_map_lifecycle() -> None:
    """map_lifecycle_state may still reflect a real, independently known map
    lifecycle (e.g. MAP_ACTIVE) even while the top-level code is
    CONFIGURATION_UNAVAILABLE, per the contract's Conditional Nullability and
    Required Behavior sections."""
    NativeShortScopeStatusRecord(
        key=_key(),
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        scope_status_code=NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_ACTIVE,
        observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
        actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
        projection_as_of_utc=_TS,
        rebuilt_at_utc=_TS,
        scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    )


def test_configuration_unavailable_observation_rejects_non_null_cadence_version() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="cadence_contract_version"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            cadence_contract_version="v1",
        )


def test_configuration_unavailable_observation_rejects_non_null_source_state() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="source_state"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
        )


def test_configuration_unavailable_observation_rejects_non_null_geometry_action() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="geometry_action"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            geometry_action=NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY,
        )


def test_configuration_unavailable_observation_rejects_non_null_freshness_limits() -> None:
    with pytest.raises(
        NativeShortScopeStatusValidationError, match="primary_source_freshness_limit_seconds"
    ):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            primary_source_freshness_limit_seconds=43200,
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="supporting_source_freshness_limit_seconds"
    ):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            supporting_source_freshness_limit_seconds=10800,
        )


def test_configuration_unavailable_observation_rejects_non_null_evaluation_due_at_utc() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="evaluation_due_at_utc"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
            evaluation_due_at_utc=_TS,
        )


def test_configuration_unavailable_observation_requires_exact_reason_code() -> None:
    with pytest.raises(
        NativeShortScopeStatusValidationError, match="CONFIGURATION_UNAVAILABLE_REQUIRES_REASON_CODE"
    ):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
            observation_reason_code="SOME_OTHER_REASON",
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="CONFIGURATION_UNAVAILABLE_REQUIRES_REASON_CODE"
    ):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
        )


def test_ordinary_observation_still_rejects_missing_cadence_source_geometry_fields() -> None:
    base_kwargs = dict(
        key=_key(),
        run_id=1,
        run_uuid="00000000-0000-0000-0000-000000000001",
        observed_at_utc=_TS,
        observation_status=NativeShortScopeObservationStatus.EVALUATED,
    )

    with pytest.raises(NativeShortScopeStatusValidationError, match="cadence_contract_version"):
        NativeShortScopeObservationRecord(
            **base_kwargs,
            source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            geometry_action=NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY,
        )

    with pytest.raises(NativeShortScopeStatusValidationError, match="source_state"):
        NativeShortScopeObservationRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
            geometry_action=NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY,
        )

    with pytest.raises(NativeShortScopeStatusValidationError, match="geometry_action"):
        NativeShortScopeObservationRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="primary_source_freshness_limit_seconds"
    ):
        NativeShortScopeObservationRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            supporting_source_freshness_limit_seconds=10800,
            geometry_action=NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY,
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="supporting_source_freshness_limit_seconds"
    ):
        NativeShortScopeObservationRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            primary_source_freshness_limit_seconds=43200,
            geometry_action=NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY,
        )


def test_configuration_unavailable_status_rejects_non_null_cadence_fields() -> None:
    base_kwargs = dict(
        key=_key(),
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        scope_status_code=NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.NO_CURRENT_MAP,
        observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
        actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
        projection_as_of_utc=_TS,
        rebuilt_at_utc=_TS,
        scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    )

    with pytest.raises(NativeShortScopeStatusValidationError, match="cadence_contract_version"):
        NativeShortScopeStatusRecord(**base_kwargs, cadence_contract_version="v1")

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="primary_source_freshness_limit_seconds"
    ):
        NativeShortScopeStatusRecord(**base_kwargs, primary_source_freshness_limit_seconds=43200)

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="supporting_source_freshness_limit_seconds"
    ):
        NativeShortScopeStatusRecord(**base_kwargs, supporting_source_freshness_limit_seconds=10800)

    with pytest.raises(NativeShortScopeStatusValidationError, match="source_freshness_state"):
        NativeShortScopeStatusRecord(
            **base_kwargs, source_freshness_state=NativeShortScopeSourceState.SOURCE_CURRENT
        )


def test_configuration_unavailable_status_requires_exact_reason_actionability_and_freshness() -> None:
    base_kwargs = dict(
        key=_key(),
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        scope_status_code=NativeShortScopeStatusCode.CONFIGURATION_UNAVAILABLE,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.NO_CURRENT_MAP,
        projection_as_of_utc=_TS,
        rebuilt_at_utc=_TS,
    )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="CONFIGURATION_UNAVAILABLE_REQUIRES_REASON_CODE"
    ):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
            actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
            scope_status_reason_code="SOME_OTHER_REASON",
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="CONFIGURATION_UNAVAILABLE_REQUIRES_ACTIONABILITY"
    ):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
            actionability_state=NativeShortScopeActionabilityState.BLOCKED_SOURCE,
            scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError,
        match="CONFIGURATION_UNAVAILABLE_REQUIRES_OBSERVATION_FRESHNESS",
    ):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            observation_freshness_state=NativeShortObservationFreshnessState.NO_OBSERVATION,
            actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
            scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
        )


def test_ordinary_status_still_rejects_missing_cadence_and_source_freshness_fields() -> None:
    base_kwargs = dict(
        key=_key(),
        scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
        scope_status_code=NativeShortScopeStatusCode.CURRENT_EVALUATION,
        map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_ACTIVE,
        observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CURRENT,
        actionability_state=NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP,
        projection_as_of_utc=_TS,
        rebuilt_at_utc=_TS,
    )

    with pytest.raises(NativeShortScopeStatusValidationError, match="cadence_contract_version"):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            source_freshness_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
        )

    with pytest.raises(NativeShortScopeStatusValidationError, match="source_freshness_state"):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            primary_source_freshness_limit_seconds=43200,
            supporting_source_freshness_limit_seconds=10800,
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="primary_source_freshness_limit_seconds"
    ):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            source_freshness_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            supporting_source_freshness_limit_seconds=10800,
        )

    with pytest.raises(
        NativeShortScopeStatusValidationError, match="supporting_source_freshness_limit_seconds"
    ):
        NativeShortScopeStatusRecord(
            **base_kwargs,
            cadence_contract_version="v1",
            source_freshness_state=NativeShortScopeSourceState.SOURCE_CURRENT,
            primary_source_freshness_limit_seconds=43200,
        )


def test_configuration_unavailable_enum_values_reject_invalid_strings() -> None:
    with pytest.raises(NativeShortScopeStatusValidationError, match="INVALID_ENUM"):
        NativeShortScopeObservationRecord(
            key=_key(),
            run_id=1,
            run_uuid="00000000-0000-0000-0000-000000000001",
            observed_at_utc=_TS,
            observation_status="SKIPPED_CONFIG_MISSING",
            observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
        )

    with pytest.raises(NativeShortScopeStatusValidationError, match="INVALID_ENUM"):
        NativeShortScopeStatusRecord(
            key=_key(),
            scope_support_state=NativeShortScopeSupportEventState.SUPPORTED,
            scope_status_code="CONFIG_MISSING",
            map_lifecycle_state=NativeShortScopeMapLifecycleState.NO_CURRENT_MAP,
            observation_freshness_state=NativeShortObservationFreshnessState.OBSERVATION_CONFIGURATION_UNAVAILABLE,
            actionability_state=NativeShortScopeActionabilityState.BLOCKED_CONFIGURATION,
            projection_as_of_utc=_TS,
            rebuilt_at_utc=_TS,
            scope_status_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
        )
