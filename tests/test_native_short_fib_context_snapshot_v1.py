from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data import native_short_fib_context_snapshot_v1 as snapshot
from src.market_data import run_native_short_fib_context_snapshot_v1 as runner
from src.market_data.native_short_fib_context_v1 import (
    STATUS_AVAILABLE,
    STATUS_STALE_OR_INVALID,
    STATUS_SYMBOL_MISSING,
    load_native_short_context_rows,
)


AS_OF = datetime(2026, 7, 16, 12, tzinfo=UTC)


def _scope(**overrides):
    row = {
        "scope_id": 1,
        "venue": "bitvavo",
        "symbol": "BTC",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "scope_support_state": "SUPPORTED",
        "scope_reason_code": None,
        "scope_status_id": 11,
        "scope_status_code": "CURRENT_EVALUATION",
        "scope_status_reason_code": None,
        "map_lifecycle_state": "MAP_ACTIVE",
        "observation_freshness_state": "OBSERVATION_CURRENT",
        "source_freshness_state": "SOURCE_CURRENT",
        "actionability_state": "ACTIONABLE_ACTIVE_MAP",
        "current_map_id": 7,
        "current_map_cycle_id": "cycle-btc-1",
        "latest_generation_event_id": 70,
        "latest_lifecycle_event_id": 71,
        "latest_observation_id": 72,
        "latest_run_id": 73,
        "latest_observed_at_utc": AS_OF,
        "primary_latest_candle_ts_utc": AS_OF - timedelta(hours=4),
        "supporting_latest_candle_ts_utc": AS_OF - timedelta(hours=1),
        "projection_as_of_utc": AS_OF,
        "rebuilt_at_utc": AS_OF + timedelta(minutes=1),
    }
    row.update(overrides)
    return row


def _map(**overrides):
    row = {
        "map_id": 7,
        "venue": "bitvavo",
        "symbol": "BTC",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "map_cycle_id": "cycle-btc-1",
        "previous_map_id": 6,
        "previous_map_cycle_id": "cycle-btc-0",
        "published_at_utc": AS_OF - timedelta(days=2),
        "structure_hash": "a" * 64,
        "anchor_low_ts_utc": AS_OF - timedelta(days=8),
        "anchor_low_price": "90",
        "anchor_high_ts_utc": AS_OF - timedelta(days=5),
        "anchor_high_price": "100",
        "fib_ratios_json": json.dumps(
            {
                "breakout_gate": "100",
                "ext_1_272": "102.72",
                "ext_1_618": "106.18",
                "ext_2_000": "110",
                "reload_r382": "96.18",
                "reload_r500": "95",
                "reload_r618": "93.82",
                "reload_r786": "92.14",
            }
        ),
        "invalidation_price": "90",
        "source_primary_ref": "obs_market_candle:4h",
        "source_support_ref": "obs_market_candle:1h",
        "source_primary_candle_count": 120,
        "source_support_candle_count": 240,
    }
    row.update(overrides)
    return row


def _levels(*, state_by_role=None, price_1272="102.72"):
    states = state_by_role or {
        "SELL_EXT_1_272": "REACHED",
        "SELL_EXT_1_618": "ACTIVE",
        "SELL_EXT_2_000": "ACTIVE",
    }
    prices = {
        "SELL_EXT_1_272": price_1272,
        "SELL_EXT_1_618": "106.18",
        "SELL_EXT_2_000": "110",
    }
    return [
        {
            "map_level_status_id": index,
            "current_map_id": 7,
            "map_cycle_id": "cycle-btc-1",
            "canonical_map_level_role": role,
            "canonical_unrounded_price": prices[role],
            "level_lifecycle_state": states[role],
            "level_status_as_of_utc": AS_OF,
        }
        for index, role in enumerate(states, start=701)
    ]


def _build(*, scope_row=None, map_row=None, levels=None):
    scope_row = scope_row or _scope()
    map_row = _map() if map_row is None else map_row
    maps = {} if map_row is False else {7: map_row}
    level_map = {7: _levels() if levels is None else levels}
    return snapshot.build_snapshot(
        scopes=[scope_row],
        maps_by_id=maps,
        levels_by_map_id=level_map,
        generation_event_ts_by_id={70: AS_OF - timedelta(minutes=2)},
        lifecycle_event_ts_by_id={71: AS_OF - timedelta(minutes=1)},
    )


