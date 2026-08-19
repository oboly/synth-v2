from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigError,
    StrategyBucketAccountConfigRevocationV1,
    StrategyBucketAccountConfigRowV1,
    resolve_strategy_bucket_account_config_v1,
)


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
ACCOUNT_A = 101
ACCOUNT_B = 202
BUCKET_A = "SHORT_TERM_ROTATION"
BUCKET_B = "MEDIUM_SWING"


def _row(**changes: object) -> StrategyBucketAccountConfigRowV1:
    values: dict[str, object] = dict(
        strategy_bucket_account_config_id=1,
        trading_account_id=ACCOUNT_A,
        strategy_bucket_id=BUCKET_A,
        config_version="1",
        is_enabled=True,
        risk_profile="MODERATE",
        max_position_amount_eur=None,
        max_bucket_amount_eur=None,
        max_asset_exposure_pct=None,
        max_open_positions=None,
        allow_new_entries=True,
        allow_reduce_reviews=True,
        effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
        source_provenance="manual_review",
    )
    values.update(changes)
    return StrategyBucketAccountConfigRowV1(**values)  # type: ignore[arg-type]


def _revocation(**changes: object) -> StrategyBucketAccountConfigRevocationV1:
    values: dict[str, object] = dict(
        strategy_bucket_account_config_revocation_id=1,
        strategy_bucket_account_config_id=1,
        trading_account_id=ACCOUNT_A,
        revocation_version="1",
        effective_ts_utc=NOW,
        actor="operator-v1",
        reason="superseded",
    )
    values.update(changes)
    return StrategyBucketAccountConfigRevocationV1(**values)  # type: ignore[arg-type]


