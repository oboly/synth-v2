from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from src.market_data.native_short_map_level_status_materializer_v1 import (
    materialize_native_short_map_level_status_for_scope,
)
from src.market_data.native_short_map_level_status_v1 import (
    delete_native_short_map_level_status_for_scope,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_map_materializer_v1 import materialize_scope_symbol
from src.market_data.native_short_multi_asset_audit_v1 import summarize_writer_provenance
from src.market_data.native_short_scope_status_materializer_v1 import (
    run_native_short_scope_status_materializer,
)
from src.market_data.run_native_short_map_scope_seed_canary_v1 import run_write_symbol
from src.market_data.native_short_writer_provenance_v1 import (
    CANONICAL_REPOSITORY_WRITER_OWNER,
    CHAIN_TRIGGER_TYPE,
    MANUAL_MAP_TRIGGER_TYPE,
    PROVENANCE_CONTRACT_VERSION,
    TEST_REPOSITORY_COMMIT_SHA,
    TEST_TRIGGER_TYPE,
    TEST_WRITER_ENTRYPOINT,
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
    NativeShortWriterProvenanceError,
    NativeShortWriterProvenanceState,
    classify_persisted_native_short_writer_provenance,
    validate_native_short_writer_provenance,
)


MIGRATION = Path("db/migrations/20260716_native_short_writer_provenance_v1.sql")


class NoDatabaseTouch:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"database touched before provenance validation: {name}")


def _test_provenance(invocation_uuid: str | None = None) -> NativeShortWriterProvenance:
    return NativeShortWriterProvenance(
        writer_entrypoint=TEST_WRITER_ENTRYPOINT,
        repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
        runner_name="native_short_writer_test_v1",
        runner_version="test-v1",
        execution_mode=NativeShortWriterExecutionMode.TEST,
        invocation_uuid=invocation_uuid or str(uuid.uuid4()),
        repository_commit_sha=TEST_REPOSITORY_COMMIT_SHA,
        host_name="test-host",
        process_id=123,
        trigger_type=TEST_TRIGGER_TYPE,
        trigger_ref="test-suite",
    )


def chain_provenance() -> NativeShortWriterProvenance:
    return NativeShortWriterProvenance(
        writer_entrypoint="scripts/run_chain_4h.sh",
        repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
        runner_name="run_native_short_scope_status_chain_v1",
        runner_version="0.1",
        execution_mode=NativeShortWriterExecutionMode.CHAIN,
        invocation_uuid=str(uuid.uuid4()),
        repository_commit_sha="a" * 40,
        host_name="runtime-host",
        process_id=456,
        trigger_type=CHAIN_TRIGGER_TYPE,
        trigger_ref="scripts/run_chain_4h.sh",
    )


def manual_provenance() -> NativeShortWriterProvenance:
    return NativeShortWriterProvenance(
        writer_entrypoint="src.market_data.run_native_short_map_materializer_v1",
        repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
        runner_name="run_native_short_map_materializer_v1",
        runner_version="0.1",
        execution_mode=NativeShortWriterExecutionMode.MANUAL,
        invocation_uuid=str(uuid.uuid4()),
        repository_commit_sha="b" * 40,
        host_name="operator-host",
        process_id=789,
        trigger_type=MANUAL_MAP_TRIGGER_TYPE,
        trigger_ref="operator-canary-1",
    )


def persisted_row(value: NativeShortWriterProvenance) -> dict[str, object]:
    return {
        "run_uuid": value.invocation_uuid,
        "runner_name": value.runner_name,
        "runner_version": value.runner_version,
        "trigger_type": value.trigger_type,
        "trigger_ref": value.trigger_ref,
        "host_name": value.host_name,
        "process_id": value.process_id,
        "provenance_contract_version": value.provenance_contract_version,
        "writer_entrypoint": value.writer_entrypoint,
        "repository_writer_owner": value.repository_writer_owner,
        "execution_mode": str(value.execution_mode),
        "repository_commit_sha": value.repository_commit_sha,
    }


def test_valid_modes_are_explicit_and_distinct() -> None:
    values = (chain_provenance(), manual_provenance(), _test_provenance())
    for value in values:
        assert validate_native_short_writer_provenance(value) is value
    assert {str(value.execution_mode) for value in values} == {"CHAIN", "MANUAL", "TEST"}


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_commit_sha", "unknown"),
        ("writer_entrypoint", "unsupported.py"),
        ("repository_writer_owner", "invented-owner"),
        ("trigger_ref", ""),
        ("process_id", 0),
    ),
)
def test_malformed_or_contradictory_provenance_fails(field: str, value: object) -> None:
    original = manual_provenance()
    changed = NativeShortWriterProvenance(
        **{**original.__dict__, field: value},
    )
    with pytest.raises(NativeShortWriterProvenanceError):
        validate_native_short_writer_provenance(changed)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "runner_name",
            "run_native_short_map_level_status_materializer_v1",
            "MANUAL_RUNNER_CONTRADICTION",
        ),
        (
            "trigger_type",
            "MANUAL_NATIVE_SHORT_MAP_LEVEL_STATUS",
            "MANUAL_TRIGGER_CONTRADICTION",
        ),
    ),
)
def test_manual_entrypoint_runner_trigger_contract_is_exact(
    field: str,
    value: str,
    message: str,
) -> None:
    original = manual_provenance()
    with pytest.raises(NativeShortWriterProvenanceError, match=message):
        validate_native_short_writer_provenance(
            NativeShortWriterProvenance(**{**original.__dict__, field: value})
        )


