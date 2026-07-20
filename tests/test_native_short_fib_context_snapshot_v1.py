from __future__ import annotations

from tests.writer_auth_support import make_test_authorization
_NS_AUTH = make_test_authorization("native_short_4h_chain")


import pytest as _pytest_authz


@_pytest_authz.fixture(autouse=True)
def _authorized_writer_context(monkeypatch):
    """Run write mechanics as an already-authorized writer capability. Denial is
    covered by tests/test_writer_capability_authorization_v1.py."""
    from tests.writer_auth_support import install_authorized_writer_context
    install_authorized_writer_context(monkeypatch)

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


def test_not_applicable_row_does_not_degrade_supported_overall_freshness() -> None:
    unsupported = _scope(
        scope_id=2,
        symbol="ETH",
        scope_support_state="NOT_APPLICABLE",
        scope_reason_code="UNSUPPORTED_MARKET",
        scope_status_id=None,
        current_map_id=None,
    )
    build = snapshot.build_snapshot(
        scopes=[unsupported, _scope()],
        maps_by_id={7: _map()},
        levels_by_map_id={7: _levels()},
        generation_event_ts_by_id={70: AS_OF - timedelta(minutes=2)},
        lifecycle_event_ts_by_id={71: AS_OF - timedelta(minutes=1)},
    )
    assert build.counts == {"fresh": 1, "stale": 0, "missing": 0, "unavailable": 1, "supported": 1}
    assert build.overall_freshness_state == snapshot.FRESH


def test_supported_stale_row_remains_overall_stale_with_unsupported_inventory() -> None:
    stale_scope = _scope(scope_status_code="SOURCE_STALE", source_freshness_state="SOURCE_STALE")
    stale_levels = [{**row, "level_status_as_of_utc": AS_OF} for row in _levels()]
    unsupported = _scope(
        scope_id=2,
        symbol="ETH",
        scope_support_state="NOT_APPLICABLE",
        scope_status_id=None,
        current_map_id=None,
    )
    build = snapshot.build_snapshot(
        scopes=[stale_scope, unsupported],
        maps_by_id={7: _map()},
        levels_by_map_id={7: stale_levels},
        generation_event_ts_by_id={70: AS_OF},
        lifecycle_event_ts_by_id={71: AS_OF},
    )
    assert build.overall_freshness_state == snapshot.STALE


def test_no_supported_scope_has_unavailable_overall_summary() -> None:
    build = _build(
        scope_row=_scope(scope_support_state="NOT_APPLICABLE", scope_status_id=None, current_map_id=None),
        map_row=False,
        levels=[],
    )
    assert build.overall_freshness_state == snapshot.UNAVAILABLE


@pytest.mark.parametrize("field", ["primary_latest_candle_ts_utc", "supporting_latest_candle_ts_utc"])
def test_missing_persisted_source_timestamp_fails_closed(field: str) -> None:
    build = _build(scope_row=_scope(**{field: None}))
    assert build.rows[0]["context_freshness_status"] == snapshot.MISSING
    assert build.rows[0]["context_status"] == STATUS_STALE_OR_INVALID


def test_naive_source_timestamp_is_rejected_not_replaced_with_wall_clock() -> None:
    with pytest.raises(snapshot.SnapshotContractError, match="absolute"):
        _build(scope_row=_scope(projection_as_of_utc=datetime(2026, 7, 16, 12)))


def test_persisted_mariadb_datetime_is_explicitly_typed_as_utc() -> None:
    persisted = datetime(2026, 7, 16, 12, 34, 56)
    typed = snapshot.persisted_db_datetime_utc(
        persisted,
        table="native_short_scope_status_v1",
        field="projection_as_of_utc",
    )
    assert typed == datetime(2026, 7, 16, 12, 34, 56, tzinfo=UTC)
    assert snapshot.persisted_db_datetime_utc(
        None,
        table="native_short_scope_status_v1",
        field="projection_as_of_utc",
    ) is None


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


