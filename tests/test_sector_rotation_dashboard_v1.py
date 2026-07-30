from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.reporting.sector_rotation_dashboard_v1 import (
    WINDOWS,
    build_dashboard,
    classify_freshness,
    dashboard_to_json_dict,
    render_dashboard_html,
    select_coherent_cohort,
)


NOW = datetime(2026, 7, 16, 19, 0, tzinfo=UTC)
ASOF = datetime(2026, 7, 16, 18, 0)


def _sector_defs():
    return [
        {"sector_code": "AI_COMPUTE", "display_name": "AI / Compute"},
        {"sector_code": "DEFI_YIELD", "display_name": "DeFi Yield"},
    ]


def _snapshot_row(sector_code: str, window_code: str, **overrides):
    row = {
        "sector_code": sector_code,
        "window_code": window_code,
        "rotation_score": 42.5,
        "rotation_state": "LEADING",
        "confidence": 0.71,
        "participation_ratio": 0.64,
        "supporting_flags_json": '{"rotation_inflow_proxy": true}',
        "generated_ts_utc": ASOF,
    }
    row.update(overrides)
    return row


def _full_snapshot_rows():
    rows = []
    for sector in _sector_defs():
        for window_code in WINDOWS:
            rows.append(_snapshot_row(sector["sector_code"], window_code))
    return rows


def test_select_coherent_cohort_picks_latest_with_all_windows():
    candidates = [
        {"asof_ts_utc": datetime(2026, 7, 16, 19, 0), "window_count": 2},
        {"asof_ts_utc": datetime(2026, 7, 16, 18, 0), "window_count": 4},
        {"asof_ts_utc": datetime(2026, 7, 16, 17, 0), "window_count": 4},
    ]
    assert select_coherent_cohort(candidates) == datetime(2026, 7, 16, 18, 0)


def test_select_coherent_cohort_none_when_no_full_cohort():
    candidates = [{"asof_ts_utc": datetime(2026, 7, 16, 19, 0), "window_count": 3}]
    assert select_coherent_cohort(candidates) is None


def test_classify_freshness_fresh_stale_future():
    assert classify_freshness(ASOF, NOW) == "FRESH"
    assert classify_freshness(datetime(2026, 7, 16, 10, 0), NOW) == "STALE"
    assert classify_freshness(datetime(2026, 7, 16, 23, 0), NOW) == "FUTURE_TIMESTAMP"


def test_build_dashboard_no_cohort_is_data_unavailable():
    dashboard = build_dashboard(
        [], [], venue="bitvavo", model_version="sector-rotation-v1.0.0", asof_ts_utc=None, now_utc=NOW
    )
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "NO_COHERENT_COHORT"
    assert dashboard.sectors == ()


def test_build_dashboard_no_active_sectors_is_data_unavailable():
    dashboard = build_dashboard(
        [], _full_snapshot_rows(), venue="bitvavo", model_version="sector-rotation-v1.0.0",
        asof_ts_utc=ASOF, now_utc=NOW,
    )
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "NO_ACTIVE_SECTORS"


def test_build_dashboard_available_with_full_four_windows():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    assert dashboard.status == "AVAILABLE"
    assert dashboard.freshness_state == "FRESH"
    assert len(dashboard.sectors) == 2
    for sector in dashboard.sectors:
        assert len(sector.cells) == 4
        assert [cell.window_code for cell in sector.cells] == list(WINDOWS)
        for cell in sector.cells:
            assert cell.cell_status == "AVAILABLE"


def test_build_dashboard_deterministic_ordering_follows_sector_definition_order():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    assert [s.sector_code for s in dashboard.sectors] == ["AI_COMPUTE", "DEFI_YIELD"]