def test_field_projection_uses_persisted_authorities_and_parser_contract(tmp_path: Path) -> None:
    build = _build()
    row = build.rows[0]

    assert row["context_status"] == STATUS_AVAILABLE
    assert row["native_map_id"] == "7"
    assert row["map_cycle_id"] == "cycle-btc-1"
    assert row["anchor_low_price"] == "90"
    assert row["breakout_gate_price"] == "100"
    assert row["ext_1_618_price"] == "106.18"
    assert json.loads(row["active_target_levels_json"]) == ["106.18", "110"]
    assert json.loads(row["previous_target_levels_json"]) == ["102.72"]
    assert row["primary_4h_lifecycle_state"] == "MAP_ACTIVE"
    assert row["latest_primary_close_ts_utc"] == "2026-07-16T08:00:00Z"
    assert row["context_freshness_status"] == snapshot.FRESH
    availability = json.loads(row["field_availability_json"])
    assert availability["supporting_1h_state"] == snapshot.UNAVAILABLE
    assert availability["rollover_state"] == snapshot.UNAVAILABLE

    csv_path = tmp_path / snapshot.ROWS_NAME
    snapshot.atomic_write_bytes(csv_path, snapshot.render_rows_csv(build.rows))
    loaded, missing = load_native_short_context_rows(csv_path)
    assert missing is False
    assert loaded["BTC"].map_cycle_id == "cycle-btc-1"
    assert loaded["BTC"].active_target_levels == (Decimal("106.18"), Decimal("110"))


def test_unsupported_scope_is_explicitly_unavailable() -> None:
    build = _build(
        scope_row=_scope(
            scope_support_state="NOT_APPLICABLE",
            scope_reason_code="UNSUPPORTED_MARKET",
            scope_status_id=None,
            current_map_id=None,
        ),
        map_row=False,
        levels=[],
    )
    row = build.rows[0]
    assert row["context_status"] == STATUS_SYMBOL_MISSING
    assert row["context_freshness_status"] == snapshot.UNAVAILABLE
    assert row["selection_reason"] == "UNSUPPORTED_MARKET"


@pytest.mark.parametrize(
    ("scope_row", "map_row", "levels", "reason_fragment"),
    [
        (_scope(current_map_id=None), False, [], "NO_CURRENT_MAP"),
        (_scope(), False, [], "SELECTED_MAP_GEOMETRY_MISSING"),
        (_scope(), _map(fib_ratios_json="{}"), _levels(), "GEOMETRY"),
        (_scope(latest_lifecycle_event_id=None), _map(), _levels(), "LIFECYCLE"),
        (_scope(), _map(), [], "THREE_V1_SELL"),
    ],
)
def test_missing_authority_fails_closed(scope_row, map_row, levels, reason_fragment) -> None:
    build = _build(scope_row=scope_row, map_row=map_row, levels=levels)
    row = build.rows[0]
    assert row["context_status"] == STATUS_STALE_OR_INVALID
    assert row["context_freshness_status"] == snapshot.MISSING
    assert reason_fragment in row["selection_reason"]
    if "GEOMETRY" in reason_fragment:
        assert json.loads(row["field_availability_json"])["breakout_gate_price"] == snapshot.MISSING


def test_stale_projection_is_not_refreshed_by_producer_clock() -> None:
    build = _build(
        scope_row=_scope(
            scope_status_code="SOURCE_STALE",
            source_freshness_state="SOURCE_STALE",
            projection_as_of_utc=AS_OF - timedelta(days=1),
        ),
        levels=[{**row, "level_status_as_of_utc": AS_OF - timedelta(days=1)} for row in _levels()],
    )
    assert build.rows[0]["context_freshness_status"] == snapshot.STALE
    assert build.rows[0]["context_status"] == STATUS_STALE_OR_INVALID


@pytest.mark.parametrize("field", ["primary_latest_candle_ts_utc", "supporting_latest_candle_ts_utc"])
def test_missing_persisted_source_timestamp_fails_closed(field: str) -> None:
    build = _build(scope_row=_scope(**{field: None}))
    assert build.rows[0]["context_freshness_status"] == snapshot.MISSING
    assert build.rows[0]["context_status"] == STATUS_STALE_OR_INVALID


def test_naive_source_timestamp_is_rejected_not_replaced_with_wall_clock() -> None:
    with pytest.raises(snapshot.SnapshotContractError, match="absolute"):
        _build(scope_row=_scope(projection_as_of_utc=datetime(2026, 7, 16, 12)))


def test_canonical_serialization_digest_and_snapshot_identity_are_stable() -> None:
    first = _build()
    second = _build()
    assert snapshot.canonical_json_bytes(first.rows) == snapshot.canonical_json_bytes(second.rows)
    assert first.content_digest == second.content_digest
    assert first.snapshot_id == second.snapshot_id


def test_rebuild_only_metadata_does_not_create_new_semantic_snapshot() -> None:
    first = _build()
    rebuilt_scope = _scope(scope_status_id=99, rebuilt_at_utc=AS_OF + timedelta(minutes=9))
    rebuilt_levels = [
        {**row, "map_level_status_id": int(row["map_level_status_id"]) + 1000}
        for row in _levels()
    ]
    rebuilt = _build(scope_row=rebuilt_scope, levels=rebuilt_levels)
    assert rebuilt.rows != first.rows
    assert rebuilt.content_digest == first.content_digest
    assert rebuilt.snapshot_id == first.snapshot_id


