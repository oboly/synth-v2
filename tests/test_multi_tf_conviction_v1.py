"""Issue #591: tests for the Multi-TF Conviction composition contract.

Every test injects synthetic HorizonEvidenceV1 fixtures. No DB, no broker,
no account state, no execution intent anywhere in this module.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.signal_engine import multi_tf_conviction_v1 as mtc

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _evidence(
    horizon: str,
    *,
    state: str = mtc.EVIDENCE_STATE_STRONG_POSITIVE,
    freshness: str = mtc.FRESHNESS_FRESH,
    replay_safe: bool = True,
    model_id: str = "test_model",
    model_version: str = "1.0",
    provenance: str = "test_fixture",
    confidence: float | None = 0.9,
    reason_codes: tuple[str, ...] = ("TEST_REASON",),
    asof_ts: datetime | None = NOW,
) -> mtc.HorizonEvidenceV1:
    return mtc.HorizonEvidenceV1(
        horizon=horizon,
        state=state,
        freshness=freshness,
        asof_ts=asof_ts,
        replay_safe=replay_safe,
        model_id=model_id,
        model_version=model_version,
        provenance=provenance,
        confidence=confidence,
        reason_codes=reason_codes,
    )


def _compose(
    *,
    long_state: str = mtc.EVIDENCE_STATE_STRONG_POSITIVE,
    mid_evidence: mtc.HorizonEvidenceV1 | None = None,
    short_evidence: mtc.HorizonEvidenceV1 | None = None,
    long_evidence: mtc.HorizonEvidenceV1 | None = None,
) -> mtc.MultiTFConvictionV1:
    return mtc.compose_multi_tf_conviction_v1(
        symbol="TESTASSET",
        generated_at_utc=NOW,
        long_evidence=long_evidence if long_evidence is not None else _evidence(mtc.HORIZON_LONG, state=long_state),
        mid_evidence=mid_evidence if mid_evidence is not None else _evidence(mtc.HORIZON_MID),
        short_evidence=short_evidence if short_evidence is not None else _evidence(mtc.HORIZON_SHORT),
    )


# --- 1. Three distinct simultaneous states ----------------------------------


def test_long_strong_mid_weak_short_weak_remains_three_distinct_states() -> None:
    result = _compose(
        long_evidence=_evidence(mtc.HORIZON_LONG, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE),
        mid_evidence=_evidence(mtc.HORIZON_MID, state=mtc.EVIDENCE_STATE_NEUTRAL),
        short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_NEGATIVE),
    )
    assert result.conviction_long.conviction_state == mtc.CONVICTION_STRONG
    assert result.conviction_mid.conviction_state == mtc.CONVICTION_WEAK
    assert result.conviction_short.conviction_state == mtc.CONVICTION_WEAK
    assert result.conviction_long.derived_state == mtc.CAPITAL_FLOOR_CORE_INTACT
    assert result.conviction_mid.derived_state == mtc.EXPOSURE_REDUCE
    assert result.conviction_short.derived_state == mtc.TIMING_UNFAVORABLE


# --- 2. SHORT deterioration cannot invalidate intact LONG -------------------


def test_short_deterioration_alone_does_not_change_long() -> None:
    baseline = _compose(short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_POSITIVE))
    deteriorated = _compose(short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_INVALIDATING))

    assert baseline.conviction_long == deteriorated.conviction_long
    assert deteriorated.conviction_short.conviction_state == mtc.CONVICTION_INVALIDATED
    assert deteriorated.conviction_long.conviction_state == mtc.CONVICTION_STRONG
    assert deteriorated.conviction_long.derived_state == mtc.CAPITAL_FLOOR_CORE_INTACT


# --- 3. MID deterioration changes only MID/exposure -------------------------


def test_mid_deterioration_changes_only_mid_semantics() -> None:
    baseline = _compose(mid_evidence=_evidence(mtc.HORIZON_MID, state=mtc.EVIDENCE_STATE_POSITIVE))
    deteriorated = _compose(mid_evidence=_evidence(mtc.HORIZON_MID, state=mtc.EVIDENCE_STATE_INVALIDATING))

    assert baseline.conviction_long == deteriorated.conviction_long
    assert baseline.conviction_short == deteriorated.conviction_short
    assert deteriorated.conviction_mid.conviction_state == mtc.CONVICTION_INVALIDATED
    assert deteriorated.conviction_mid.derived_state == mtc.EXPOSURE_SUPPRESS


# --- 4. SHORT recovery reopens timing without rebuilding LONG ---------------


def test_short_recovery_transitions_timing_upward_while_long_continuity_intact() -> None:
    weak = _compose(short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_NEGATIVE))
    recovered = _compose(short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE))

    assert weak.conviction_short.derived_state == mtc.TIMING_UNFAVORABLE
    assert recovered.conviction_short.derived_state == mtc.TIMING_FAVORABLE
    assert weak.conviction_long == recovered.conviction_long
    assert recovered.conviction_long.derived_state == mtc.CAPITAL_FLOOR_CORE_INTACT


# --- 5. LONG invalidation collapses only long-thesis/capital-floor ---------


def test_long_invalidation_collapses_only_long_semantics() -> None:
    result = _compose(
        long_evidence=_evidence(mtc.HORIZON_LONG, state=mtc.EVIDENCE_STATE_INVALIDATING),
        mid_evidence=_evidence(mtc.HORIZON_MID, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE),
        short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE),
    )
    assert result.conviction_long.conviction_state == mtc.CONVICTION_INVALIDATED
    assert result.conviction_long.derived_state == mtc.CAPITAL_FLOOR_CORE_COLLAPSED
    assert result.conviction_mid.conviction_state == mtc.CONVICTION_STRONG
    assert result.conviction_short.conviction_state == mtc.CONVICTION_STRONG
    assert result.conviction_mid.derived_state == mtc.EXPOSURE_EXPAND
    assert result.conviction_short.derived_state == mtc.TIMING_FAVORABLE


# --- 6. Stale input -> explicit stale/insufficient state --------------------


def test_stale_evidence_yields_explicit_insufficient_state() -> None:
    result = mtc.evaluate_horizon_conviction_v1(
        mtc.HORIZON_MID, _evidence(mtc.HORIZON_MID, freshness=mtc.FRESHNESS_STALE)
    )
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_STALE
    assert result.derived_state == mtc.EXPOSURE_UNKNOWN
    # Provenance/freshness detail must survive even in the fail-closed case.
    assert result.freshness == mtc.FRESHNESS_STALE
    assert result.model_id == "test_model"


def test_freshness_insufficient_data_yields_explicit_insufficient_state() -> None:
    result = mtc.evaluate_horizon_conviction_v1(
        mtc.HORIZON_SHORT, _evidence(mtc.HORIZON_SHORT, freshness=mtc.FRESHNESS_INSUFFICIENT_DATA)
    )
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_INSUFFICIENT_DATA


def test_unknown_freshness_yields_explicit_insufficient_state() -> None:
    result = mtc.evaluate_horizon_conviction_v1(
        mtc.HORIZON_LONG, _evidence(mtc.HORIZON_LONG, freshness=mtc.FRESHNESS_UNKNOWN)
    )
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_FRESHNESS_UNKNOWN


# --- 7. Missing input -> explicit insufficient state ------------------------


def test_missing_evidence_yields_explicit_insufficient_state() -> None:
    result = mtc.evaluate_horizon_conviction_v1(mtc.HORIZON_LONG, None)
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_MISSING
    assert result.derived_state == mtc.CAPITAL_FLOOR_UNKNOWN
    assert result.confidence is None
    assert result.model_id is None


# --- 8. Conflicting horizon evidence remains visible ------------------------


def test_conflicting_horizon_evidence_remains_visible_not_forced_to_consensus() -> None:
    result = _compose(
        long_evidence=_evidence(mtc.HORIZON_LONG, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE),
        short_evidence=_evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_INVALIDATING),
    )
    assert result.conviction_long.conviction_state == mtc.CONVICTION_STRONG
    assert result.conviction_short.conviction_state == mtc.CONVICTION_INVALIDATED
    # Both extremes coexist in the same output -- no consensus collapse.
    assert result.conviction_long.conviction_state != result.conviction_short.conviction_state


# --- 9. No opaque cross-horizon average -------------------------------------


def test_output_has_no_aggregate_or_average_field() -> None:
    result = _compose()
    field_names = {f for f in vars(result)}
    for forbidden in ("aggregate", "average", "overall", "score", "conviction_total"):
        assert not any(forbidden in name.lower() for name in field_names), field_names


# --- 10. Research-only / not-replay-safe upstream fails closed -------------


def test_research_only_evidence_fails_closed() -> None:
    result = mtc.evaluate_horizon_conviction_v1(
        mtc.HORIZON_MID,
        _evidence(mtc.HORIZON_MID, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE, replay_safe=False),
    )
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_NOT_REPLAY_SAFE


def test_missing_asof_ts_fails_closed_even_when_freshness_claims_fresh() -> None:
    result = mtc.evaluate_horizon_conviction_v1(
        mtc.HORIZON_LONG,
        _evidence(mtc.HORIZON_LONG, freshness=mtc.FRESHNESS_FRESH, asof_ts=None),
    )
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_ASOF_MISSING
    assert result.derived_state == mtc.CAPITAL_FLOOR_UNKNOWN


def test_horizon_mismatched_evidence_fails_closed() -> None:
    wrong_slot_evidence = _evidence(mtc.HORIZON_SHORT, state=mtc.EVIDENCE_STATE_STRONG_POSITIVE)
    result = mtc.evaluate_horizon_conviction_v1(mtc.HORIZON_LONG, wrong_slot_evidence)
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_HORIZON_MISMATCH


def test_unrecognized_evidence_state_fails_closed() -> None:
    result = mtc.evaluate_horizon_conviction_v1(
        mtc.HORIZON_SHORT, _evidence(mtc.HORIZON_SHORT, state="SOME_UNKNOWN_STATE")
    )
    assert result.conviction_state == mtc.CONVICTION_INSUFFICIENT_DATA
    assert result.reason_code == mtc.REASON_EVIDENCE_STATE_UNRECOGNIZED


# --- 11. Deterministic reason codes and provenance survive output ----------


def test_healthy_evidence_carries_deterministic_provenance() -> None:
    evidence = _evidence(
        mtc.HORIZON_LONG,
        state=mtc.EVIDENCE_STATE_STRONG_POSITIVE,
        model_id="long_thesis_model",
        model_version="2.3",
        provenance="canonical_owner_ref_123",
        confidence=0.77,
    )
    result = mtc.evaluate_horizon_conviction_v1(mtc.HORIZON_LONG, evidence)
    assert result.reason_code == mtc.REASON_OK
    assert result.model_id == "long_thesis_model"
    assert result.model_version == "2.3"
    assert result.provenance == "canonical_owner_ref_123"
    assert result.confidence == 0.77
    assert result.asof_ts == NOW
    assert result.evidence_reason_codes == ("TEST_REASON",)


def test_composition_is_deterministic_across_repeated_calls() -> None:
    first = _compose()
    second = _compose()
    assert first == second


def test_unknown_horizon_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        mtc.evaluate_horizon_conviction_v1("NOT_A_HORIZON", None)