def test_map_level_price_scale_difference_is_canonicalized_not_rejected() -> None:
    levels = _levels()
    levels[0] = {**levels[0], "canonical_unrounded_price": "102.720000000000000000"}
    build = _build(levels=levels)
    assert build.rows[0]["context_freshness_status"] == snapshot.FRESH
    assert json.loads(build.rows[0]["previous_target_levels_json"]) == ["102.72"]


def test_publish_is_atomic_consistent_and_unchanged_is_not_duplicated(tmp_path: Path) -> None:
    build = _build()
    first = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF + timedelta(minutes=1),
    authorization=_NS_AUTH)
    second = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF + timedelta(hours=4),
        publication_ts_utc=AS_OF + timedelta(hours=4, minutes=1),
    authorization=_NS_AUTH)
    assert first.status == "PUBLISHED"
    assert second.status == "UNCHANGED"
    assert list((tmp_path / "snapshots").iterdir()) == [tmp_path / "snapshots" / build.snapshot_id]

    manifest = json.loads(first.manifest_path.read_text())
    bundle = json.loads(first.bundle_path.read_text())
    assert manifest["snapshot_id"] == bundle["envelope"]["snapshot_id"] == build.snapshot_id
    assert manifest["row_count"] == len(bundle["rows"]) == 1
    assert hashlib.sha256(first.rows_path.read_bytes()).hexdigest() == manifest["rows_csv_digest"].split(":", 1)[1]
    assert hashlib.sha256(first.bundle_path.read_bytes()).hexdigest() == manifest["snapshot_bundle_digest"].split(":", 1)[1]


@pytest.mark.parametrize("artifact", ["rows", "bundle"])
def test_unchanged_rejects_missing_or_corrupt_immutable_artifact(tmp_path: Path, artifact: str) -> None:
    build = _build()
    published = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
    authorization=_NS_AUTH)
    path = published.rows_path if artifact == "rows" else published.bundle_path
    if artifact == "rows":
        path.unlink()
        expected = "missing immutable"
    else:
        path.write_bytes(b"corrupt")
        expected = "bundle is unreadable"
    with pytest.raises(snapshot.SnapshotContractError, match=expected):
        snapshot.publish_snapshot(
            build,
            output_dir=tmp_path,
            generated_ts_utc=AS_OF,
            publication_ts_utc=AS_OF,
        authorization=_NS_AUTH)


@pytest.mark.parametrize("existing_artifact", ["rows", "bundle"])
def test_preexisting_partial_snapshot_directory_is_completed_before_manifest(
    tmp_path: Path,
    existing_artifact: str,
) -> None:
    build = _build()
    snapshot_dir = tmp_path / "snapshots" / build.snapshot_id
    snapshot_dir.mkdir(parents=True)
    rows_path = snapshot_dir / snapshot.ROWS_NAME
    bundle_path = snapshot_dir / snapshot.BUNDLE_NAME
    if existing_artifact == "rows":
        rows_path.write_bytes(snapshot.render_rows_csv(build.rows))
    else:
        envelope = snapshot.build_envelope(build, generated_ts_utc=AS_OF, publication_ts_utc=AS_OF)
        bundle_path.write_bytes(snapshot.canonical_json_bytes({"envelope": envelope, "rows": build.rows}))

    published = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
    authorization=_NS_AUTH)
    assert published.status == "PUBLISHED"
    assert published.rows_path == rows_path
    assert published.bundle_path == bundle_path
    assert published.rows_path.is_file()
    assert published.bundle_path.is_file()
    assert published.manifest_path.is_file()


def test_unchanged_rejects_self_consistent_but_semantically_wrong_rows(tmp_path: Path) -> None:
    build = _build()
    published = snapshot.publish_snapshot(
        build,
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
    authorization=_NS_AUTH)
    manifest = json.loads(published.manifest_path.read_text(encoding="utf-8"))
    wrong_rows = published.rows_path.read_bytes().replace(b"BTC", b"ETH")
    published.rows_path.write_bytes(wrong_rows)
    manifest["rows_csv_digest"] = f"sha256:{hashlib.sha256(wrong_rows).hexdigest()}"
    published.manifest_path.write_bytes(snapshot.canonical_json_bytes(manifest))

    with pytest.raises(snapshot.SnapshotContractError, match="semantic snapshot"):
        snapshot.publish_snapshot(
            build,
            output_dir=tmp_path,
            generated_ts_utc=AS_OF,
            publication_ts_utc=AS_OF,
        authorization=_NS_AUTH)


