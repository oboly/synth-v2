from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import ast
import inspect

import pytest

from src.entry_policy.automatic_buy_candidate_v1 import (
    ACTION_ENTER,
    ACTION_RE_ENTER,
    FORBIDDEN_FIELD_SUBSTRINGS,
    REASON_ENTRY_ZONE_REACHED,
    REASON_INVALID_CONTEXT,
    REASON_INVALID_POLICY_CONFIG,
    REASON_INVALID_TIMESTAMP,
    REASON_NO_ENTRY_CONDITION,
    REASON_RE_ENTRY_ZONE_REACHED,
    REASON_SETUP_CONTEXT_STALE,
    REASON_SETUP_NOT_READY,
    STATE_CANDIDATE,
    STATE_NO_ACTION,
    STATE_NON_ACTIONABLE,
    AutomaticBuyCandidateV1,
    AutomaticBuyEvaluationV1,
    AutomaticBuyPolicyConfigV1,
    AutomaticBuySetupContextV1,
    evaluate_automatic_buy_candidate_v1,
    validate_no_account_or_broker_fields,
)


NOW = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)

CANDIDATE_DATACLASSES = (
    AutomaticBuySetupContextV1,
    AutomaticBuyPolicyConfigV1,
    AutomaticBuyCandidateV1,
    AutomaticBuyEvaluationV1,
)

# Literal terms Issue #399 explicitly forbids in the Phase 1 BUY candidate.
ISSUE_399_FORBIDDEN_TERMS = (
    "trading_account_id",
    "balance",
    "wallet",
    "allocation",
    "permitted_quantity",
    "position_size",
    "credential",
    "broker",
)


def _setup(**changes: object) -> AutomaticBuySetupContextV1:
    values: dict[str, object] = dict(
        venue="bitvavo", asset_id=9, market="SOL-EUR",
        strategy_id="expansion_rotation", strategy_version="1",
        setup_id="native-long:SOL:2026-08-15", setup_ready=True,
        current_price=Decimal("150"),
        entry_zone_low=Decimal("145"), entry_zone_high=Decimal("155"),
        re_entry_zone_low=Decimal("130"), re_entry_zone_high=Decimal("140"),
        evidence_id="native-map-level:701", observed_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticBuySetupContextV1(**values)  # type: ignore[arg-type]


def _evaluate(**changes: object):
    setup_context = changes.pop("setup_context", _setup())
    return evaluate_automatic_buy_candidate_v1(
        setup_context=setup_context, evaluation_ts_utc=NOW, **changes
    )


def test_setup_not_ready_is_no_action() -> None:
    result = _evaluate(setup_context=_setup(setup_ready=False))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NO_ACTION, REASON_SETUP_NOT_READY, None)


def test_ready_setup_with_price_outside_all_zones_is_no_action() -> None:
    result = _evaluate(setup_context=_setup(current_price=Decimal("200")))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NO_ACTION, REASON_NO_ENTRY_CONDITION, None)


def test_price_in_entry_zone_is_deterministic_enter_candidate_with_provenance() -> None:
    result = _evaluate(setup_context=_setup(current_price=Decimal("150")))
    assert result.state == STATE_CANDIDATE
    assert result.candidate is not None
    assert result.candidate.candidate_action == ACTION_ENTER
    assert result.candidate.reason_code == REASON_ENTRY_ZONE_REACHED
    assert result.candidate.evidence_id == "native-map-level:701"
    assert result.candidate.setup_id == "native-long:SOL:2026-08-15"
    assert result.candidate.strategy_id == "expansion_rotation"
    assert result.candidate.strategy_version == "1"
    assert result.candidate.venue == "bitvavo"
    assert result.candidate.market == "SOL-EUR"
    assert result.candidate.observed_ts_utc == NOW
    assert _evaluate(setup_context=_setup(current_price=Decimal("150"))) == result


def test_price_in_re_entry_zone_is_re_enter_candidate() -> None:
    result = _evaluate(setup_context=_setup(current_price=Decimal("135")))
    assert result.candidate is not None
    assert result.candidate.candidate_action == ACTION_RE_ENTER
    assert result.candidate.reason_code == REASON_RE_ENTRY_ZONE_REACHED


def test_stale_setup_context_is_non_actionable() -> None:
    result = _evaluate(setup_context=_setup(observed_ts_utc=NOW - timedelta(minutes=16)))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_SETUP_CONTEXT_STALE, None)


