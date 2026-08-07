from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationOperationType as OperationType,
    NativeShortScopeAdministrationResult,
    NativeShortScopeAdministrationResultClass as ResultClass,
    NativeShortScopeAdministrationResultCode as ResultCode,
    NativeShortScopeAdministrationTriggerType,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    AdministrationTransactionOutcome,
    CommitState,
    OperationAction,
    TransactionMode,
)
from src.market_data import (
    native_short_scope_administration_rollout_v1 as rollout,
)
from src.market_data.native_short_multi_asset_audit_v1 import (
    ROLLOUT_STATUS_ALREADY_SUPPORTED,
    ROLLOUT_STATUS_BLOCKED,
    ROLLOUT_STATUS_READY,
    ROLLOUT_STATUS_SKIPPED_NOT_READY,
)
from src.market_data.native_short_scope_administration_rollout_v1 import (
    APPROVED_ROLLOUT_UNIVERSE_V1,
    RolloutConfigurationError,
    RolloutSymbolEntry,
    build_request_for_entry,
    deterministic_operation_uuid,
    execute_rollout,
    plan_rollout,
    resolve_rollout_entries,
)


_BTC_ENTRY = RolloutSymbolEntry(
    symbol="BTC",
    operation_type=OperationType.ADOPT_LEGACY_SCOPE,
    approval_reference="docs/todo/example.md",
    note="adopt legacy",
)
_SOL_ENTRY = RolloutSymbolEntry(
    symbol="SOL",
    operation_type=OperationType.PROMOTE_SCOPE,
    approval_reference="docs/todo/example.md",
    note="promote new",
)
_TEST_UNIVERSE = (_BTC_ENTRY, _SOL_ENTRY)


def _outcome(
    *,
    write: bool,
    result_class: ResultClass,
    result_code: ResultCode,
    action: OperationAction = OperationAction.ADOPT,
    persisted: bool | None = True,
    scope_admin_operation_id: int | None = 1,
) -> AdministrationTransactionOutcome:
    result = NativeShortScopeAdministrationResult(
        result_class=result_class,
        result_code=result_code,
        support_generation_before=None,
        support_generation_after=1,
    )
    return AdministrationTransactionOutcome(
        mode=TransactionMode.WRITE if write else TransactionMode.DRY_RUN,
        write=write,
        persisted=persisted,
        commit_state=CommitState.COMMITTED if persisted else CommitState.ROLLED_BACK,
        operation_type=str(OperationType.ADOPT_LEGACY_SCOPE),
        operation_uuid="00000000-0000-0000-0000-000000000000",
        request_digest="digest",
        scope_key={
            "venue": "bitvavo",
            "symbol": "BTC",
            "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT",
            "primary_interval": "4h",
            "supporting_interval": "1h",
        },
        action=action,
        result=result,
        scope_admin_operation_id=scope_admin_operation_id,
        advisory_lock_name="nssa1:deadbeef",
        current_state={},
        detail="test",
    )


def _build_request(entry: RolloutSymbolEntry):
    return build_request_for_entry(
        entry,
        actor_type=NativeShortScopeAdministrationActorType.HUMAN_OPERATOR,
        actor_id="tester",
        trigger_type=NativeShortScopeAdministrationTriggerType.MANUAL_CLI,
        request_source="pytest",
        reason="test rollout",
        requested_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        repository_sha="a" * 40,
        schema_version="native_short_scope_administration_v1",
        metadata={},
    )


# --------------------------------------------------------------------------- #
# resolve_rollout_entries                                                     #
# --------------------------------------------------------------------------- #


def test_resolve_rollout_entries_defaults_to_complete_universe() -> None:
    assert resolve_rollout_entries(None, universe=_TEST_UNIVERSE) == _TEST_UNIVERSE


def test_resolve_rollout_entries_filters_and_preserves_universe_order() -> None:
    result = resolve_rollout_entries(["SOL", "BTC"], universe=_TEST_UNIVERSE)
    assert result == (_BTC_ENTRY, _SOL_ENTRY)


