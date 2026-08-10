from __future__ import annotations

import json as jsonlib
from datetime import UTC, datetime, timedelta

from src.reporting.sector_rotation_dashboard_v1 import (
    WINDOWS,
    build_dashboard,
    classify_freshness,
    dashboard_to_json_dict,
    render_dashboard_html,
    select_coherent_cohort,
)
from src.reporting.run_sector_rotation_dashboard_v1 import atomic_text_write


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


def _full_snapshot_rows(asof_sectors=None):
    sectors = asof_sectors if asof_sectors is not None else _sector_defs()
    rows = []
    for sector in sectors:
        for window_code in WINDOWS:
            rows.append(_snapshot_row(sector["sector_code"], window_code))
    return rows


def _window_codes(rows):
    return {row["window_code"] for row in rows}


def _build(rows, *, latest_asof_ts_utc=ASOF, sector_defs=None):
    return build_dashboard(
        sector_defs if sector_defs is not None else _sector_defs(),
        rows,
        venue="bitvavo",
        model_version="sector-rotation-v1.0.0",
        latest_asof_ts_utc=latest_asof_ts_utc,
        observed_window_codes=_window_codes(rows),
        now_utc=NOW,
    )


# --- select_coherent_cohort: latest-only, no fallback -----------------------


def test_select_coherent_cohort_accepts_canonical_windows_at_latest():
    asof, reason = select_coherent_cohort(ASOF, {"1h", "4h", "1d", "7d"})
    assert asof == ASOF
    assert reason is None


def test_select_coherent_cohort_rejects_missing_window_no_fallback():
    asof, reason = select_coherent_cohort(ASOF, {"1h", "4h", "1d"})
    assert asof is None
    assert reason == "INCOMPLETE_LATEST_COHORT"


def test_select_coherent_cohort_rejects_noncanonical_window_codes():
    asof, reason = select_coherent_cohort(ASOF, {"1m", "5m", "15m", "30m"})
    assert asof is None
    assert reason == "INCOMPLETE_LATEST_COHORT"


def test_select_coherent_cohort_none_when_no_candidates():
    asof, reason = select_coherent_cohort(None, set())
    assert asof is None
    assert reason == "NO_COHORT_CANDIDATES"


# --- freshness ---------------------------------------------------------------


def test_classify_freshness_fresh_stale_future():
    assert classify_freshness(ASOF, NOW) == "FRESH"
    assert classify_freshness(datetime(2026, 7, 16, 10, 0), NOW) == "STALE"
    assert classify_freshness(datetime(2026, 7, 16, 23, 0), NOW) == "FUTURE_TIMESTAMP"


# --- build_dashboard: no fallback to an older complete cohort ---------------


def test_no_fallback_when_newest_cohort_incomplete_even_if_older_is_complete():
    # Only the newest asof_ts_utc is ever inspected by build_dashboard; an
    # older, complete cohort must never be substituted in.
    newest_incomplete_rows = [
        r for r in _full_snapshot_rows() if not (r["sector_code"] == "DEFI_YIELD" and r["window_code"] == "7d")
    ]
    dashboard = _build(newest_incomplete_rows, latest_asof_ts_utc=ASOF)
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "INCOMPLETE_LATEST_COHORT"
    assert dashboard.sectors == ()
    # The attempted (newest) as-of timestamp is still surfaced for display.
    assert dashboard.asof_ts_utc == ASOF


def test_four_noncanonical_windows_is_data_unavailable():
    rows = []
    for sector in _sector_defs():
        for window_code in ("1m", "5m", "15m", "30m"):
            rows.append(_snapshot_row(sector["sector_code"], window_code))
    dashboard = _build(rows, latest_asof_ts_utc=ASOF)
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "INCOMPLETE_LATEST_COHORT"
    assert dashboard.sectors == ()


def test_missing_sector_window_cell_in_newest_cohort_is_data_unavailable():
    rows = [
        r for r in _full_snapshot_rows() if not (r["sector_code"] == "DEFI_YIELD" and r["window_code"] == "7d")
    ]
    dashboard = _build(rows, latest_asof_ts_utc=ASOF)
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "INCOMPLETE_LATEST_COHORT"
    assert dashboard.sectors == ()


