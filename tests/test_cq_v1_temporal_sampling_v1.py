from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.research.cq_v1_temporal_sampling_v1 import (
    derive_asofs,
    load_contract,
    split_asofs,
    split_for_asof,
)


def test_frozen_sampling_contract_derives_exact_45_daily_asofs() -> None:
    contract = load_contract()
    asofs = derive_asofs(contract)
    assert len(asofs) == 45
    assert asofs[0].isoformat() == "2026-07-18T00:00:00+00:00"
    assert asofs[-1].isoformat() == "2026-08-31T00:00:00+00:00"
    assert all(b > a for a, b in zip(asofs, asofs[1:]))
    assert all((b - a) == timedelta(days=1) for a, b in zip(asofs, asofs[1:]))


def test_frozen_split_counts_and_boundaries_are_exact() -> None:
    contract = load_contract()
    grouped = split_asofs(contract)
    assert len(grouped["discovery"]) == 27
    assert len(grouped["validation"]) == 9
    assert len(grouped["holdout"]) == 9
    assert grouped["discovery"][0].isoformat() == "2026-07-18T00:00:00+00:00"
    assert grouped["discovery"][-1].isoformat() == "2026-08-13T00:00:00+00:00"
    assert grouped["validation"][0].isoformat() == "2026-08-14T00:00:00+00:00"
    assert grouped["validation"][-1].isoformat() == "2026-08-22T00:00:00+00:00"
    assert grouped["holdout"][0].isoformat() == "2026-08-23T00:00:00+00:00"
    assert grouped["holdout"][-1].isoformat() == "2026-08-31T00:00:00+00:00"


def test_every_asof_belongs_to_exactly_one_chronological_split() -> None:
    contract = load_contract()
    asofs = derive_asofs(contract)
    labels = [split_for_asof(asof, contract) for asof in asofs]
    assert labels == ["discovery"] * 27 + ["validation"] * 9 + ["holdout"] * 9
    grouped = split_asofs(contract)
    discovery = set(grouped["discovery"])
    validation = set(grouped["validation"])
    holdout = set(grouped["holdout"])
    assert discovery.isdisjoint(validation)
    assert discovery.isdisjoint(holdout)
    assert validation.isdisjoint(holdout)


def test_split_rejects_off_cadence_and_naive_timestamps() -> None:
    contract = load_contract()
    off_cadence = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="not a frozen temporal sample"):
        split_for_asof(off_cadence, contract)

    naive = datetime(2026, 8, 14, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        split_for_asof(naive, contract)


def test_contract_preserves_fail_closed_historical_semantics() -> None:
    contract = load_contract()
    pit = contract["pit_rules"]
    assert pit["current_latest_fallback"] == "FORBIDDEN"
    assert pit["future_feature_truth"] == "FORBIDDEN"
    assert pit["missingness"] == "PRESERVE_EXPLICITLY"
    assert pit["imputation"] == "FORBIDDEN"
    assert pit["weight_renormalization_on_missing"] == "FORBIDDEN"
    assert pit["sector_context"] == "UNAVAILABLE_HISTORICAL_MEMBERSHIP"
    assert pit["sector_current_membership_substitution"] == "FORBIDDEN"
    assert pit["ppp_history"] == "UNAVAILABLE_UNLESS_CANONICAL_PIT_ARTIFACT_SUPPLIED"
    assert pit["later_candles"] == "LABELS_ONLY"


def test_frozen_model_family_identity_is_unchanged() -> None:
    contract = load_contract()
    frozen = contract["frozen_model_family"]
    assert frozen["model_family_version"] == "1.0.0"
    assert frozen["coverage_artifact_sha256"] == (
        "f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d"
    )
    assert frozen["candidate_ids"] == [
        "cq_v1_mrp_balanced_v1",
        "cq_v1_mrp_anchor_v1",
    ]


def test_holdout_is_marked_untouched_and_safety_forbids_outcome_reads() -> None:
    contract = load_contract()
    assert contract["outcomes_inspected_before_freeze"] is False
    assert contract["chronological_split"]["holdout"]["untouched_until_final_evaluation"] is True
    assert contract["safety"]["outcomes_read"] == 0
    assert contract["safety"]["model_retuning"] == 0
    assert contract["artifact_policy"]["historical_shadow_backfill"] == "FORBIDDEN"