def test_resolve_rollout_entries_rejects_unapproved_symbol() -> None:
    with pytest.raises(RolloutConfigurationError):
        resolve_rollout_entries(["ETH"], universe=_TEST_UNIVERSE)


def test_resolve_rollout_entries_dedupes_repeated_requests() -> None:
    result = resolve_rollout_entries(["BTC", "BTC"], universe=_TEST_UNIVERSE)
    assert result == (_BTC_ENTRY,)


# --------------------------------------------------------------------------- #
# deterministic_operation_uuid                                                #
# --------------------------------------------------------------------------- #


def test_deterministic_operation_uuid_is_stable_across_calls() -> None:
    assert deterministic_operation_uuid(_BTC_ENTRY) == deterministic_operation_uuid(
        _BTC_ENTRY
    )


def test_deterministic_operation_uuid_differs_by_symbol_and_operation() -> None:
    uuids = {
        deterministic_operation_uuid(_BTC_ENTRY),
        deterministic_operation_uuid(_SOL_ENTRY),
    }
    assert len(uuids) == 2


# --------------------------------------------------------------------------- #
# build_request_for_entry                                                     #
# --------------------------------------------------------------------------- #


def test_build_request_for_entry_binds_symbol_and_operation() -> None:
    request = _build_request(_BTC_ENTRY)
    assert request.scope_key.symbol == "BTC"
    assert request.operation_type == OperationType.ADOPT_LEGACY_SCOPE
    assert request.provenance.operation_uuid == deterministic_operation_uuid(_BTC_ENTRY)
    assert request.canonical_metadata["rollout_entry_note"] == _BTC_ENTRY.note


def test_build_request_for_entry_is_deterministic_for_identical_inputs() -> None:
    first = _build_request(_BTC_ENTRY)
    second = _build_request(_BTC_ENTRY)
    assert first.request_digest == second.request_digest


# --------------------------------------------------------------------------- #
# plan_rollout / execute_rollout orchestration                                #
# --------------------------------------------------------------------------- #


def test_execute_rollout_processes_all_entries_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_execute(conn: Any, request: Any, *, authorization: Any) -> AdministrationTransactionOutcome:
        calls.append(request.scope_key.symbol)
        return _outcome(
            write=True,
            result_class=ResultClass.SUCCESS,
            result_code=ResultCode.ADOPTED_LEGACY_SCOPE,
        )

    monkeypatch.setattr(rollout, "execute_scope_administration", fake_execute)

    outcome = execute_rollout(
        object(),
        _TEST_UNIVERSE,
        build_request=_build_request,
        authorization=object(),
    )

    assert calls == ["BTC", "SOL"]
    assert outcome.stopped_early is False
    assert outcome.remaining_symbols == ()
    assert outcome.as_json_dict()["all_succeeded"] is True
    assert [c.symbol for c in outcome.completed] == ["BTC", "SOL"]


def test_execute_rollout_continues_past_rejected_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_execute(conn: Any, request: Any, *, authorization: Any) -> AdministrationTransactionOutcome:
        calls.append(request.scope_key.symbol)
        if request.scope_key.symbol == "BTC":
            return _outcome(
                write=True,
                result_class=ResultClass.SUCCESS,
                result_code=ResultCode.ADOPTED_LEGACY_SCOPE,
            )
        return _outcome(
            write=True,
            result_class=ResultClass.BLOCKED,
            result_code=ResultCode.GLOBAL_BLOCKERS_ACTIVE,
            action=OperationAction.REJECT,
            persisted=False,
        )

    monkeypatch.setattr(rollout, "execute_scope_administration", fake_execute)

    outcome = execute_rollout(
        object(),
        _TEST_UNIVERSE,
        build_request=_build_request,
        authorization=object(),
    )

    assert calls == ["BTC", "SOL"]
    # Continue-always: nothing is ever left unattempted.
    assert outcome.stopped_early is False
    assert outcome.remaining_symbols == ()
    # The first failure is still reported honestly for operator triage.
    assert "GLOBAL_BLOCKERS_ACTIVE" in outcome.stop_reason
    assert outcome.as_json_dict()["all_succeeded"] is False
    by_symbol = {c.symbol: c for c in outcome.completed}
    assert by_symbol["BTC"].status == ROLLOUT_STATUS_READY
    assert by_symbol["SOL"].status == ROLLOUT_STATUS_BLOCKED