def test_preexisting_corrupt_partial_snapshot_never_publishes_manifest(tmp_path: Path) -> None:
    build = _build()
    snapshot_dir = tmp_path / "snapshots" / build.snapshot_id
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / snapshot.ROWS_NAME).write_bytes(b"corrupt")
    with pytest.raises(snapshot.SnapshotContractError, match="immutable snapshot collision"):
        snapshot.publish_snapshot(
            build,
            output_dir=tmp_path,
            generated_ts_utc=AS_OF,
            publication_ts_utc=AS_OF,
        authorization=_NS_AUTH)
    assert not (tmp_path / snapshot.MANIFEST_NAME).exists()


def test_concurrent_publisher_fails_closed_before_manifest_write(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    lock_handle = (tmp_path / snapshot.PUBLICATION_LOCK_NAME).open("a+b")
    snapshot.fcntl.flock(lock_handle.fileno(), snapshot.fcntl.LOCK_EX | snapshot.fcntl.LOCK_NB)
    try:
        with pytest.raises(snapshot.SnapshotContractError, match="lock is already held"):
            snapshot.publish_snapshot(
                _build(),
                output_dir=tmp_path,
                generated_ts_utc=AS_OF,
                publication_ts_utc=AS_OF,
            authorization=_NS_AUTH)
    finally:
        snapshot.fcntl.flock(lock_handle.fileno(), snapshot.fcntl.LOCK_UN)
        lock_handle.close()
    assert not (tmp_path / snapshot.MANIFEST_NAME).exists()


def test_atomic_write_failure_removes_temp_file(tmp_path: Path, monkeypatch) -> None:
    def fail_replace(source, destination) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(snapshot.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        snapshot.atomic_write_bytes(tmp_path / "artifact.json", b"payload")
    assert list(tmp_path.glob(".*.tmp")) == []


def test_publication_fsyncs_snapshot_and_parent_directories(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    real_fsync = snapshot._fsync_directory

    def record_fsync(path: Path) -> None:
        calls.append(path)
        real_fsync(path)

    monkeypatch.setattr(snapshot, "_fsync_directory", record_fsync)
    published = snapshot.publish_snapshot(
        _build(),
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
    authorization=_NS_AUTH)
    assert published.rows_path.parent in calls
    assert published.rows_path.parent.parent in calls
    assert tmp_path in calls


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rows_csv", "/tmp/escape.csv"),
        ("rows_csv", "../../escape.csv"),
        ("snapshot_bundle", "/tmp/escape.json"),
        ("snapshot_bundle", "snapshots/other/snapshot_bundle_v1.json"),
    ],
)
def test_manifest_artifact_paths_reject_absolute_traversal_and_identity_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    build = _build()
    relative_dir = Path("snapshots") / build.snapshot_id
    manifest = {
        "snapshot_id": build.snapshot_id,
        "rows_csv": str(relative_dir / snapshot.ROWS_NAME),
        "snapshot_bundle": str(relative_dir / snapshot.BUNDLE_NAME),
    }
    manifest[field] = value
    with pytest.raises(snapshot.SnapshotContractError, match="manifest"):
        snapshot.resolve_manifest_artifact_paths(tmp_path, manifest)


def test_failed_commit_pointer_write_preserves_last_valid_snapshot(tmp_path: Path, monkeypatch) -> None:
    first = snapshot.publish_snapshot(
        _build(),
        output_dir=tmp_path,
        generated_ts_utc=AS_OF,
        publication_ts_utc=AS_OF,
    authorization=_NS_AUTH)
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
        authorization=_NS_AUTH)
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