def test_changed_persisted_authority_changes_snapshot_identity() -> None:
    first = _build()
    changed = _build(scope_row=_scope(latest_observation_id=999))
    assert changed.content_digest != first.content_digest
    assert changed.snapshot_id != first.snapshot_id


def test_map_level_price_must_match_named_immutable_geometry() -> None:
    build = _build(levels=_levels(price_1272="102.73"))
    assert build.rows[0]["context_freshness_status"] == snapshot.MISSING
    assert "NAMED_GEOMETRY" in build.rows[0]["selection_reason"]


def test_publish_is_atomic_consistent_and_unchanged_is_not_duplicated(tmp_path: Path) -> None:
    build = _build()
    first = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF + timedelta(minutes=1),
    )
    second = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF + timedelta(hours=4),
        publication_ts_utc=AS_OF + timedelta(hours=4, minutes=1),
    )
    assert first.status == "PUBLISHED"
    assert second.status == "UNCHANGED"
    assert list((tmp_path / "snapshots").iterdir()) == [tmp_path / "snapshots" / build.snapshot_id]

    manifest = json.loads(first.manifest_path.read_text())
    bundle = json.loads(first.bundle_path.read_text())
    assert manifest["snapshot_id"] == bundle["envelope"]["snapshot_id"] == build.snapshot_id
    assert manifest["row_count"] == len(bundle["rows"]) == 1
    assert hashlib.sha256(first.rows_path.read_bytes()).hexdigest() == manifest["rows_csv_digest"].split(":", 1)[1]


def test_failed_commit_pointer_write_preserves_last_valid_snapshot(tmp_path: Path, monkeypatch) -> None:
    first = snapshot.publish_snapshot(
        _build(),
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
    )
    prior_manifest = first.manifest_path.read_bytes()
    changed = _build(levels=_levels(price_1272="102.73"))
    real_atomic_write = snapshot.atomic_write_bytes

    def fail_manifest(path: Path, payload: bytes) -> None:
        if path.name == snapshot.MANIFEST_NAME:
            raise OSError("interrupted before commit pointer replace")
        real_atomic_write(path, payload)

    monkeypatch.setattr(snapshot, "atomic_write_bytes", fail_manifest)
    with pytest.raises(OSError, match="interrupted"):
        snapshot.publish_snapshot(
            changed,
            output_dir=tmp_path,
            generated_ts_utc=AS_OF + timedelta(hours=4),
            publication_ts_utc=AS_OF + timedelta(hours=4),
        )
    assert first.manifest_path.read_bytes() == prior_manifest


def test_schema_validation_rejects_missing_field() -> None:
    row = dict(_build().rows[0])
    row.pop("native_map_id")
    with pytest.raises(snapshot.SnapshotContractError, match="schema fields"):
        snapshot.validate_rows([row])


def test_chain_calls_snapshot_once_after_native_authorities() -> None:
    source = Path("scripts/run_chain_4h.sh").read_text(encoding="utf-8")
    authority_step = "run_native_short_scope_status_chain_once.sh"
    snapshot_step = "src.market_data.run_native_short_fib_context_snapshot_v1"
    assert source.count(snapshot_step) == 1
    assert source.index(authority_step) < source.index(snapshot_step) < source.index("src.features.run_feat_candle")
    assert "--publish" in source[source.index(snapshot_step) : source.index("src.features.run_feat_candle")]


def test_boundary_has_no_forbidden_imports_or_second_scheduler() -> None:
    module_source = Path("src/market_data/native_short_fib_context_snapshot_v1.py").read_text(encoding="utf-8")
    runner_source = Path("src/market_data/run_native_short_fib_context_snapshot_v1.py").read_text(encoding="utf-8")
    combined = module_source + runner_source
    for forbidden in (
        "src.reporting",
        "src.account",
        "src.selection",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.agents",
        "src.broker",
        "src.research",
    ):
        assert forbidden not in combined
    assert "SYNTH_ACCOUNT" not in runner_source
    assert "build_htf_extension_map" not in combined
    assert "obs_market_candle" not in combined
    assert "map_payload_json" not in combined
    changed_runtime_source = combined + Path("scripts/run_chain_4h.sh").read_text(encoding="utf-8")
    assert "OnCalendar=" not in changed_runtime_source
    assert "systemctl" not in changed_runtime_source


def test_cli_defaults_to_read_only_and_market_owned_output_path() -> None:
    args = runner.parse_args([])
    assert args.publish is False
    assert args.output_dir == Path("/var/www/html/synth/_runtime/native_short_context_snapshot_v1")