def test_execute_rollout_middle_failure_does_not_block_unrelated_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The literal Issue #276 acceptance criterion: one rejected/unready scope
    must not block unrelated qualified scopes. Three entries, the middle one
    fails; the first and last must both still be attempted and both still
    succeed."""
    three_entries = (
        _BTC_ENTRY,
        RolloutSymbolEntry(
            symbol="SOL",
            operation_type=OperationType.PROMOTE_SCOPE,
            approval_reference="docs/todo/example.md",
            note="promote",
        ),
        RolloutSymbolEntry(
            symbol="ETH",
            operation_type=OperationType.PROMOTE_SCOPE,
            approval_reference="docs/todo/example.md",
            note="promote",
        ),
    )

    calls: list[str] = []

    def fake_execute(conn: Any, request: Any, *, authorization: Any) -> AdministrationTransactionOutcome:
        calls.append(request.scope_key.symbol)
        if request.scope_key.symbol == "SOL":
            return _outcome(
                write=True,
                result_class=ResultClass.CORRUPT_STATE,
                result_code=ResultCode.PARTIAL_SCOPE_STATE,
                action=OperationAction.REJECT,
                persisted=False,
            )
        return _outcome(
            write=True,
            result_class=ResultClass.SUCCESS,
            result_code=ResultCode.ADOPTED_LEGACY_SCOPE,
        )

    monkeypatch.setattr(rollout, "execute_scope_administration", fake_execute)

    outcome = execute_rollout(
        object(),
        three_entries,
        build_request=_build_request,
        authorization=object(),
    )

    # Every entry attempted, in checked-in order, despite the middle failure.
    assert calls == ["BTC", "SOL", "ETH"]
    assert [c.symbol for c in outcome.completed] == ["BTC", "SOL", "ETH"]
    assert outcome.remaining_symbols == ()
    assert outcome.stopped_early is False

    by_symbol = {c.symbol: c for c in outcome.completed}
    # The unrelated scopes still succeeded; only the failing one did not.
    assert by_symbol["BTC"].succeeded is True
    assert by_symbol["ETH"].succeeded is True
    assert by_symbol["SOL"].succeeded is False
    assert by_symbol["SOL"].status == ROLLOUT_STATUS_SKIPPED_NOT_READY
    assert outcome.as_json_dict()["completed_symbols"] == ["BTC", "ETH"]
    assert outcome.as_json_dict()["all_succeeded"] is False


def test_execute_rollout_continues_past_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected exception on one scope is recorded on that scope only and
    never prevents a later unrelated scope from being attempted."""
    calls: list[str] = []

    def fake_execute(conn: Any, request: Any, *, authorization: Any) -> AdministrationTransactionOutcome:
        calls.append(request.scope_key.symbol)
        if request.scope_key.symbol == "BTC":
            raise RuntimeError("boom")
        return _outcome(
            write=True,
            result_class=ResultClass.SUCCESS,
            result_code=ResultCode.PROMOTED_NEW_SCOPE,
        )

    monkeypatch.setattr(rollout, "execute_scope_administration", fake_execute)

    outcome = execute_rollout(
        object(),
        _TEST_UNIVERSE,
        build_request=_build_request,
        authorization=object(),
    )

    assert calls == ["BTC", "SOL"]
    assert outcome.stopped_early is False
    assert outcome.remaining_symbols == ()

    by_symbol = {c.symbol: c for c in outcome.completed}
    assert by_symbol["BTC"].error is not None
    assert "boom" in by_symbol["BTC"].error
    assert by_symbol["BTC"].status == ROLLOUT_STATUS_SKIPPED_NOT_READY
    # The unrelated scope after the crash still ran and still succeeded.
    assert by_symbol["SOL"].succeeded is True
    assert by_symbol["SOL"].status == ROLLOUT_STATUS_READY