def test_no_cohort_candidates_is_data_unavailable():
    dashboard = _build([], latest_asof_ts_utc=None)
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "NO_COHORT_CANDIDATES"
    assert dashboard.asof_ts_utc is None
    assert dashboard.age_seconds is None


def test_no_active_sectors_is_data_unavailable():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF, sector_defs=[])
    assert dashboard.status == "DATA_UNAVAILABLE"
    assert dashboard.reason == "NO_ACTIVE_SECTORS"


def test_exact_canonical_complete_latest_cohort_publishes_normally():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    assert dashboard.status == "AVAILABLE"
    assert dashboard.freshness_state == "FRESH"
    assert dashboard.reason is None
    assert len(dashboard.sectors) == 2
    for sector in dashboard.sectors:
        assert len(sector.cells) == 4
        assert [cell.window_code for cell in sector.cells] == list(WINDOWS)
        for cell in sector.cells:
            assert cell.cell_status == "AVAILABLE"


def test_deterministic_ordering_follows_sector_definition_order():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    assert [s.sector_code for s in dashboard.sectors] == ["AI_COMPUTE", "DEFI_YIELD"]


def test_persisted_sector_order_is_not_recomputed_from_rotation_scores():
    rows = _full_snapshot_rows()
    for row in rows:
        row["rotation_score"] = -99.0 if row["sector_code"] == "AI_COMPUTE" else 99.0

    dashboard = _build(rows, latest_asof_ts_utc=ASOF)

    assert [sector.sector_code for sector in dashboard.sectors] == ["AI_COMPUTE", "DEFI_YIELD"]
    assert dashboard.sectors[0].cells[0].rotation_score == -99.0
    assert dashboard.sectors[1].cells[0].rotation_score == 99.0


def test_stale_cohort_is_degraded_with_age():
    stale_asof = datetime(2026, 7, 16, 10, 0)
    rows = _full_snapshot_rows()
    dashboard = _build(rows, latest_asof_ts_utc=stale_asof)
    assert dashboard.status == "DEGRADED"
    assert dashboard.freshness_state == "STALE"
    assert dashboard.age_seconds == timedelta(hours=9).total_seconds()


def test_stale_missing_and_unavailable_are_distinct_rendered_states():
    stale = _build(_full_snapshot_rows(), latest_asof_ts_utc=datetime(2026, 7, 16, 10, 0))
    missing = _build(
        [
            row for row in _full_snapshot_rows()
            if not (row["sector_code"] == "DEFI_YIELD" and row["window_code"] == "7d")
        ],
        latest_asof_ts_utc=ASOF,
    )
    unavailable = _build([], latest_asof_ts_utc=None)

    assert stale.status == "DEGRADED"
    assert stale.freshness_state == "STALE"
    assert "STALE" in render_dashboard_html(stale)
    assert missing.status == "DATA_UNAVAILABLE"
    assert missing.reason == "INCOMPLETE_LATEST_COHORT"
    assert "INCOMPLETE_LATEST_COHORT" in render_dashboard_html(missing)
    assert unavailable.status == "DATA_UNAVAILABLE"
    assert unavailable.reason == "NO_COHORT_CANDIDATES"
    assert "NO_COHORT_CANDIDATES" in render_dashboard_html(unavailable)


# --- JSON/HTML share one view model ------------------------------------------


def test_json_and_html_derive_from_same_view_model():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    payload = dashboard_to_json_dict(dashboard)
    rendered = render_dashboard_html(dashboard)
    assert payload["status"] == dashboard.status
    assert len(payload["sectors"]) == len(dashboard.sectors)
    assert "AI / Compute" in rendered
    assert "DeFi Yield" in rendered
    for sector in payload["sectors"]:
        assert set(sector["windows"].keys()) == set(WINDOWS)


def test_unavailable_json_and_html_share_view_model_and_reason():
    dashboard = _build([], latest_asof_ts_utc=None)
    payload = dashboard_to_json_dict(dashboard)
    rendered = render_dashboard_html(dashboard)
    assert payload["status"] == "DATA_UNAVAILABLE"
    assert payload["reason"] == "NO_COHORT_CANDIDATES"
    assert "NO_COHORT_CANDIDATES" in rendered
    assert payload["reason"] in rendered