def test_missing_identity_or_evidence_is_non_actionable() -> None:
    for changes in (
        {"venue": ""},
        {"market": ""},
        {"strategy_id": ""},
        {"strategy_version": ""},
        {"setup_id": ""},
        {"evidence_id": ""},
        {"asset_id": 0},
    ):
        result = _evaluate(setup_context=_setup(**changes))
        assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None), changes


def test_invalid_price_or_zone_is_non_actionable() -> None:
    for changes in (
        {"current_price": Decimal("0")},
        {"current_price": Decimal("-1")},
        {"entry_zone_low": Decimal("160"), "entry_zone_high": Decimal("150")},
        {"entry_zone_low": Decimal("-1")},
        {"re_entry_zone_high": Decimal("0")},
    ):
        result = _evaluate(setup_context=_setup(**changes))
        assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None), changes


def test_naive_timestamps_are_rejected_as_non_actionable() -> None:
    result = _evaluate(setup_context=_setup(observed_ts_utc=NOW.replace(tzinfo=None)))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP, None)


def test_invalid_policy_config_fails_closed() -> None:
    result = _evaluate(config=AutomaticBuyPolicyConfigV1(max_setup_context_age_seconds=-1))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_INVALID_POLICY_CONFIG, None)


def test_missing_entry_and_re_entry_zones_is_no_action_not_error() -> None:
    result = _evaluate(setup_context=_setup(
        entry_zone_low=None, entry_zone_high=None,
        re_entry_zone_low=None, re_entry_zone_high=None,
    ))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NO_ACTION, REASON_NO_ENTRY_CONDITION, None)


def test_module_has_no_decision_gate_bypass_or_execution_dependencies() -> None:
    import src.entry_policy.automatic_buy_candidate_v1 as module

    tree = ast.parse(inspect.getsource(module))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = ("decision_gate", "execution_planner", "executor", "bitvavo", "broker", "manual_execution")
    assert not any(term in imported for imported in imports for term in forbidden)
    result = _evaluate(setup_context=_setup(current_price=Decimal("150")))
    assert result.candidate is not None
    assert not hasattr(result.candidate, "quantity_base")
    assert not hasattr(result.candidate, "broker_payload")
    assert not hasattr(result.candidate, "trading_account_id")


def test_entry_policy_package_has_no_decision_gate_dependency() -> None:
    import src.entry_policy as package

    tree = ast.parse(inspect.getsource(package))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any("decision_gate" in imported for imported in imports)


def test_candidate_and_context_have_no_account_or_broker_fields() -> None:
    for dataclass_type in CANDIDATE_DATACLASSES:
        field_names = {field.name.lower() for field in fields(dataclass_type)}
        for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
            assert not any(forbidden in name for name in field_names), (
                f"{dataclass_type.__name__} must not bind a field containing {forbidden!r}"
            )
        for forbidden in ISSUE_399_FORBIDDEN_TERMS:
            assert not any(forbidden in name for name in field_names), (
                f"{dataclass_type.__name__} must not bind a field containing {forbidden!r}"
            )


def test_module_level_validation_already_passed_for_all_candidate_dataclasses() -> None:
    # This is a no-op assertion in the sense that the module already ran this
    # check at import time (and import would have failed otherwise); calling
    # it again here documents and locks in the account-agnosticism guarantee
    # independent of import-time side effects.
    validate_no_account_or_broker_fields(*CANDIDATE_DATACLASSES)


def test_construction_with_forbidden_field_is_rejected() -> None:
    @dataclass(frozen=True)
    class _BadCandidateWithAccountField:
        trading_account_id: int
        venue: str

    with pytest.raises(ValueError):
        validate_no_account_or_broker_fields(_BadCandidateWithAccountField)

    @dataclass(frozen=True)
    class _BadCandidateWithBalanceField:
        wallet_balance_eur: str

    with pytest.raises(ValueError):
        validate_no_account_or_broker_fields(_BadCandidateWithBalanceField)

    @dataclass(frozen=True)
    class _BadCandidateWithBrokerField:
        broker_credential_ref: str

    with pytest.raises(ValueError):
        validate_no_account_or_broker_fields(_BadCandidateWithBrokerField)


def test_validate_rejects_non_dataclass() -> None:
    with pytest.raises(TypeError):
        validate_no_account_or_broker_fields(int)