def test_rollout_scope_outcome_status_vocabulary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each administration result class maps onto exactly one canonical
    per-scope rollout label, and the label is exported in as_json_dict()."""
    cases = (
        (ResultClass.SUCCESS, ResultCode.ADOPTED_LEGACY_SCOPE, True, ROLLOUT_STATUS_READY),
        (
            ResultClass.IDEMPOTENT_SUCCESS,
            ResultCode.OPERATION_ALREADY_COMPLETED,
            True,
            ROLLOUT_STATUS_ALREADY_SUPPORTED,
        ),
        (
            ResultClass.BLOCKED,
            ResultCode.GLOBAL_BLOCKERS_ACTIVE,
            False,
            ROLLOUT_STATUS_BLOCKED,
        ),
        (
            ResultClass.CONFLICT,
            ResultCode.OPERATION_METADATA_MISMATCH,
            False,
            ROLLOUT_STATUS_SKIPPED_NOT_READY,
        ),
        (
            ResultClass.CORRUPT_STATE,
            ResultCode.PARTIAL_SCOPE_STATE,
            False,
            ROLLOUT_STATUS_SKIPPED_NOT_READY,
        ),
        (
            ResultClass.RETRYABLE,
            ResultCode.DEADLOCK,
            False,
            ROLLOUT_STATUS_SKIPPED_NOT_READY,
        ),
    )
    for result_class, result_code, persisted, expected in cases:
        scope_outcome = rollout.RolloutScopeOutcome(
            symbol="BTC",
            operation_type=str(OperationType.ADOPT_LEGACY_SCOPE),
            outcome=_outcome(
                write=True,
                result_class=result_class,
                result_code=result_code,
                action=OperationAction.ADOPT if persisted else OperationAction.REJECT,
                persisted=persisted,
            ),
            error=None,
        )
        assert scope_outcome.status == expected
        assert scope_outcome.as_json_dict()["rollout_status"] == expected

    # An unexpected exception (no outcome at all) is never reported as ready.
    crashed = rollout.RolloutScopeOutcome(
        symbol="BTC",
        operation_type=str(OperationType.ADOPT_LEGACY_SCOPE),
        outcome=None,
        error="RuntimeError: boom",
    )
    assert crashed.status == ROLLOUT_STATUS_SKIPPED_NOT_READY
    assert crashed.as_json_dict()["rollout_status"] == ROLLOUT_STATUS_SKIPPED_NOT_READY


def test_execute_rollout_is_idempotent_on_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rerun over an already-completed entry replays as
    OPERATION_ALREADY_COMPLETED (IDEMPOTENT_SUCCESS) and continues, proving
    restartability without any orchestrator-side run-state."""

    def fake_execute(conn: Any, request: Any, *, authorization: Any) -> AdministrationTransactionOutcome:
        return _outcome(
            write=True,
            result_class=ResultClass.IDEMPOTENT_SUCCESS,
            result_code=ResultCode.OPERATION_ALREADY_COMPLETED,
        )

    monkeypatch.setattr(rollout, "execute_scope_administration", fake_execute)

    outcome = execute_rollout(
        object(),
        _TEST_UNIVERSE,
        build_request=_build_request,
        authorization=object(),
    )

    assert outcome.stopped_early is False
    assert outcome.as_json_dict()["all_succeeded"] is True