def test_json_preserves_canonical_machine_codes():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    payload = dashboard_to_json_dict(dashboard)
    first_sector = payload["sectors"][0]
    assert first_sector["sector_code"] == "AI_COMPUTE"
    assert first_sector["windows"]["1h"]["rotation_state"] == "LEADING"
    assert payload["model_version"] == "sector-rotation-v1.0.0"


def test_render_dashboard_shows_proxy_wording_not_measured_flow():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    rendered = render_dashboard_html(dashboard)
    assert "proxi" in rendered.lower()
    assert "not measured capital inflow or outflow" in rendered.lower()
    payload = dashboard_to_json_dict(dashboard)
    assert "proxi" in payload["rotation_proxy_disclaimer"].lower()


def test_render_unavailable_page_contains_reason_asof_age_generated_safety():
    dashboard = _build(
        [r for r in _full_snapshot_rows() if not (r["sector_code"] == "DEFI_YIELD" and r["window_code"] == "7d")],
        latest_asof_ts_utc=ASOF,
    )
    rendered = render_dashboard_html(dashboard)
    assert "DATA UNAVAILABLE" in rendered
    assert "INCOMPLETE_LATEST_COHORT" in rendered
    assert "2026-07-16T18:00:00Z" in rendered  # attempted as-of
    assert "Age" in rendered
    assert "Generated" in rendered
    assert "db_writes=0" in rendered
    assert "decision_gate=none" in rendered


def test_render_unavailable_page_shows_unknown_asof_when_no_candidates():
    dashboard = _build([], latest_asof_ts_utc=None)
    rendered = render_dashboard_html(dashboard)
    assert "Attempted as of unknown" in rendered
    assert "Age unknown" in rendered


def test_render_dashboard_shows_age_alongside_freshness_and_asof():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    rendered = render_dashboard_html(dashboard)
    assert "FRESH" in rendered
    assert "2026-07-16T18:00:00Z" in rendered
    assert "Age 1h00m" in rendered


def test_json_does_not_substitute_zero_for_unavailable():
    dashboard = _build([], latest_asof_ts_utc=None)
    payload = dashboard_to_json_dict(dashboard)
    assert payload["sectors"] == []
    assert payload["asof_ts_utc"] is None
    assert payload["age_seconds"] is None


def test_safety_markers_are_all_zero_or_none():
    dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    safety = dashboard_to_json_dict(dashboard)["safety"]
    assert safety == {
        "account_inputs": 0,
        "db_writes": 0,
        "writer_calls": 0,
        "broker_calls": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "decision_gate": "none",
        "execution_planner": "none",
        "executor": "none",
    }


def test_unavailable_dashboard_also_carries_safety_markers():
    dashboard = _build([], latest_asof_ts_utc=None)
    safety = dashboard_to_json_dict(dashboard)["safety"]
    assert safety["db_writes"] == 0
    assert safety["decision_gate"] == "none"


# --- atomic publish must replace prior output --------------------------------


def test_unavailable_run_replaces_pre_existing_output_files(tmp_path):
    html_path = tmp_path / "sector-overview.html"
    json_path = tmp_path / "sector-overview.json"

    available_dashboard = _build(_full_snapshot_rows(), latest_asof_ts_utc=ASOF)
    atomic_text_write(render_dashboard_html(available_dashboard), html_path)
    atomic_text_write(jsonlib.dumps(dashboard_to_json_dict(available_dashboard)), json_path)
    assert "AI / Compute" in html_path.read_text(encoding="utf-8")
    assert '"status": "AVAILABLE"' in json_path.read_text(encoding="utf-8")

    unavailable_dashboard = _build([], latest_asof_ts_utc=None)
    atomic_text_write(render_dashboard_html(unavailable_dashboard), html_path)
    atomic_text_write(jsonlib.dumps(dashboard_to_json_dict(unavailable_dashboard)), json_path)

    html_content = html_path.read_text(encoding="utf-8")
    json_content = json_path.read_text(encoding="utf-8")
    assert "AI / Compute" not in html_content
    assert "DATA UNAVAILABLE" in html_content
    assert '"status": "AVAILABLE"' not in json_content
    assert '"status": "DATA_UNAVAILABLE"' in json_content


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


def test_runner_has_no_writer_broker_or_account_layer_import():
    import ast
    import inspect

    from src.reporting import run_sector_rotation_dashboard_v1 as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_substrings = (
        "sector_rotation_engine",
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "selection_engine",
        "account",
    )
    for name in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import: {name}"
