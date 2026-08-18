from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.reporting.market_rotation_pressure_dashboard_v1 import (
    DEFAULT_HISTORY_VIEWPORT,
    HISTORY_VIEWPORTS,
    PRESSURE_SCALE_MAX,
    PRESSURE_SCALE_MIN,
    RotationPressureHistoryPoint,
    build_dashboard,
    build_history_view,
    classify_freshness,
    dashboard_to_json_dict,
    detect_snapshot_cadence,
    format_cadence_label,
    format_history_window_label,
    render_dashboard_html,
    select_history_window,
)
from src.reporting.run_market_rotation_pressure_dashboard_v1 import (
    fetch_pressure_history,
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
    assert "HISTORY_FETCH_PAGE_SIZE = 2000" in text
    assert "INSERT " not in text
    assert "UPDATE " not in text


class _PagedHistoryCursor:
    """Fakes keyset-paginated reads: each ``fetchall`` returns the next
    pre-baked page, regardless of the SQL/params passed to ``execute`` (the
    stitching logic under test is exercised via the number/size of calls
    made, not by re-implementing keyset filtering here)."""

    def __init__(self, pages: list[list[dict[str, object]]]):
        self._pages = list(pages)
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.execute_calls.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        if self._pages:
            return self._pages.pop(0)
        return []


class _PagedHistoryConn:
    def __init__(self, cursor: _PagedHistoryCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_fetch_pressure_history_has_no_overall_row_cap():
    """Regression for the review-flagged truncation gap: the old
    implementation issued one query with a fixed LIMIT, so persisted history
    past that bound was silently dropped. The fix must keep reading pages
    until a short page proves exhaustion, however many pages that takes --
    proving there is no total-row cap, only a per-query page bound."""
    page_size = 4
    total_rows = 10 * page_size + 3  # deliberately not a multiple of page_size
    all_rows = [
        {
            "pressure_snapshot_id": index,
            "as_of_ts_utc": datetime(2026, 1, 1) + timedelta(hours=index),
            "market_score": float((index % 9) - 4),
        }
        for index in range(total_rows)
    ]
    pages = [all_rows[start : start + page_size] for start in range(0, total_rows, page_size)]
    cursor = _PagedHistoryCursor(pages)
    conn = _PagedHistoryConn(cursor)

    rows = fetch_pressure_history(conn, venue="bitvavo", model_version="1.0", page_size=page_size)

    assert len(rows) == total_rows
    assert [row["pressure_snapshot_id"] for row in rows] == list(range(total_rows))
    # More round-trips than any single fixed-LIMIT read: proves the fetch
    # kept paging instead of stopping at one bounded query.
    assert len(cursor.execute_calls) == len(pages)
    assert len(cursor.execute_calls) > 1
    first_sql, first_params = cursor.execute_calls[0]
    assert "as_of_ts_utc >" not in first_sql
    assert first_params == ("bitvavo", "1.0", page_size)
    second_sql, second_params = cursor.execute_calls[1]
    assert "as_of_ts_utc >" in second_sql or "as_of_ts_utc = %s AND pressure_snapshot_id >" in second_sql
    assert second_params[0:2] == ("bitvavo", "1.0")


def test_fetch_pressure_history_stops_after_exact_multiple_with_empty_probe():
    """When persisted history is an exact multiple of page_size, the loop
    must issue one more (empty) page fetch to confirm exhaustion rather than
    assuming completeness -- otherwise a coincidental multiple would look
    truncated the same way the old fixed-LIMIT bound did."""
    page_size = 5
    total_rows = page_size * 3
    all_rows = [
        {
            "pressure_snapshot_id": index,
            "as_of_ts_utc": datetime(2026, 2, 1) + timedelta(hours=index),
            "market_score": 0.0,
        }
        for index in range(total_rows)
    ]
    pages = [all_rows[start : start + page_size] for start in range(0, total_rows, page_size)]
    cursor = _PagedHistoryCursor(pages)
    conn = _PagedHistoryConn(cursor)

    rows = fetch_pressure_history(conn, venue="bitvavo", model_version="1.0", page_size=page_size)

    assert len(rows) == total_rows
    assert len(cursor.execute_calls) == len(pages) + 1


def _hourly_history(count: int, base: datetime = datetime(2026, 8, 10, 12, 0)):
    """``count`` persisted points at a strict 1h cadence, oldest first, with
    scores cycling through both signs so min/zero/max bounds are exercised."""
    return tuple(
        sorted(
            (
                RotationPressureHistoryPoint(
                    pressure_snapshot_id=count - hours_ago,
                    as_of_ts_utc=base - timedelta(hours=hours_ago),
                    market_score=float((hours_ago % 5) - 2),
                )
                for hours_ago in range(count)
            ),
            key=lambda point: point.as_of_ts_utc,
        )
    )


def test_select_history_window_24h_membership_is_exact():
    history = _hourly_history(24 * 40)
    window = select_history_window(history, "24h")
    assert len(window) == 25
    anchor = history[-1].as_of_ts_utc
    assert all(point.as_of_ts_utc >= anchor - timedelta(hours=24) for point in window)
    assert window[0].as_of_ts_utc == anchor - timedelta(hours=24)
    assert window[-1] == history[-1]


def test_select_history_window_7d_membership_is_exact():
    history = _hourly_history(24 * 40)
    window = select_history_window(history, "7d")
    assert len(window) == 24 * 7 + 1


def test_select_history_window_30d_membership_is_exact():
    history = _hourly_history(24 * 40)
    window = select_history_window(history, "30d")
    assert len(window) == 24 * 30 + 1


def test_select_history_window_all_exposes_full_persisted_history():
    history = _hourly_history(24 * 40)
    window = select_history_window(history, "all")
    assert len(window) == len(history) == 24 * 40
    assert window == history


def test_select_history_window_rejects_unknown_viewport():
    try:
        select_history_window(_hourly_history(1), "12h")
    except ValueError as exc:
        assert "12h" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported viewport")


def test_build_history_view_defaults_to_30d():
    assert DEFAULT_HISTORY_VIEWPORT == "30d"
    history = _hourly_history(24 * 40)
    view = build_history_view(history)
    assert view.viewport == "30d"
    assert len(view.points) == 24 * 30 + 1
    assert view.total_persisted_count == len(history)


def test_build_history_view_visible_bounds_always_include_zero():
    history = tuple(
        RotationPressureHistoryPoint(
            pressure_snapshot_id=index,
            as_of_ts_utc=datetime(2026, 8, 10, 0, 0) + timedelta(hours=index),
            market_score=score,
        )
        for index, score in enumerate([5.0, 12.0, 8.0])
    )
    view = build_history_view(history, "all")
    assert view.visible_min == 0.0
    assert view.visible_max == 12.0

    negative_history = tuple(
        RotationPressureHistoryPoint(
            pressure_snapshot_id=index,
            as_of_ts_utc=datetime(2026, 8, 10, 0, 0) + timedelta(hours=index),
            market_score=score,
        )
        for index, score in enumerate([-30.0, -5.0, -18.0])
    )
    negative_view = build_history_view(negative_history, "all")
    assert negative_view.visible_min == -30.0
    assert negative_view.visible_max == 0.0


def test_detect_snapshot_cadence_hourly():
    history = _hourly_history(48)
    assert detect_snapshot_cadence(history) == timedelta(hours=1)
    assert format_cadence_label(detect_snapshot_cadence(history)) == "1h snapshots"


def test_detect_snapshot_cadence_needs_two_points():
    assert detect_snapshot_cadence(_hourly_history(1)) is None
    assert format_cadence_label(None) == "cadence unknown"


def test_detect_snapshot_cadence_is_robust_to_one_gap():
    base = datetime(2026, 8, 10, 0, 0)
    history = tuple(
        RotationPressureHistoryPoint(pressure_snapshot_id=i, as_of_ts_utc=ts, market_score=0.0)
        for i, ts in enumerate(
            [base, base + timedelta(hours=1), base + timedelta(hours=2), base + timedelta(hours=9)]
        )
    )
    assert detect_snapshot_cadence(history) == timedelta(hours=1)


def test_format_history_window_label_states_span_and_cadence():
    history = _hourly_history(24 * 40)
    view = build_history_view(history, "30d")
    assert format_history_window_label(view) == "history: 30d · 1h snapshots"


def test_build_dashboard_preserves_full_persisted_history_row_count():
    history_rows = [
        {
            "pressure_snapshot_id": i,
            "as_of_ts_utc": datetime(2026, 7, 1, 0, 0) + timedelta(hours=i),
            "market_score": 1.0,
        }
        for i in range(200)
    ]
    dashboard = build_dashboard(_header(), _rows(), now_utc=NOW, history_rows=history_rows)
    assert len(dashboard.history) == 200
    all_view = build_history_view(dashboard.history, "all")
    assert len(all_view.points) == 200


def test_render_dashboard_has_all_viewport_buttons_and_defaults_to_30d():
    dashboard = build_dashboard(_header(), _rows(), now_utc=NOW, history_rows=[
        {"pressure_snapshot_id": 1, "as_of_ts_utc": datetime(2026, 7, 12, 19, 0), "market_score": 5.0},
        {"pressure_snapshot_id": 2, "as_of_ts_utc": datetime(2026, 7, 12, 20, 0), "market_score": 38.5},
    ])
    rendered = render_dashboard_html(dashboard)
    for viewport in HISTORY_VIEWPORTS:
        assert f"data-viewport='{viewport}'" in rendered
    assert "history-viewport-btn active' data-viewport='30d'" in rendered
    assert "history-panel active' data-viewport='30d'" in rendered
    assert "history: 30d ·" in rendered


def test_render_dashboard_history_scale_reflects_visible_window_not_fixed_domain():
    dashboard = build_dashboard(_header(), _rows(), now_utc=NOW, history_rows=[
        {"pressure_snapshot_id": 1, "as_of_ts_utc": datetime(2026, 7, 12, 19, 0), "market_score": 5.0},
        {"pressure_snapshot_id": 2, "as_of_ts_utc": datetime(2026, 7, 12, 20, 0), "market_score": 12.0},
    ])
    rendered = render_dashboard_html(dashboard)
    assert "<span>+0.0</span><span>0</span><span>+12.0</span>" in rendered