def test_no_row_is_unresolved_and_fails_closed():
    with pytest.raises(StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED"):
        resolve_strategy_bucket_account_config_v1((), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW)


def test_row_for_another_account_does_not_resolve():
    with pytest.raises(StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED"):
        resolve_strategy_bucket_account_config_v1(
            (_row(trading_account_id=ACCOUNT_B),), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_row_for_another_bucket_does_not_resolve():
    with pytest.raises(StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED"):
        resolve_strategy_bucket_account_config_v1(
            (_row(strategy_bucket_id=BUCKET_B),), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_multi_account_isolation_resolves_independently():
    """Two accounts each configuring the same bucket resolve to their own
    distinct, isolated configuration -- proves #279's multi-account safety."""
    row_a = _row(
        strategy_bucket_account_config_id=1, trading_account_id=ACCOUNT_A,
        is_enabled=True, risk_profile="MODERATE",
    )
    row_b = _row(
        strategy_bucket_account_config_id=2, trading_account_id=ACCOUNT_B,
        is_enabled=False, risk_profile="CONSERVATIVE",
    )
    config_a = resolve_strategy_bucket_account_config_v1(
        (row_a, row_b), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
    )
    config_b = resolve_strategy_bucket_account_config_v1(
        (row_a, row_b), trading_account_id=ACCOUNT_B, strategy_bucket_id=BUCKET_A, at=NOW,
    )
    assert config_a.trading_account_id == ACCOUNT_A
    assert config_a.is_enabled is True
    assert config_a.risk_profile == "MODERATE"
    assert config_b.trading_account_id == ACCOUNT_B
    assert config_b.is_enabled is False
    assert config_b.risk_profile == "CONSERVATIVE"


def test_row_outside_effective_window_does_not_resolve():
    future = _row(effective_from_ts_utc=NOW + timedelta(days=1))
    with pytest.raises(StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED"):
        resolve_strategy_bucket_account_config_v1(
            (future,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_overlapping_active_rows_are_ambiguous_and_fail_closed():
    row_a = _row(strategy_bucket_account_config_id=1)
    row_b = _row(strategy_bucket_account_config_id=2)
    with pytest.raises(StrategyBucketAccountConfigError, match="AMBIGUOUS_STRATEGY_BUCKET_CONFIGURATION"):
        resolve_strategy_bucket_account_config_v1(
            (row_a, row_b), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_unsupported_config_version_fails_closed():
    row = _row(config_version="999")
    with pytest.raises(StrategyBucketAccountConfigError, match="UNSUPPORTED_STRATEGY_BUCKET_CONFIGURATION_VERSION"):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_malformed_effective_window_fails_closed():
    row = _row(effective_until_ts_utc=NOW - timedelta(days=2))
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_CONFIGURATION_WINDOW"):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_empty_risk_profile_fails_closed():
    row = _row(risk_profile="   ")
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_RISK_PROFILE"):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_empty_source_provenance_fails_closed():
    row = _row(source_provenance="  ")
    with pytest.raises(
        StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_CONFIGURATION_SOURCE_PROVENANCE",
    ):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_negative_max_position_amount_fails_closed():
    row = _row(max_position_amount_eur=Decimal("-1"))
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_MAX_POSITION_AMOUNT"):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_out_of_range_max_asset_exposure_pct_fails_closed():
    row = _row(max_asset_exposure_pct=Decimal("150"))
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_MAX_ASSET_EXPOSURE_PCT"):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_non_positive_max_open_positions_fails_closed():
    row = _row(max_open_positions=0)
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_MAX_OPEN_POSITIONS"):
        resolve_strategy_bucket_account_config_v1(
            (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_resolves_single_effective_row_to_typed_config():
    row = _row(
        is_enabled=True, risk_profile="AGGRESSIVE",
        max_position_amount_eur=Decimal("500"), max_bucket_amount_eur=Decimal("2000"),
        max_asset_exposure_pct=Decimal("25"), max_open_positions=3,
        allow_new_entries=True, allow_reduce_reviews=False,
    )
    config = resolve_strategy_bucket_account_config_v1(
        (row,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
    )
    assert config.trading_account_id == ACCOUNT_A
    assert config.strategy_bucket_id == BUCKET_A
    assert config.is_enabled is True
    assert config.risk_profile == "AGGRESSIVE"
    assert config.max_position_amount_eur == Decimal("500")
    assert config.max_bucket_amount_eur == Decimal("2000")
    assert config.max_asset_exposure_pct == Decimal("25")
    assert config.max_open_positions == 3
    assert config.allow_new_entries is True
    assert config.allow_reduce_reviews is False


def test_invalid_lookup_arguments_raise():
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_CONFIGURATION_LOOKUP"):
        resolve_strategy_bucket_account_config_v1((), trading_account_id=0, strategy_bucket_id=BUCKET_A, at=NOW)
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_CONFIGURATION_LOOKUP"):
        resolve_strategy_bucket_account_config_v1((), trading_account_id=ACCOUNT_A, strategy_bucket_id="  ", at=NOW)


# --- Revocation lifecycle -----------------------------------------------------


def test_open_ended_config_resolves_before_any_revocation():
    row = _row(effective_until_ts_utc=None)
    config = resolve_strategy_bucket_account_config_v1(
        (row,), (), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
    )
    assert config.is_enabled is True


def test_revocation_makes_config_inactive_at_and_after_its_effective_timestamp():
    row = _row(strategy_bucket_account_config_id=1, effective_until_ts_utc=None)
    revocation = _revocation(strategy_bucket_account_config_id=1, effective_ts_utc=NOW)
    with pytest.raises(StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED"):
        resolve_strategy_bucket_account_config_v1(
            (row,), (revocation,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )
    config = resolve_strategy_bucket_account_config_v1(
        (row,), (revocation,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW - timedelta(minutes=1),
    )
    assert config.is_enabled is True


def test_successor_becomes_sole_effective_config_after_revocation():
    old = _row(
        strategy_bucket_account_config_id=1,
        effective_from_ts_utc=NOW - timedelta(days=10),
        effective_until_ts_utc=None,
        risk_profile="CONSERVATIVE",
    )
    new = _row(
        strategy_bucket_account_config_id=2,
        effective_from_ts_utc=NOW,
        effective_until_ts_utc=None,
        risk_profile="AGGRESSIVE",
    )
    revocation = _revocation(strategy_bucket_account_config_id=1, effective_ts_utc=NOW)
    config = resolve_strategy_bucket_account_config_v1(
        (old, new), (revocation,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
    )
    assert config.risk_profile == "AGGRESSIVE"


def test_revocation_referencing_unknown_config_fails_closed():
    row = _row(strategy_bucket_account_config_id=1)
    dangling = _revocation(strategy_bucket_account_config_id=999)
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_CONFIGURATION_REVOCATION"):
        resolve_strategy_bucket_account_config_v1(
            (row,), (dangling,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )


def test_revocation_account_mismatch_fails_closed():
    row_a = _row(strategy_bucket_account_config_id=1, trading_account_id=ACCOUNT_A)
    row_b = _row(strategy_bucket_account_config_id=2, trading_account_id=ACCOUNT_B)
    mismatched = StrategyBucketAccountConfigRevocationV1(
        strategy_bucket_account_config_revocation_id=1,
        strategy_bucket_account_config_id=2,
        trading_account_id=ACCOUNT_A,
        revocation_version="1",
        effective_ts_utc=NOW,
        actor="operator-v1",
        reason="corrupt",
    )
    with pytest.raises(
        StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_CONFIGURATION_REVOCATION_ACCOUNT_MISMATCH",
    ):
        resolve_strategy_bucket_account_config_v1(
            (row_a, row_b), (mismatched,), trading_account_id=ACCOUNT_A, strategy_bucket_id=BUCKET_A, at=NOW,
        )
