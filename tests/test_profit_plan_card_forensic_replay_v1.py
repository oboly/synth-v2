from __future__ import annotations

import csv
import json
from pathlib import Path

from src.research.run_profit_plan_card_forensic_replay_v1 import (
    DEFAULT_FIXTURES_PATH,
    replay_fixtures,
)


REQUIRED_FIXTURE_IDS = {
    "active_map_only",
    "completed_map_only",
    "invalidated_map_only",
    "active_map_plus_older_completed_map",
    "completed_map_plus_newer_active_rollover_map",
    "active_map_plus_newer_invalidated_map",
    "stale_current_price",
    "missing_current_price",
    "missing_native_short_context",
    "map_with_all_targets_historically_passed",
    "target_changed_after_map_rollover",
    "stale_open_order_at_old_map_level",
    "historical_order_at_completed_target",
    "active_map_with_missing_ladder_orders",
    "active_map_with_fully_armed_ladder",
    "contradictory_source_statuses_or_broken_lineage",
}


def _run(tmp_path: Path) -> Path:
    summary = replay_fixtures(
        fixtures_path=DEFAULT_FIXTURES_PATH,
        output_root=tmp_path,
        run_id="pytest-run",
    )
    return Path(summary["output_dir"])


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _violations(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_fixture_file_contains_required_p0d_cases() -> None:
    payload = json.loads(DEFAULT_FIXTURES_PATH.read_text(encoding="utf-8"))
    fixture_ids = {row["fixture_id"] for row in payload["fixtures"]}
    assert payload["schema_version"] == "profit_plan_card_forensic_replay_v1"
    assert REQUIRED_FIXTURE_IDS <= fixture_ids
    assert len(payload["fixtures"]) >= 16


def test_replay_writes_required_research_outputs(tmp_path: Path) -> None:
    output_dir = _run(tmp_path)

    assert (output_dir / "fixture_results.jsonl").is_file()
    assert (output_dir / "invariant_violations.csv").is_file()
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "manifest.json").is_file()
    assert (output_dir / "card_json_snapshots").is_dir()
    assert (output_dir / "card_html_snapshots").is_dir()

    results = _jsonl(output_dir / "fixture_results.jsonl")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert len(results) >= 16
    assert summary["safety"] == {
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "decision_gate": "none",
        "execution_planner": "none",
        "executor": "none",
    }
    assert manifest["outputs"]["fixture_results_jsonl"] == "fixture_results.jsonl"
    for result in results:
        assert (output_dir / result["card_json_path"]).is_file()
        assert (output_dir / result["card_html_path"]).is_file()


def test_replay_uses_native_short_rank_for_rollover_selection(tmp_path: Path) -> None:
    output_dir = _run(tmp_path)
    by_id = {row["fixture_id"]: row for row in _jsonl(output_dir / "fixture_results.jsonl")}

    assert (
        by_id["completed_map_plus_newer_active_rollover_map"]["selected_map"]["map_cycle_id"]
        == "EEE|SHORT|4h|active-2"
    )
    assert (
        by_id["active_map_plus_newer_invalidated_map"]["selected_map"]["map_cycle_id"]
        == "FFF|SHORT|4h|active-1"
    )
    assert (
        by_id["target_changed_after_map_rollover"]["selected_map"]["map_cycle_id"]
        == "KKK|SHORT|4h|active-2"
    )
    rollover_card = by_id["target_changed_after_map_rollover"]["card_semantics"]
    assert rollover_card["active_target"] is None
    assert rollover_card["event_state"] == "CONTEXT_UNAVAILABLE"
    assert rollover_card["action_label"] == "REVIEW_CONTEXT"


def test_stale_old_map_order_does_not_create_lineage_claim_without_canonical_truth(tmp_path: Path) -> None:
    output_dir = _run(tmp_path)
    violations = _violations(output_dir / "invariant_violations.csv")

    matching = [
        row
        for row in violations
        if row["fixture_id"] == "stale_open_order_at_old_map_level"
        and row["invariant_id"] == "I006_ORDER_ROWS_MATCH_ACTIVE_MAP_LINEAGE"
    ]
    assert not matching, "reporting must not evaluate active-map order lineage from transient map rows"


def test_stale_current_price_fixture_blocks_action_semantics(tmp_path: Path) -> None:
    output_dir = _run(tmp_path)
    by_id = {row["fixture_id"]: row for row in _jsonl(output_dir / "fixture_results.jsonl")}
    stale = by_id["stale_current_price"]["card_semantics"]

    assert stale["primary_state"] == "CONTEXT_UNAVAILABLE"
    assert stale["action_label"] == "REVIEW_CONTEXT"
    assert stale["active_target"] is None
    assert stale["target_exit_zone"] == []
    assert "ORDER_DATA_UNAVAILABLE" in stale["ladder_states"]


def test_contradictory_status_fixture_records_lifecycle_status_violation(tmp_path: Path) -> None:
    output_dir = _run(tmp_path)
    violations = _violations(output_dir / "invariant_violations.csv")
    ids = {
        row["invariant_id"]
        for row in violations
        if row["fixture_id"] == "contradictory_source_statuses_or_broken_lineage"
    }

    assert "I003_INVALIDATED_MAP_NOT_ACTIVE_CONTEXT" not in ids
    assert "I008_LIFECYCLE_SOURCE_STATUS_COMPATIBILITY" in ids


def test_html_json_parity_does_not_fail_for_clean_active_fixture(tmp_path: Path) -> None:
    output_dir = _run(tmp_path)
    violations = _violations(output_dir / "invariant_violations.csv")

    active_html_json = [
        row
        for row in violations
        if row["fixture_id"] == "active_map_with_fully_armed_ladder"
        and row["invariant_id"] == "I007_HTML_JSON_PARITY"
    ]
    assert active_html_json == []
