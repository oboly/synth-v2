from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.features import fast_rotation_c1_history_v1 as history


def candidate_result(**overrides):
    values = {
        "venue": "bitvavo",
        "asset_id": 42,
        "candidate_id": "C1",
        "model_id": history.ROTATION_MODEL,
        "model_version": history.ROTATION_MODEL_VERSION,
        "input_interval": history.INPUT_INTERVAL,
        "lookback_horizon": history.LOOKBACK_HORIZON,
        "effective_horizon": history.EFFECTIVE_HORIZON,
        "observed_lifecycle": history.OBSERVED_LIFECYCLE,
        "asof_ts": datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        "freshness": "FRESH",
        "provenance": history.SOURCE_PROVENANCE,
        "cohort_size": 80,
        "relative_return_unit": Decimal("-0.250000"),
        "signed_flow_unit": Decimal("0.100000"),
        "relative_acceleration_unit": Decimal("-0.050000"),
        "rotation_score": Decimal("-6.666667"),
        "data_quality": "COMPLETE",
        "reason": "OK",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def materialize(result=None, *, market="TEST-EUR", universe_size=100):
    return history.materialize_observation(
        candidate_result() if result is None else result,
        market=market,
        evaluated_universe_size=universe_size,
    )


def test_frozen_replay_source_is_exact_current_source():
    assert history.verify_frozen_replay_source() == history.FROZEN_REPLAY_SOURCE_SHA256


def test_materialize_preserves_negative_score_without_sign_flip():
    row = materialize()
    assert row.rotation_score == Decimal("-6.666667")
    assert row.relative_return_unit == Decimal("-0.250000")
    assert row.candidate_id == "C1"
    assert row.effective_horizon == "VERY_SHORT"
    assert row.frozen_final_holdout_fingerprint == history.FROZEN_FINAL_HOLDOUT_FINGERPRINT


def test_materialize_persists_immutable_universe_denominator_and_coverage():
    row = materialize(universe_size=100)
    assert row.cohort_size == 80
    assert row.evaluated_universe_size == 100
    assert row.coverage_ratio == Decimal("0.800000")


def test_materialize_coverage_is_not_reconstructed_from_future_universe():
    original = materialize(universe_size=100)
    later = history.materialize_observation(
        candidate_result(cohort_size=80),
        market="TEST-EUR",
        evaluated_universe_size=125,
    )
    assert original.coverage_ratio == Decimal("0.800000")
    assert later.coverage_ratio == Decimal("0.640000")


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("candidate_id", "C2"),
        ("model_id", "different_model"),
        ("model_version", "1.0.1-c1"),
        ("input_interval", "1h"),
        ("lookback_horizon", "15m"),
        ("effective_horizon", "SHORT"),
        ("observed_lifecycle", "15m"),
        ("provenance", "different_source"),
    ],
)
def test_materialize_rejects_semantic_drift(field, bad_value):
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observation(
            candidate_result(**{field: bad_value}),
            market="TEST-EUR",
            evaluated_universe_size=100,
        )


def test_materialize_complete_requires_all_numeric_components():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observation(
            candidate_result(relative_acceleration_unit=None),
            market="TEST-EUR",
            evaluated_universe_size=100,
        )


def test_materialize_rejects_zero_universe_denominator():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observation(
            candidate_result(),
            market="TEST-EUR",
            evaluated_universe_size=0,
        )


def test_materialize_rejects_cohort_larger_than_universe():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observation(
            candidate_result(cohort_size=101),
            market="TEST-EUR",
            evaluated_universe_size=100,
        )


def test_materialize_insufficient_data_keeps_explicit_quality_and_no_score():
    row = history.materialize_observation(
        candidate_result(
            freshness="INSUFFICIENT_DATA",
            data_quality="INSUFFICIENT_DATA",
            reason="MISSING_OR_DEGENERATE_COMPONENT",
            rotation_score=None,
            relative_return_unit=None,
            signed_flow_unit=None,
            relative_acceleration_unit=None,
        ),
        market="TEST-EUR",
        evaluated_universe_size=100,
    )
    assert row.rotation_score is None
    assert row.freshness_state == "INSUFFICIENT_DATA"
    assert row.data_quality == "INSUFFICIENT_DATA"
    assert row.reason_code == "MISSING_OR_DEGENERATE_COMPONENT"
    assert row.coverage_ratio == Decimal("0.800000")


def test_materialize_rejects_score_on_insufficient_data():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observation(
            candidate_result(
                freshness="INSUFFICIENT_DATA",
                data_quality="INSUFFICIENT_DATA",
                rotation_score=Decimal("1"),
                relative_return_unit=None,
                signed_flow_unit=None,
                relative_acceleration_unit=None,
            ),
            market="TEST-EUR",
            evaluated_universe_size=100,
        )


def test_materialize_batch_requires_canonical_market_identity():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observations(
            [candidate_result()],
            market_by_asset={},
            evaluated_universe_size=1,
        )


def test_materialize_batch_requires_result_count_equal_denominator():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observations(
            [candidate_result()],
            market_by_asset={42: "TEST-EUR"},
            evaluated_universe_size=2,
        )


def test_materialize_batch_rejects_duplicate_logical_rows():
    result = candidate_result()
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observations(
            [result, result],
            market_by_asset={42: "TEST-EUR"},
            evaluated_universe_size=2,
        )


class FakeCursor:
    def __init__(self, rowcounts):
        self.rowcounts = iter(rowcounts)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executions.append((sql, params))
        return next(self.rowcounts)


class FakeConnection:
    def __init__(self, rowcounts):
        self.cursor_obj = FakeCursor(rowcounts)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_persist_is_idempotent_and_authorization_guarded(monkeypatch):
    calls = []

    def require_authorization(authorization, capability):
        calls.append((authorization, capability))

    import src.operations.writer_capability_authorization_v1 as auth_module

    monkeypatch.setattr(auth_module, "require_writer_mutation_authorization", require_authorization)
    observation = materialize()
    conn = FakeConnection([1, 0])

    created, existing = history.persist_observations(
        conn,
        [observation, observation],
        authorization="token",
    )

    assert (created, existing) == (1, 1)
    assert calls == [("token", "fast_rotation_c1_history")]
    assert conn.commits == 1
    assert conn.rollbacks == 0
    sql, params = conn.cursor_obj.executions[0]
    assert "ON DUPLICATE KEY UPDATE c1_observation_id=c1_observation_id" in sql
    assert "evaluated_universe_size,coverage_ratio" in sql
    assert 100 in params
    assert "0.800000" in params


def test_persist_rolls_back_on_error(monkeypatch):
    def require_authorization(_authorization, _capability):
        return None

    import src.operations.writer_capability_authorization_v1 as auth_module

    monkeypatch.setattr(auth_module, "require_writer_mutation_authorization", require_authorization)
    observation = materialize()

    class FailingCursor(FakeCursor):
        def execute(self, sql, params):
            raise RuntimeError("db failure")

    conn = FakeConnection([])
    conn.cursor_obj = FailingCursor([])

    with pytest.raises(RuntimeError):
        history.persist_observations(conn, [observation], authorization="token")
    assert conn.commits == 0
    assert conn.rollbacks == 1
