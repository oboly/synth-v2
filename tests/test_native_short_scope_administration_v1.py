from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationOperationType,
    NativeShortScopeAdministrationProvenance,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationResult,
    NativeShortScopeAdministrationResultClass,
    NativeShortScopeAdministrationResultCode,
    NativeShortScopeAdministrationTriggerType,
    NativeShortScopeAdministrationValidationError,
)


MODULE_PATH = Path("src/market_data/native_short_scope_administration_v1.py")


def _key(**changes: str) -> NativeShortScopeAdministrationKey:
    values = {
        "venue": "bitvavo",
        "symbol": "BTC",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
    }
    values.update(changes)
    return NativeShortScopeAdministrationKey(**values)


def _provenance(
    **changes: object,
) -> NativeShortScopeAdministrationProvenance:
    values: dict[str, object] = {
        "operation_uuid": "00000000-0000-4000-8000-000000000001",
        "actor_type": NativeShortScopeAdministrationActorType.TEST,
        "actor_id": "native-short-scope-admin-test",
        "trigger_type": NativeShortScopeAdministrationTriggerType.TEST,
        "request_source": "tests/test_native_short_scope_administration_v1.py",
        "reason": "explicit test provenance",
        "requested_at_utc": datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        "repository_sha": "0" * 40,
        "schema_version": "native_short_scope_administration_v1",
    }
    values.update(changes)
    return NativeShortScopeAdministrationProvenance(**values)  # type: ignore[arg-type]


def _request(
    *,
    operation_type: NativeShortScopeAdministrationOperationType | str = (
        NativeShortScopeAdministrationOperationType.PROMOTE_SCOPE
    ),
    provenance: NativeShortScopeAdministrationProvenance | None = None,
    metadata: dict[str, object] | None = None,
) -> NativeShortScopeAdministrationRequest:
    return NativeShortScopeAdministrationRequest(
        operation_type=operation_type,
        scope_key=_key(),
        provenance=provenance or _provenance(),
        canonical_metadata=metadata or {"ticket": "scope-1", "guards": ["a", "b"]},
    )


def test_scope_key_normalizes_exact_canonical_identity() -> None:
    key = _key(
        venue="  BITVAVO ",
        symbol=" btc ",
        quote_currency=" eur ",
        fib_trading_horizon=" short ",
        primary_interval=" 4H ",
        supporting_interval=" 1H ",
    )
    assert key.as_dict() == {
        "venue": "bitvavo",
        "symbol": "BTC",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("venue", "kraken"),
        ("quote_currency", "USD"),
        ("fib_trading_horizon", "LONG"),
        ("primary_interval", "1d"),
        ("supporting_interval", "15m"),
        ("symbol", ""),
        ("symbol", "BTC,ETH"),
        ("symbol", "*"),
        ("symbol", "BTC?"),
        ("symbol", "BTC ETH"),
    ),
)
def test_scope_key_rejects_noncanonical_or_multi_symbol_input(
    field: str, value: str
) -> None:
    with pytest.raises(NativeShortScopeAdministrationValidationError):
        _key(**{field: value})


def test_operation_enum_is_closed() -> None:
    assert {item.value for item in NativeShortScopeAdministrationOperationType} == {
        "ADOPT_LEGACY_SCOPE",
        "PROMOTE_SCOPE",
        "REMOVE_SCOPE",
    }
    with pytest.raises(NativeShortScopeAdministrationValidationError, match="INVALID_ENUM"):
        _request(operation_type="PROMOTE_AND_MATERIALIZE")


def test_result_class_and_code_are_closed_and_consistent() -> None:
    result = NativeShortScopeAdministrationResult(
        result_class=NativeShortScopeAdministrationResultClass.SUCCESS,
        result_code=NativeShortScopeAdministrationResultCode.PROMOTED_NEW_SCOPE,
        support_generation_before=None,
        support_generation_after=1,
    )
    assert result.result_code == NativeShortScopeAdministrationResultCode.PROMOTED_NEW_SCOPE

    with pytest.raises(NativeShortScopeAdministrationValidationError, match="INVALID_ENUM"):
        replace(result, result_class="UNKNOWN")
    with pytest.raises(
        NativeShortScopeAdministrationValidationError,
        match="RESULT_CLASS_CODE_MISMATCH",
    ):
        replace(result, result_class=NativeShortScopeAdministrationResultClass.CONFLICT)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("operation_uuid", ""),
        ("actor_id", ""),
        ("request_source", ""),
        ("reason", ""),
        ("repository_sha", "unknown"),
        ("schema_version", ""),
    ),
)
def test_provenance_requires_explicit_valid_fields(field: str, value: object) -> None:
    with pytest.raises(NativeShortScopeAdministrationValidationError):
        _provenance(**{field: value})


def test_test_provenance_requires_both_explicit_test_enums() -> None:
    with pytest.raises(
        NativeShortScopeAdministrationValidationError,
        match="TEST_PROVENANCE_MUST_BE_EXPLICIT",
    ):
        _provenance(trigger_type=NativeShortScopeAdministrationTriggerType.MANUAL_CLI)


def test_metadata_serialization_and_digest_are_order_independent() -> None:
    first = _request(metadata={"z": 3, "nested": {"b": 2, "a": 1}})
    second = _request(metadata={"nested": {"a": 1, "b": 2}, "z": 3})
    assert first.canonical_metadata_json == second.canonical_metadata_json
    assert first.canonical_request_json() == second.canonical_request_json()
    assert first.request_digest == second.request_digest


def test_digest_changes_with_metadata_operation_actor_and_reason() -> None:
    baseline = _request()
    changed_metadata = _request(metadata={"ticket": "scope-2"})
    changed_operation = _request(
        operation_type=NativeShortScopeAdministrationOperationType.REMOVE_SCOPE
    )
    changed_actor = _request(provenance=_provenance(actor_id="another-test-actor"))
    changed_reason = _request(provenance=_provenance(reason="different explicit reason"))
    assert len(baseline.request_digest) == 64
    assert len(
        {
            baseline.request_digest,
            changed_metadata.request_digest,
            changed_operation.request_digest,
            changed_actor.request_digest,
            changed_reason.request_digest,
        }
    ) == 5


def test_metadata_rejects_noncanonical_json_values() -> None:
    with pytest.raises(
        NativeShortScopeAdministrationValidationError,
        match="METADATA_VALUE_UNSUPPORTED",
    ):
        _request(metadata={"ratio": 0.5})


def test_pure_contract_has_no_forbidden_layer_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "account",
        "wallet",
        "broker",
        "selection",
        "decision_gate",
        "execution_planner",
        "executor",
        "order",
        "reporting",
        "src.common.db",
    )
    for module_name in imported:
        assert not any(
            part in module_name for part in forbidden
        ), f"pure contract imports forbidden dependency: {module_name}"
