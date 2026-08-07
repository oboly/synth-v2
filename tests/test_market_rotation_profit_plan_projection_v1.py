from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.reporting.market_rotation_profit_plan_projection_v1 import (
    build_rotation_projection,
    get_market_projection,
    market_projection_to_json_dict,
    to_json_dict,
    unavailable_projection,
)


NOW = datetime(2026, 7, 12, 20, 30, tzinfo=UTC)


def _header(**overrides):
    row = {
        "pressure_snapshot_id": 44,
        "as_of_ts_utc": datetime(2026, 7, 12, 20, 0),
        "venue": "bitvavo",
        "model_version": "1.0",
        "eligible_asset_count": 3,
        "excluded_missing_pair_count": 1,
        "positive_count": 2,
        "neutral_count": 0,
        "negative_count": 1,
        "market_score": 38.5,
        "positive_breadth_ratio": 2 / 3,
        "negative_breadth_ratio": 1 / 3,
        "acceleration_state": "ACCELERATING_IN",
        "concentration_state": "SELECTIVE",
        "confirmation_state": "CONFIRMED",
        "market_direction": "ROTATION_IN",
        "evidence_light_count": 4,
    }
    row.update(overrides)
    return row


def _row(asset_id: int, market: str, score: float, phase: str):
    return {
        "asset_id": asset_id,
        "market": market,
        "score_total": score,
        "pressure_state": "ROTATION_IN" if score > 0 else "ROTATION_OUT",
        "phase_state": phase,
        "raw_return_24h_pct": score / 10,
        "raw_return_7d_pct": score / 4,
        "raw_relative_volume_24h": 1.8,
        "raw_relative_volume_7d": 1.3,
        "score_acceleration": score / 2,
        "score_persistence": score / 3,
    }


def _rows():
    return [
        _row(1, "AERO-EUR", 78.0, "ACCELERATING_IN"),
        _row(2, "XLM-EUR", 61.0, "SUSTAINED_IN"),
        _row(3, "APT-EUR", -72.0, "ACCELERATING_OUT"),
    ]


def test_fresh_aggregate_snapshot_available_and_verbatim():
    projection = build_rotation_projection(_header(), _rows(), now_utc=NOW)
    assert projection.available is True
    assert projection.freshness == "FRESH"
    assert projection.evidence_light_count == 4
    assert projection.aggregate_direction == "ROTATION_IN"
    assert projection.aggregate_score == 38.5
    assert projection.positive_breadth_ratio == 2 / 3
    assert projection.negative_breadth_ratio == 1 / 3
    assert projection.acceleration_state == "ACCELERATING_IN"
    assert projection.confirmation_state == "CONFIRMED"
    assert projection.concentration_state == "SELECTIVE"
    assert projection.eligible_asset_count == 3
    assert projection.venue == "bitvavo"


def test_per_market_matching_by_canonical_market_identity():
    projection = build_rotation_projection(_header(), _rows(), now_utc=NOW)
    aero = get_market_projection(projection, "AERO-EUR")
    assert aero.available is True
    assert aero.market == "AERO-EUR"
    assert aero.score_total == 78.0
    assert aero.pressure_state == "ROTATION_IN"
    # Case-sensitive / exact match only -- no fuzzy matching.
    lower_case_lookup = get_market_projection(projection, "aero-eur")
    assert lower_case_lookup.available is False
    assert lower_case_lookup.reason == "NO_ROTATION_ROW"


def test_market_absent_from_observation_rows_gets_explicit_no_row_entry():
    projection = build_rotation_projection(_header(), _rows(), now_utc=NOW)
    missing = get_market_projection(projection, "NOTLISTED-EUR")
    assert missing.available is False
    assert missing.reason == "NO_ROTATION_ROW"
    assert missing.score_total is None
    assert missing.pressure_state is None
    # Freshness is inherited from the aggregate snapshot, not fabricated.
    assert missing.freshness == projection.freshness


def test_missing_aggregate_snapshot_is_unavailable_no_exception():
    projection = build_rotation_projection(None, [], now_utc=NOW)
    assert projection.available is False
    assert projection.freshness == "DATA_UNAVAILABLE"
    assert projection.reason == "NO_PRESSURE_SNAPSHOT"
    assert projection.per_market == {}
    # Any lookup against an unavailable projection must still degrade cleanly.
    lookup = get_market_projection(projection, "AERO-EUR")
    assert lookup.available is False