def test_build_dashboard_missing_window_marks_cell_unavailable_not_zero():
    rows = [r for r in _full_snapshot_rows() if not (r["sector_code"] == "DEFI_YIELD" and r["window_code"] == "7d")]
    dashboard = build_dashboard(
        _sector_defs(), rows, venue="bitvavo", model_version="sector-rotation-v1.0.0",
        asof_ts_utc=ASOF, now_utc=NOW,
    )
    assert dashboard.status == "DEGRADED"
    defi = next(s for s in dashboard.sectors if s.sector_code == "DEFI_YIELD")
    missing_cell = next(c for c in defi.cells if c.window_code == "7d")
    assert missing_cell.cell_status == "UNAVAILABLE"
    assert missing_cell.rotation_score is None
    assert missing_cell.participation_ratio is None


def test_build_dashboard_stale_cohort_is_degraded_with_age():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0",
        asof_ts_utc=datetime(2026, 7, 16, 10, 0), now_utc=NOW,
    )
    assert dashboard.status == "DEGRADED"
    assert dashboard.freshness_state == "STALE"
    assert dashboard.age_seconds == timedelta(hours=9).total_seconds()


def test_json_and_html_derive_from_same_view_model():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    payload = dashboard_to_json_dict(dashboard)
    rendered = render_dashboard_html(dashboard)
    assert payload["status"] == dashboard.status
    assert len(payload["sectors"]) == len(dashboard.sectors)
    assert "AI / Compute" in rendered
    assert "DeFi Yield" in rendered
    for sector in payload["sectors"]:
        assert set(sector["windows"].keys()) == set(WINDOWS)


def test_json_preserves_canonical_machine_codes():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    payload = dashboard_to_json_dict(dashboard)
    first_sector = payload["sectors"][0]
    assert first_sector["sector_code"] == "AI_COMPUTE"
    assert first_sector["windows"]["1h"]["rotation_state"] == "LEADING"
    assert payload["model_version"] == "sector-rotation-v1.0.0"


def test_json_does_not_substitute_zero_for_unavailable():
    rows = [r for r in _full_snapshot_rows() if not (r["sector_code"] == "DEFI_YIELD" and r["window_code"] == "7d")]
    dashboard = build_dashboard(
        _sector_defs(), rows, venue="bitvavo", model_version="sector-rotation-v1.0.0",
        asof_ts_utc=ASOF, now_utc=NOW,
    )
    payload = dashboard_to_json_dict(dashboard)
    defi = next(s for s in payload["sectors"] if s["sector_code"] == "DEFI_YIELD")
    cell = defi["windows"]["7d"]
    assert cell["cell_status"] == "UNAVAILABLE"
    assert cell["rotation_score"] is None
    assert cell["participation_ratio"] is None


def test_render_dashboard_shows_proxy_wording_not_measured_flow():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    rendered = render_dashboard_html(dashboard)
    assert "proxy" in rendered.lower()
    assert "not measured capital inflow or outflow" in rendered.lower()
    payload = dashboard_to_json_dict(dashboard)
    assert "proxi" in payload["rotation_proxy_disclaimer"].lower()


def test_render_unavailable_page_contains_reason():
    dashboard = build_dashboard(
        [], [], venue="bitvavo", model_version="sector-rotation-v1.0.0", asof_ts_utc=None, now_utc=NOW
    )
    rendered = render_dashboard_html(dashboard)
    assert "DATA UNAVAILABLE" in rendered
    assert "NO_COHERENT_COHORT" in rendered


def test_render_dashboard_shows_freshness_and_asof():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    rendered = render_dashboard_html(dashboard)
    assert "FRESH" in rendered
    assert "2026-07-16T18:00:00Z" in rendered


def test_safety_markers_are_all_zero_or_none():
    dashboard = build_dashboard(
        _sector_defs(), _full_snapshot_rows(), venue="bitvavo",
        model_version="sector-rotation-v1.0.0", asof_ts_utc=ASOF, now_utc=NOW,
    )
    safety = dashboard_to_json_dict(dashboard)["safety"]
    assert safety == {
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "decision_gate": "none",
        "execution_planner": "none",
        "executor": "none",
    }


def test_module_has_no_write_capable_or_execution_layer_import():
    import ast
    import inspect

    from src.reporting import sector_rotation_dashboard_v1 as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_substrings = ("executor", "decision_gate", "execution_planner", "broker", "db")
    for name in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import: {name}"