def test_plan_rollout_delegates_to_plan_scope_administration(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_plan(conn: Any, request: Any) -> AdministrationTransactionOutcome:
        return _outcome(
            write=False,
            result_class=ResultClass.SUCCESS,
            result_code=ResultCode.ADOPTED_LEGACY_SCOPE,
            persisted=False,
        )

    monkeypatch.setattr(rollout, "plan_scope_administration", fake_plan)

    outcome = plan_rollout(object(), _TEST_UNIVERSE, build_request=_build_request)

    assert outcome.mode == "DRY_RUN"
    assert outcome.as_json_dict()["all_succeeded"] is True


# --------------------------------------------------------------------------- #
# Checked-in APPROVED_ROLLOUT_UNIVERSE_V1                                     #
# --------------------------------------------------------------------------- #


def test_approved_universe_is_btc_adopt_then_eth_then_xrp_promote() -> None:
    assert [(e.symbol, str(e.operation_type)) for e in APPROVED_ROLLOUT_UNIVERSE_V1] == [
        ("BTC", str(OperationType.ADOPT_LEGACY_SCOPE)),
        ("ETH", str(OperationType.PROMOTE_SCOPE)),
        ("XRP", str(OperationType.PROMOTE_SCOPE)),
    ]


def test_approved_universe_does_not_include_sol() -> None:
    """SOL was promoted directly through the single-scope CLI, outside this
    orchestrator; re-adding it here would be rejected (its scope already
    exists) and would needlessly stop a sequential run before ETH/XRP."""
    assert "SOL" not in {e.symbol for e in APPROVED_ROLLOUT_UNIVERSE_V1}


def test_approved_universe_entries_are_unique_symbols() -> None:
    symbols = [e.symbol for e in APPROVED_ROLLOUT_UNIVERSE_V1]
    assert len(symbols) == len(set(symbols))


@pytest.fixture(autouse=True)
def _authorize_test_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: None,
    )


def test_execute_rollout_real_universe_promotes_eth_then_xrp_end_to_end() -> None:
    """The real, unmodified transaction layer, the real checked-in approved
    universe (selected to its two PROMOTE_SCOPE entries -- BTC's
    ADOPT_LEGACY_SCOPE path has its own separate, already-covered legacy-row
    fixtures and is not this change's concern), and the real (accepted)
    ETH/XRP bootstrap-manifest entries -- no evaluator is mocked. Proves the
    generic orchestrator, unchanged since BTC-only, correctly sequences a
    real multi-symbol PROMOTE_SCOPE rollout with each scope's own
    independent evidence and no cross-scope leakage."""
    from tests.test_native_short_scope_administration_promotion_bootstrap_wiring_v1 import (
        _accepted_writer_evidence_row,
    )
    from tests.test_native_short_scope_administration_transaction_v1 import (
        _AUTH,
        _FakeConn,
        _FakeState,
    )

    state = _FakeState()
    state.writer_runs.append(_accepted_writer_evidence_row())
    conn = _FakeConn(state)

    outcome = execute_rollout(
        conn,
        resolve_rollout_entries(["ETH", "XRP"], universe=APPROVED_ROLLOUT_UNIVERSE_V1),
        build_request=_build_request,
        authorization=_AUTH,
    )

    assert outcome.as_json_dict()["all_succeeded"] is True
    assert [c.symbol for c in outcome.completed] == ["ETH", "XRP"]
    assert {op["symbol"] for op in conn.state.operations} == {"ETH", "XRP"}


def test_execute_rollout_real_universe_is_restartable_after_partial_completion() -> None:
    """A rerun that only re-selects the not-yet-attempted remainder (as the
    documented restart procedure would) still succeeds, and re-selecting an
    already-completed entry alongside it replays idempotently -- proving
    restartability with no orchestrator-side run-state file."""
    from tests.test_native_short_scope_administration_promotion_bootstrap_wiring_v1 import (
        _accepted_writer_evidence_row,
    )
    from tests.test_native_short_scope_administration_transaction_v1 import (
        _AUTH,
        _FakeConn,
        _FakeState,
    )

    state = _FakeState()
    state.writer_runs.append(_accepted_writer_evidence_row())
    conn = _FakeConn(state)
    subset = resolve_rollout_entries(["ETH", "XRP"], universe=APPROVED_ROLLOUT_UNIVERSE_V1)

    first_pass = execute_rollout(
        conn,
        resolve_rollout_entries(["ETH"], universe=APPROVED_ROLLOUT_UNIVERSE_V1),
        build_request=_build_request,
        authorization=_AUTH,
    )
    assert first_pass.as_json_dict()["all_succeeded"] is True

    second_pass = execute_rollout(
        conn,
        subset,
        build_request=_build_request,
        authorization=_AUTH,
    )
    assert second_pass.as_json_dict()["all_succeeded"] is True
    assert [c.symbol for c in second_pass.completed] == ["ETH", "XRP"]
    assert {op["symbol"] for op in conn.state.operations} == {"ETH", "XRP"}
