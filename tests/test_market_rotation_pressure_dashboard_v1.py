from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.reporting.market_rotation_pressure_dashboard_v1 import (
    PRESSURE_SCALE_MAX,
    PRESSURE_SCALE_MIN,
    build_dashboard,
    classify_freshness,
    dashboard_to_json_dict,
    render_dashboard_html,
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


def test_classify_freshness_fresh():
    assert classify_freshness(datetime(2026, 7, 12, 20, 0), NOW) == "FRESH"


def test_classify_freshness_stale():
    assert classify_freshness(datetime(2026, 7, 12, 17, 0), NOW) == "STALE"


def test_classify_freshness_future_timestamp():
    assert classify_freshness(datetime(2026, 7, 12, 21, 0), NOW) == "FUTURE_TIMESTAMP"


def test_classify_freshness_custom_threshold():
    assert classify_freshness(
        datetime(2026, 7, 12, 20, 0),
        NOW,
        stale_after=timedelta(minutes=20),
    ) == "STALE"


def test_build_dashboard_available():
    dashboard = build_dashboard(_header(), _rows(), now_utc=NOW)
    assert dashboard.status == "AVAILABLE"
    assert dashboard.freshness_state == "FRESH"
    assert dashboard.header is not None
    assert dashboard.header.evidence_light_count == 4
    assert len(dashboard.rows) == 3


def test_build_dashboard_no_snapshot_fails_closed():
    dashboard = build_dashboard(None, [], now_utc=NOW)
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "NO_PRESSURE_SNAPSHOT"
    assert dashboard.header is None


def test_build_dashboard_observation_count_mismatch_fails_closed():
    dashboard = build_dashboard(
        _header(eligible_asset_count=4, positive_count=3, neutral_count=0, negative_count=1),
        _rows(),
        now_utc=NOW,
    )
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert (dashboard.reason or "").startswith("OBSERVATION_COUNT_MISMATCH")


def test_build_dashboard_negative_composition_count_fails_closed():
    dashboard = build_dashboard(
        _header(positive_count=4, neutral_count=0, negative_count=-1),
        _rows(),
        now_utc=NOW,
    )
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.header is None
    assert (dashboard.reason or "").startswith("INVALID_PRESSURE_SNAPSHOT:composition counts")
    assert "<div class='composition-band'" not in render_dashboard_html(dashboard)


def test_build_dashboard_composition_count_total_mismatch_fails_closed():
    dashboard = build_dashboard(
        _header(positive_count=1, neutral_count=1, negative_count=0),
        _rows(),
        now_utc=NOW,
    )
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.header is None
    assert (dashboard.reason or "").startswith(
        "INVALID_PRESSURE_SNAPSHOT:composition count total"
    )
    assert "<div class='composition-band'" not in render_dashboard_html(dashboard)


def test_build_dashboard_stale_is_degraded_not_available():
    dashboard = build_dashboard(
        _header(as_of_ts_utc=datetime(2026, 7, 12, 17, 0)),
        _rows(),
        now_utc=NOW,
    )
    assert dashboard.status == "DEGRADED"
    assert dashboard.freshness_state == "STALE"


def test_render_dashboard_has_exact_active_light_count():
    dashboard = build_dashboard(_header(evidence_light_count=4), _rows(), now_utc=NOW)
    rendered = render_dashboard_html(dashboard)
    assert rendered.count("light active light-in") == 4
    assert "4 of 5 evidence lights" in rendered


def test_render_dashboard_shows_persisted_observation_rows_without_local_ranking():
    rendered = render_dashboard_html(build_dashboard(_header(), _rows(), now_utc=NOW))
    assert "AERO-EUR" in rendered
    assert "XLM-EUR" in rendered
    assert "APT-EUR" in rendered
    assert "Top rotation in" not in rendered


def test_render_dashboard_leads_with_fixed_pressure_scale_and_secondary_direction():
    rendered = render_dashboard_html(build_dashboard(_header(market_score=38.5), _rows(), now_utc=NOW))
    assert PRESSURE_SCALE_MIN == -100.0
    assert PRESSURE_SCALE_MAX == 100.0
    assert "-100</span><span>0</span><span>+100" in rendered
    assert "+38.5" in rendered
    assert rendered.index("+38.5") < rendered.index("ROTATION IN")


def test_render_dashboard_supports_negative_pressure_and_persisted_composition():
    dashboard = build_dashboard(
        _header(
            market_score=-42.0,
            positive_count=1,
            neutral_count=1,
            negative_count=1,
            market_direction="ROTATION_OUT",
        ),
        _rows(),
        now_utc=NOW,
    )
    rendered = render_dashboard_html(dashboard)
    assert "-42.0" in rendered
    assert "OUT 33%" in rendered
    assert "MIXED 33%" in rendered
    assert "IN 33%" in rendered
    assert "composition-band" in rendered


def test_render_dashboard_composition_zero_counts_have_zero_width():
    rendered = render_dashboard_html(
        build_dashboard(
            _header(positive_count=3, neutral_count=0, negative_count=0),
            _rows(),
            now_utc=NOW,
        )
    )
    assert "composition-out composition-zero' style='flex:0 0 0.000000%;width:0.000000%'" in rendered
    assert "composition-mixed composition-zero' style='flex:0 0 0.000000%;width:0.000000%'" in rendered
    assert "composition-in' style='flex:0 0 100.000000%;width:100.000000%'" in rendered
    assert "IN 100%" in rendered


def test_render_dashboard_composition_asymmetric_widths_are_exact_percentages():
    rows = _rows() + [_row(4, "DOGE-EUR", 1.0, "MIXED")]
    rendered = render_dashboard_html(
        build_dashboard(
            _header(eligible_asset_count=4, positive_count=2, neutral_count=1, negative_count=1),
            rows,
            now_utc=NOW,
        )
    )
    assert "composition-out' style='flex:0 0 25.000000%;width:25.000000%'" in rendered
    assert "composition-mixed' style='flex:0 0 25.000000%;width:25.000000%'" in rendered
    assert "composition-in' style='flex:0 0 50.000000%;width:50.000000%'" in rendered


def test_render_dashboard_plots_only_persisted_history_with_fixed_zero_reference():
    history = [
        {"pressure_snapshot_id": 42, "as_of_ts_utc": datetime(2026, 7, 12, 18, 0), "market_score": -20.0},
        {"pressure_snapshot_id": 43, "as_of_ts_utc": datetime(2026, 7, 12, 19, 0), "market_score": 10.0},
        {"pressure_snapshot_id": 44, "as_of_ts_utc": datetime(2026, 7, 12, 20, 0), "market_score": 38.5},
    ]
    dashboard = build_dashboard(_header(), _rows(), now_utc=NOW, history_rows=history)
    rendered = render_dashboard_html(dashboard)
    assert len(dashboard.history) == 3
    assert "curve-zero" in rendered
    assert "pressure-curve" in rendered
    assert dashboard_to_json_dict(dashboard)["history"][0]["market_score"] == -20.0


def test_render_dashboard_escapes_market_and_phase_strings():
    rows = [_row(1, "<script>alert(1)</script>", 75.0, "<b>BAD</b>")]
    dashboard = build_dashboard(_header(eligible_asset_count=1, positive_count=1, negative_count=0), rows, now_utc=NOW)
    rendered = render_dashboard_html(dashboard)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<b>BAD</b>" not in rendered
    assert "&lt;b&gt;BAD&lt;/b&gt;" in rendered


def test_render_unavailable_page_contains_reason():
    rendered = render_dashboard_html(build_dashboard(None, [], now_utc=NOW))
    assert "DATA UNAVAILABLE" in rendered
    assert "NO_PRESSURE_SNAPSHOT" in rendered


def test_json_payload_exposes_safety_and_raw_rows():
    payload = dashboard_to_json_dict(build_dashboard(_header(), _rows(), now_utc=NOW))
    assert payload["status"] == "AVAILABLE"
    assert payload["header"]["market_direction"] == "ROTATION_IN"
    assert payload["header"]["as_of_ts_utc"].endswith("Z")
    assert payload["rows"][0]["market"] == "AERO-EUR"
    assert payload["safety"]["broker_writes"] == 0
    assert payload["safety"]["decision_gate"] == "none"


def test_market_writer_wrapper_has_no_reporting_ownership():
    text = Path("scripts/run_market_rotation_pressure_once.sh").read_text(encoding="utf-8")
    assert "run_market_rotation_history_v1" in text
    assert "run_market_rotation_pressure_v1" in text
    assert "run_market_rotation_pressure_dashboard_v1" not in text
    assert "reporting=none dashboard_publish=none" in text


def test_odroid_dashboard_wrapper_is_read_only():
    text = Path("scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh").read_text(encoding="utf-8")
    assert "run_market_rotation_pressure_dashboard_v1" in text
    assert "--write-db" not in text
    assert "market_data_writes=0 pressure_writes=0" in text


def test_dashboard_runner_history_is_read_only_and_bounded():
    text = Path("src/reporting/run_market_rotation_pressure_dashboard_v1.py").read_text(encoding="utf-8")
    assert "def fetch_pressure_history" in text
    assert "FROM market_rotation_pressure_snapshot_v1" in text
    assert "HISTORY_LIMIT = 168" in text
    assert "INSERT " not in text
    assert "UPDATE " not in text
