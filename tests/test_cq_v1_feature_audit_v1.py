from pathlib import Path

import yaml


REGISTRY = Path("config/research/cq_v1_feature_audit_v1.yaml")


def load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def test_registry_is_phase_2b_research_only_and_does_not_freeze_weights() -> None:
    registry = load_registry()
    assert registry["registry_name"] == "cq_v1_feature_audit_v1"
    assert registry["registry_version"] == "1.0.0"
    assert registry["issue"] == 568
    assert registry["phase"] == "2B"
    assert registry["research_only"] is True
    assert registry["market_only"] is True
    assert registry["account_agnostic"] is True
    assert registry["production_ranking_changes"] == 0
    assert registry["model_weights_frozen"] is False
    assert registry["model_scoring_enabled"] is False


def test_point_in_time_rules_fail_closed() -> None:
    pit = load_registry()["point_in_time_rule"]
    assert pit == {
        "feature_asof_must_be_lte_observation_asof": True,
        "latest_eligible_row_at_or_before_observation_asof": True,
        "future_rows_forbidden": True,
        "current_truth_fallback_forbidden": True,
        "same_venue_required": True,
    }


def test_market_rotation_pressure_sources_and_semantics_are_frozen() -> None:
    family = load_registry()["eligible_feature_families"]["market_rotation_pressure"]
    assert family["status"] == "ELIGIBLE"
    assert family["owner_capability"] == "market_rotation_pressure"
    assert family["aggregate_table"] == "market_rotation_pressure_snapshot_v1"
    assert family["per_asset_table"] == "market_rotation_pressure_observation_v1"
    assert family["time_field"] == "as_of_ts_utc"
    assert family["version_field"] == "model_version"
    assert family["frozen_model_version"] == "1.0"
    assert "positive_breadth_ratio" in family["aggregate_fields"]
    assert "negative_breadth_ratio" in family["aggregate_fields"]
    assert "score_total" in family["per_asset_fields"]
    assert "raw_market_relative_pct" in family["per_asset_fields"]
    assert any("not BTC-relative" in note for note in family["notes"])


def test_market_rotation_pressure_per_asset_venue_is_inherited_from_parent_snapshot() -> None:
    family = load_registry()["eligible_feature_families"]["market_rotation_pressure"]
    venue = family["venue_contract"]
    assert venue["observation_venue_must_equal_cq_observation_venue"] is True
    assert venue["aggregate_venue_field"] == "venue"
    assert (
        venue["per_asset_venue_resolution"]
        == "pressure_snapshot_id -> market_rotation_pressure_snapshot_v1.pressure_snapshot_id -> venue"
    )
    assert venue["cross_venue_fallback_forbidden"] is True
    assert "pressure_snapshot_id" in family["per_asset_identity_fields"]
    assert "venue" not in family["per_asset_identity_fields"]


def test_sector_rotation_requires_frozen_venue_window_model_and_pit_primary_membership() -> None:
    family = load_registry()["eligible_feature_families"]["sector_rotation"]
    assert family["status"] == "ELIGIBLE_WITH_PIT_MEMBERSHIP"
    assert family["owner_capability"] == "sector_rotation_snapshot"
    assert family["table"] == "sector_rotation_snapshot"
    assert family["time_field"] == "asof_ts_utc"
    assert family["version_field"] == "model_version"
    assert family["frozen_model_version"] == "sector-rotation-v1.0.0"
    assert family["frozen_window_code"] == "4h"
    assert family["venue_contract"] == {
        "source_venue_must_equal_cq_observation_venue": True,
        "venue_field": "venue",
        "cross_venue_fallback_forbidden": True,
    }
    assert family["source_identity_fields"] == [
        "sector_code",
        "venue",
        "window_code",
        "asof_ts_utc",
        "model_version",
        "input_hash",
        "taxonomy_versions_json",
    ]
    membership = family["membership_contract"]
    assert membership["table"] == "asset_cluster_membership"
    assert membership["valid_from_field"] == "valid_from_ts_utc"
    assert membership["valid_to_field"] == "valid_to_ts_utc"
    assert membership["membership_type_field"] == "membership_type"
    assert membership["required_membership_type"] == "PRIMARY"
    assert membership["tie_break"] == ["membership_weight DESC", "sector_code ASC"]
    assert "relative_strength_vs_btc" in family["fields"]
    assert "relative_strength_vs_eth" in family["fields"]
    assert any("sector-level only" in note for note in family["notes"])


def test_unowned_or_unpromoted_candidates_remain_excluded() -> None:
    excluded = load_registry()["excluded_candidate_families"]
    assert excluded["btc_structure_regime"]["status"] == "UNAVAILABLE_NO_CANONICAL_REPLAYABLE_OWNER"
    assert excluded["symbol_relative_vs_btc"]["status"] == "UNAVAILABLE_NO_CANONICAL_REPLAYABLE_OWNER"
    assert excluded["eth_btc_relative_context"]["status"] == "UNAVAILABLE_NO_CANONICAL_REPLAYABLE_OWNER"
    assert excluded["breathline_context"]["status"] == "EXCLUDED_RESEARCH_HYPOTHESIS_NOT_PROMOTED"
    assert excluded["rotation_flip_research"]["status"] == "EXCLUDED_RESEARCH_FINDING_NOT_CANONICAL"


def test_freeze_boundary_requires_version_bump_for_new_features() -> None:
    freeze = load_registry()["freeze_boundary"]
    assert freeze["this_registry_freezes_eligibility_and_field_contract_only"] is True
    assert freeze["feature_transformations_frozen"] is False
    assert freeze["feature_weights_frozen"] is False
    assert freeze["cq_v1_formula_frozen"] is False
    assert freeze["outcome_holdout_may_not_be_inspected_to_choose_additional_features"] is True
    assert freeze["newly_discovered_features_require_new_registry_version"] is True
    assert freeze["source_model_versions_frozen"] is True
    assert freeze["source_identity_dimensions_frozen"] is True


def test_safety_contract_has_no_live_authority() -> None:
    safety = load_registry()["safety"]
    assert safety == {
        "research_only": 1,
        "market_only": 1,
        "account_awareness": 0,
        "production_ranking_changes": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor_changes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "runtime_activation": 0,
    }