def test_stale_snapshot_is_degraded_not_silently_fresh():
    projection = build_rotation_projection(
        _header(as_of_ts_utc=datetime(2026, 7, 12, 17, 0)),
        _rows(),
        now_utc=NOW,
    )
    assert projection.freshness == "STALE"
    # Values remain present (issue requires "values still present but marked stale").
    assert projection.aggregate_score == 38.5
    assert projection.evidence_light_count == 4
    aero = get_market_projection(projection, "AERO-EUR")
    assert aero.freshness == "STALE"
    assert aero.score_total == 78.0


def test_future_timestamp_snapshot_fails_closed():
    projection = build_rotation_projection(
        _header(as_of_ts_utc=datetime(2026, 7, 12, 21, 0)),
        _rows(),
        now_utc=NOW,
    )
    assert projection.freshness == "FUTURE_TIMESTAMP"
    # Degraded, never raised, never fabricated beyond persisted values.
    assert projection.aggregate_direction == "ROTATION_IN"


def test_invalid_direction_in_raw_row_fails_closed_never_raises():
    projection = build_rotation_projection(
        _header(market_direction="NOT_A_REAL_DIRECTION"),
        _rows(),
        now_utc=NOW,
    )
    assert projection.available is False
    assert projection.aggregate_direction is None
    assert projection.reason is not None


def test_invalid_light_count_in_raw_row_fails_closed_never_raises():
    projection = build_rotation_projection(
        _header(evidence_light_count=9),
        _rows(),
        now_utc=NOW,
    )
    assert projection.available is False
    assert projection.evidence_light_count is None


def test_evidence_light_count_never_recomputed_across_fixture_values():
    for lights in (0, 1, 2, 3, 4, 5):
        projection = build_rotation_projection(_header(evidence_light_count=lights), _rows(), now_utc=NOW)
        assert projection.evidence_light_count == lights
        payload = to_json_dict(projection)
        assert payload["evidence_light_count"] == lights


def test_projection_reused_across_two_account_profiles_without_cross_contamination():
    projection = build_rotation_projection(_header(), _rows(), now_utc=NOW)

    profile_a_markets = ["AERO-EUR", "XLM-EUR"]
    profile_b_markets = ["APT-EUR", "NOTLISTED-EUR"]

    profile_a_results = {m: get_market_projection(projection, m) for m in profile_a_markets}
    profile_b_results = {m: get_market_projection(projection, m) for m in profile_b_markets}

    assert profile_a_results["AERO-EUR"].score_total == 78.0
    assert profile_a_results["XLM-EUR"].score_total == 61.0
    assert profile_b_results["APT-EUR"].score_total == -72.0
    assert profile_b_results["NOTLISTED-EUR"].available is False

    # Independent lookups do not mutate shared projection state.
    assert projection.per_market["AERO-EUR"].score_total == 78.0
    assert projection.per_market["APT-EUR"].score_total == -72.0

    # No account-specific field anywhere on the dataclasses.
    import dataclasses

    for field in dataclasses.fields(projection):
        assert "account" not in field.name
        assert "profile" not in field.name
    for mp in projection.per_market.values():
        for field in dataclasses.fields(mp):
            assert "account" not in field.name
            assert "profile" not in field.name


def test_json_contract_top_level_keys():
    projection = build_rotation_projection(_header(), _rows(), now_utc=NOW)
    payload = to_json_dict(projection)
    for key in (
        "available",
        "freshness",
        "source_ts_utc",
        "aggregate_direction",
        "aggregate_score",
        "evidence_light_count",
        "per_market",
    ):
        assert key in payload
    assert "AERO-EUR" in payload["per_market"]
    aero_json = payload["per_market"]["AERO-EUR"]
    assert aero_json["market"] == "AERO-EUR"
    assert aero_json["score_total"] == 78.0
    assert aero_json["source_ts_utc"] == "2026-07-12T20:00:00Z"


def test_unavailable_projection_json_stub():
    projection = unavailable_projection()
    payload = to_json_dict(projection)
    assert payload["available"] is False
    assert payload["freshness"] == "DATA_UNAVAILABLE"
    assert payload["per_market"] == {}


def test_market_projection_to_json_dict_shape():
    projection = build_rotation_projection(_header(), _rows(), now_utc=NOW)
    mp = get_market_projection(projection, "AERO-EUR")
    payload = market_projection_to_json_dict(mp)
    assert payload["market"] == "AERO-EUR"
    assert payload["available"] is True
    assert payload["top_in"] is True
    assert payload["top_out"] is False


def test_no_forbidden_imports_in_pure_module():
    source = Path("src/reporting/market_rotation_profit_plan_projection_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"bitvavo_client", "decision_gate", "execution_planner", "executor", "pymysql", "db"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for term in forbidden:
                assert term not in module
