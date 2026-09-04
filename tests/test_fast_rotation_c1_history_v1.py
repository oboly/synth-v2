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
        "cohort_size": 100,
        "relative_return_unit": Decimal("-0.250000"),
        "signed_flow_unit": Decimal("0.100000"),
        "relative_acceleration_unit": Decimal("-0.050000"),
        "rotation_score": Decimal("-6.666667"),
        "data_quality": "COMPLETE",
        "reason": "OK",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_frozen_replay_source_is_exact_current_source():
    assert history.verify_frozen_replay_source() == history.FROZEN_REPLAY_SOURCE_SHA256


def test_materialize_preserves_negative_score_without_sign_flip():
    row = history.materialize_observation(candidate_result(), market="TEST-EUR")
    assert row.rotation_score == Decimal("-6.666667")
    assert row.relative_return_unit == Decimal("-0.250000")
    assert row.candidate_id == "C1"
    assert row.effective_horizon == "VERY_SHORT"
    assert row.frozen_final_holdout_fingerprint == history.FROZEN_FINAL_HOLDOUT_FINGERPRINT


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
        history.materialize_observation(candidate_result(**{field: bad_value}), market="TEST-EUR")


def test_materialize_complete_requires_all_numeric_components():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observation(
            candidate_result(relative_acceleration_unit=None),
            market="TEST-EUR",
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
    )
    assert row.rotation_score is None
    assert row.freshness_state == "INSUFFICIENT_DATA"
    assert row.data_quality == "INSUFFICIENT_DATA"
    assert row.reason_code == "MISSING_OR_DEGENERATE_COMPONENT"


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
        )


def test_materialize_batch_requires_canonical_market_identity():
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observations([candidate_result()], market_by_asset={})


def test_materialize_batch_rejects_duplicate_logical_rows():
    result = candidate_result()
    with pytest.raises(history.C1PersistenceContractError):
        history.materialize_observations(
            [result, result],
            market_by_asset={42: "TEST-EUR"},
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
    observation = history.materialize_observation(candidate_result(), market="TEST-EUR")
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
    sql = conn.cursor_obj.executions[0][0]
    assert "ON DUPLICATE KEY UPDATE c1_observation_id=c1_observation_id" in sql


def test_persist_rolls_back_on_error(monkeypatch):
    def require_authorization(_authorization, _capability):
        return None

    import src.operations.writer_capability_authorization_v1 as auth_module

    monkeypatch.setattr(auth_module, "require_writer_mutation_authorization", require_authorization)
    observation = history.materialize_observation(candidate_result(), market="TEST-EUR")

    class FailingCursor(FakeCursor):
        def execute(self, sql, params):
            raise RuntimeError("db failure")

    conn = FakeConnection([])
    conn.cursor_obj = FailingCursor([])

    with pytest.raises(RuntimeError):
        history.persist_observations(conn, [observation], authorization="token")
    assert conn.commits == 0
    assert conn.rollbacks == 1