def test_unsupported_execution_mode_fails() -> None:
    original = manual_provenance()
    with pytest.raises(NativeShortWriterProvenanceError, match="EXECUTION_MODE_UNSUPPORTED"):
        validate_native_short_writer_provenance(
            NativeShortWriterProvenance(**{**original.__dict__, "execution_mode": "SCHEDULED"})
        )


def test_test_mode_cannot_masquerade_as_production() -> None:
    original = _test_provenance()
    with pytest.raises(NativeShortWriterProvenanceError, match="TEST_RUNNER_MASQUERADES"):
        validate_native_short_writer_provenance(
            NativeShortWriterProvenance(
                **{**original.__dict__, "runner_name": "run_native_short_scope_status_chain_v1"}
            )
        )


def test_rejected_provenance_precedes_every_shared_writer_boundary() -> None:
    invalid = NativeShortWriterProvenance(
        **{**manual_provenance().__dict__, "repository_commit_sha": "invalid"}
    )
    key = NativeShortMapScopeKey("bitvavo", "BTC", "EUR", "SHORT", "4h", "1h")
    with pytest.raises(NativeShortWriterProvenanceError):
        materialize_scope_symbol(
            NoDatabaseTouch(),
            scope_support=None,  # type: ignore[arg-type]
            context_row=None,  # type: ignore[arg-type]
            now_utc=None,  # type: ignore[arg-type]
            write=True,
            provenance=invalid,
        )
    with pytest.raises(NativeShortWriterProvenanceError):
        materialize_native_short_map_level_status_for_scope(
            NoDatabaseTouch(),
            key=key,
            operational_clock=lambda: None,  # type: ignore[return-value]
            provenance=invalid,
        )
    with pytest.raises(NativeShortWriterProvenanceError):
        run_native_short_scope_status_materializer(
            NoDatabaseTouch(),
            scopes=(),
            as_of_utc=None,  # type: ignore[arg-type]
            provenance=invalid,
            operational_clock=lambda: None,  # type: ignore[return-value]
            fetch_context_row=lambda *_: None,
            fetch_existing_maps=lambda *_: [],
            fetch_existing_generation_events=lambda *_: [],
            fetch_existing_lifecycle_events=lambda *_: [],
            fetch_primary_candle_close_timestamps=lambda *_: [],
            fetch_supporting_candle_close_timestamps=lambda *_: [],
        )
    with pytest.raises(NativeShortWriterProvenanceError):
        delete_native_short_map_level_status_for_scope(
            NoDatabaseTouch(),
            key=key,
            provenance=invalid,
        )
    with pytest.raises(NativeShortWriterProvenanceError):
        run_write_symbol(
            NoDatabaseTouch(),
            venue="bitvavo",
            symbol="BTC",
            quote_currency="EUR",
            provenance=invalid,
        )


def test_missing_provenance_cannot_call_writer_api() -> None:
    with pytest.raises(TypeError):
        materialize_scope_symbol(  # type: ignore[call-arg]
            NoDatabaseTouch(),
            scope_support=None,
            context_row=None,
            now_utc=None,
            write=True,
        )


def test_invocation_identity_is_stable_within_run_and_unique_between_runs() -> None:
    first = _test_provenance()
    second = _test_provenance()
    assert validate_native_short_writer_provenance(first).invocation_uuid == first.invocation_uuid
    assert first.invocation_uuid != second.invocation_uuid


def test_historical_rows_remain_legacy_without_inference() -> None:
    legacy = {
        "run_uuid": "b5d9ca6b-ff24-46eb-8155-4e663b948ebc",
        "host_name": None,
        "process_id": None,
        "trigger_ref": None,
        "provenance_contract_version": None,
    }
    assert classify_persisted_native_short_writer_provenance(legacy) == (
        NativeShortWriterProvenanceState.LEGACY_UNATTRIBUTED
    )
    assert classify_persisted_native_short_writer_provenance(dict(legacy)) == (
        NativeShortWriterProvenanceState.LEGACY_UNATTRIBUTED
    )
    assert classify_persisted_native_short_writer_provenance(
        {"provenance_contract_version": ""}
    ) == NativeShortWriterProvenanceState.INVALID_PROVENANCE


def test_audit_counts_persisted_states_and_never_accepts_repository_code_as_ops() -> None:
    invalid = persisted_row(manual_provenance())
    invalid["trigger_ref"] = None
    rows = [persisted_row(chain_provenance()), {"provenance_contract_version": None}, invalid]
    assert summarize_writer_provenance(rows) == (1, 1, 1, True)


def test_migration_is_forward_only_nullable_and_has_no_backfill() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE native_short_materializer_run_v1" in sql
    assert "provenance_contract_version VARCHAR(40) NULL" in sql
    for table in (
        "native_short_map_v1",
        "native_short_map_generation_event_v1",
        "native_short_map_lifecycle_event_v1",
        "native_short_map_scope_v1",
        "native_short_scope_support_event_v1",
        "native_short_scope_status_v1",
        "native_short_map_level_status_v1",
    ):
        assert f"ALTER TABLE {table}" in sql
    assert "writer_invocation_uuid CHAR(36) NULL" in sql
    assert sql.count("REFERENCES native_short_materializer_run_v1 (run_uuid)") == 7
    assert "UPDATE " not in sql.upper()
    assert "INSERT INTO" not in sql.upper()
    assert "DELETE FROM" not in sql.upper()
    assert PROVENANCE_CONTRACT_VERSION in sql


def test_contract_contains_no_ambient_attribution_fallback() -> None:
    source = Path("src/market_data/native_short_writer_provenance_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "systemctl",
        "INVOCATION_ID",
        "JOURNAL_STREAM",
        "getppid",
        "stat(",
        "getmtime",
    ):
        assert forbidden not in source
