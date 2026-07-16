from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.research.sector_rotation_data_v1 import (
    CandlePoint,
    UniverseAsset,
    build_reconciliation_counts,
    build_window_observations,
    snapshot_key,
)
from src.research.sector_rotation_engine_v1 import (
    MAX_ASSET_CONTRIBUTION,
    MODEL_VERSION,
    AssetWindowObservation,
    BenchmarkWindow,
    TaxonomyMembership,
    compute_sector_snapshot,
    membership_valid_at,
    normalize_multi_cluster_memberships,
)
from src.research.run_sector_rotation_replay_v1 import iter_asof_timestamps


ROOT = Path(__file__).resolve().parents[1]
ASOF = datetime(2026, 7, 16, 18, 0)


def _members(
    sector: str,
    count: int = 5,
    *,
    membership_weights: list[float] | None = None,
    liquidity_codes: list[str] | None = None,
):
    membership_weights = membership_weights or [1.0] * count
    liquidity_codes = liquidity_codes or ["MID_ALT"] * count
    return normalize_multi_cluster_memberships(
        TaxonomyMembership(
            asset_symbol=f"A{index}",
            asset_id=index,
            sector_code=sector,
            membership_weight=membership_weights[index - 1],
            liquidity_market_cap_code=liquidity_codes[index - 1],
            taxonomy_version="sector-taxonomy-v1",
        )
        for index in range(1, count + 1)
    )


def _observations(
    returns: list[float],
    *,
    baseline_returns: list[float] | None = None,
    current_volumes: list[float] | None = None,
    baseline_volumes: list[float] | None = None,
    ineligible: set[int] | None = None,
):
    baseline_returns = baseline_returns or [0.0] * len(returns)
    current_volumes = current_volumes or [200.0] * len(returns)
    baseline_volumes = baseline_volumes or [100.0] * len(returns)
    ineligible = ineligible or set()
    return {
        index: AssetWindowObservation(
            asset_id=index,
            asset_symbol=f"A{index}",
            current_return_pct=None if index in ineligible else returns[index - 1],
            baseline_return_pct=None if index in ineligible else baseline_returns[index - 1],
            current_quote_volume=None if index in ineligible else current_volumes[index - 1],
            baseline_quote_volume=None if index in ineligible else baseline_volumes[index - 1],
            current_coverage_ratio=0.0 if index in ineligible else 1.0,
            baseline_coverage_ratio=0.0 if index in ineligible else 1.0,
            latest_close_ts_utc=None if index in ineligible else ASOF,
            eligible=index not in ineligible,
            exclusion_reason="STALE_CANDLES" if index in ineligible else None,
        )
        for index in range(1, len(returns) + 1)
    }


def _benchmark(btc: float = 1.0, eth: float = 1.5) -> BenchmarkWindow:
    return BenchmarkWindow(btc, eth, ASOF, ASOF, True, None)


def _snapshot(
    returns: list[float],
    *,
    sector: str = "DEFI_YIELD",
    window: str = "1d",
    benchmark: BenchmarkWindow | None = None,
    prior_scores: tuple[float, ...] = (40.0, 35.0, 30.0),
    baseline_returns: list[float] | None = None,
    current_volumes: list[float] | None = None,
    baseline_volumes: list[float] | None = None,
    ineligible: set[int] | None = None,
    membership_weights: list[float] | None = None,
    liquidity_codes: list[str] | None = None,
):
    members = _members(
        sector,
        len(returns),
        membership_weights=membership_weights,
        liquidity_codes=liquidity_codes,
    )
    observations = _observations(
        returns,
        baseline_returns=baseline_returns,
        current_volumes=current_volumes,
        baseline_volumes=baseline_volumes,
        ineligible=ineligible,
    )
    current_total = sum(
        row.current_quote_volume or 0.0 for row in observations.values() if row.eligible
    ) + 1000.0
    baseline_total = sum(
        row.baseline_quote_volume or 0.0 for row in observations.values() if row.eligible
    ) + 1000.0
    return compute_sector_snapshot(
        sector_code=sector,
        venue="bitvavo",
        window_code=window,
        asof_ts_utc=ASOF,
        memberships=members,
        observations_by_asset=observations,
        benchmark=benchmark or _benchmark(),
        universe_current_quote_volume=current_total,
        universe_baseline_quote_volume=baseline_total,
        prior_rotation_scores=prior_scores,
    )


def test_broad_sector_advance_with_rising_volume_is_confirmed() -> None:
    row = _snapshot([3.0, 4.0, 2.5, 5.0, 3.5])
    flags = json.loads(row.supporting_flags_json)
    assert row.rotation_state == "LEADING"
    assert row.positive_participation_pct == 100.0
    assert flags["rotation_inflow_proxy"] is True
    assert flags["market_activity_rising"] is True


def test_one_asset_spike_does_not_masquerade_as_sector_rotation() -> None:
    row = _snapshot([20.0, 0.0, 0.0, -0.1, -0.1])
    flags = json.loads(row.supporting_flags_json)
    assert row.rotation_state == "INSUFFICIENT_PARTICIPATION"
    assert row.positive_participation_pct == 20.0
    assert row.confidence <= 0.49
    assert flags["rotation_inflow_proxy"] is False


def test_broad_sector_cooling_after_prior_leadership_is_explicit() -> None:
    row = _snapshot(
        [-3.0, -2.5, -4.0, -2.0, -3.5],
        benchmark=_benchmark(-1.0, -0.8),
        prior_scores=(60.0, 55.0, 50.0),
        current_volumes=[50.0] * 5,
        baseline_volumes=[200.0] * 5,
    )
    flags = json.loads(row.supporting_flags_json)
    assert row.rotation_state in {"WEAKENING", "LAGGING"}
    assert flags["market_activity_cooling"] is True
    assert flags["rotation_inflow_proxy"] is False


def test_btc_decline_with_alts_declining_harder_is_lagging() -> None:
    row = _snapshot(
        [-6.0, -5.0, -7.0, -4.0, -5.5],
        benchmark=_benchmark(-2.0, -2.5),
        prior_scores=(-80.0, -75.0, -70.0),
        current_volumes=[100.0] * 5,
        baseline_volumes=[200.0] * 5,
    )
    assert row.relative_strength_vs_btc < 0
    assert row.rotation_state == "LAGGING"


def test_eth_led_defi_improvement_keeps_benchmarks_separate() -> None:
    row = _snapshot(
        [3.0, 3.2, 2.8, 3.4, 3.1],
        benchmark=_benchmark(1.0, 4.0),
        prior_scores=(10.0, 5.0, 0.0),
    )
    assert row.relative_strength_vs_btc > 0
    assert row.relative_strength_vs_eth < 0
    assert row.rotation_state in {"IMPROVING", "LEADING"}


def test_stale_and_missing_members_fail_low_coverage_closed() -> None:
    row = _snapshot([3.0] * 5, ineligible={3, 4, 5})
    assert row.eligible_member_count == 2
    assert row.coverage_ratio == 0.4
    assert row.rotation_state == "DATA_UNAVAILABLE"
    assert row.confidence == 0.0


def test_dominant_large_member_has_capped_influence() -> None:
    row = _snapshot(
        [25.0, 1.0, 1.0, 1.0, 1.0],
        membership_weights=[1.0, 0.05, 0.05, 0.05, 0.05],
        liquidity_codes=["MAJOR", "MICRO_ALT", "MICRO_ALT", "MICRO_ALT", "MICRO_ALT"],
    )
    flags = json.loads(row.supporting_flags_json)
    assert row.dominant_member_weight_pct <= MAX_ASSET_CONTRIBUTION * 100 + 1e-8
    assert flags["asset_contribution_cap_applied"] is True


def test_conflicting_1h_and_1d_states_remain_separate() -> None:
    fast = _snapshot([2.0] * 5, window="1h", benchmark=_benchmark(0.1, 0.2))
    slow = _snapshot([-4.0] * 5, window="1d", benchmark=_benchmark(-1.0, -1.0), prior_scores=(-30.0,) * 3)
    assert fast.window_code == "1h"
    assert slow.window_code == "1d"
    assert fast.rotation_state in {"IMPROVING", "LEADING"}
    assert slow.rotation_state in {"WEAKENING", "LAGGING"}


def test_multi_cluster_membership_normalizes_total_asset_influence() -> None:
    rows = normalize_multi_cluster_memberships(
        [
            TaxonomyMembership("LINK", 10, "ORACLE", 1.0, "LARGE_ALT"),
            TaxonomyMembership("LINK", 10, "RWA_INFRA", 0.7, "LARGE_ALT", "SECONDARY"),
            TaxonomyMembership("LINK", 10, "SETTLEMENT_INTEROPERABILITY", 0.5, "LARGE_ALT", "SECONDARY"),
        ]
    )
    assert sum(row.normalized_membership_weight for row in rows) == pytest.approx(1.0)
    assert len({row.asset_id for row in rows}) == 1


@pytest.mark.parametrize("missing", ["BTC", "ETH"])
def test_missing_benchmark_fails_all_sector_metrics_closed(missing: str) -> None:
    benchmark = BenchmarkWindow(
        None if missing == "BTC" else 1.0,
        None if missing == "ETH" else 1.0,
        None if missing == "BTC" else ASOF,
        None if missing == "ETH" else ASOF,
        False,
        f"{missing}_BENCHMARK_UNAVAILABLE",
    )
    row = _snapshot([3.0] * 5, benchmark=benchmark)
    assert row.rotation_state == "DATA_UNAVAILABLE"
    assert row.weighted_return is None
    assert row.confidence == 0.0


def test_first_snapshot_exposes_insufficient_persistence_history() -> None:
    row = _snapshot([3.0] * 5, prior_scores=())
    assert row.persistence_score == 0.0
    assert row.persistence_history_count == 0
    assert row.persistence_status == "INSUFFICIENT_HISTORY"
    assert json.loads(row.supporting_flags_json)["persistence_history_insufficient"] is True


def test_deterministic_rerun_is_idempotent() -> None:
    first = _snapshot([3.0, 4.0, 2.5, 5.0, 3.5])
    second = _snapshot([3.0, 4.0, 2.5, 5.0, 3.5])
    assert first == second
    counts = build_reconciliation_counts([second], {snapshot_key(first): first.input_hash})
    assert counts.inserts == 0
    assert counts.updates == 0
    assert counts.unchanged == 1
    changed = _snapshot([3.0, 4.0, 2.5, 5.0, 4.0])
    counts = build_reconciliation_counts([changed], {snapshot_key(first): first.input_hash})
    assert counts.updates == 1


def test_taxonomy_validity_interval_is_point_in_time_and_end_exclusive() -> None:
    start = ASOF - timedelta(days=2)
    end = ASOF + timedelta(days=2)
    assert membership_valid_at(start, end, ASOF) is True
    assert membership_valid_at(start, end, start - timedelta(microseconds=1)) is False
    assert membership_valid_at(start, end, end) is False


def test_unclassified_never_receives_leading_state() -> None:
    row = _snapshot([10.0] * 5, sector="UNCLASSIFIED", benchmark=_benchmark(0.0, 0.0))
    assert row.rotation_state == "INSUFFICIENT_PARTICIPATION"
    assert json.loads(row.supporting_flags_json)["unclassified_excluded"] is True


def test_window_builder_excludes_future_and_stale_candles() -> None:
    asset = UniverseAsset(1, "A1", "A1-EUR", "MID_ALT")
    candles = []
    for hours_ago in range(49, -1, -1):
        close_ts = ASOF - timedelta(hours=hours_ago)
        candles.append(CandlePoint(1, close_ts, 100.0 + hours_ago, 10.0))
    candles.append(CandlePoint(1, ASOF + timedelta(hours=1), 9999.0, 9999.0))
    rows = build_window_observations(
        universe_assets=[asset],
        candles_by_asset={1: candles},
        asof_ts_utc=ASOF,
        window_code="1d",
    )
    assert rows[1].eligible is True
    assert rows[1].latest_close_ts_utc == ASOF
    stale_rows = build_window_observations(
        universe_assets=[asset],
        candles_by_asset={1: candles[:-4]},
        asof_ts_utc=ASOF,
        window_code="1d",
    )
    assert stale_rows[1].eligible is False


def test_replay_timestamp_sequence_is_deterministic_and_inclusive() -> None:
    assert iter_asof_timestamps(ASOF, ASOF + timedelta(hours=4), 2) == (
        ASOF,
        ASOF + timedelta(hours=2),
        ASOF + timedelta(hours=4),
    )


def test_new_modules_have_no_selection_account_or_execution_imports() -> None:
    paths = [
        ROOT / "src/research/sector_rotation_engine_v1.py",
        ROOT / "src/research/sector_rotation_data_v1.py",
        ROOT / "src/research/run_sector_rotation_engine_v1.py",
        ROOT / "src/research/run_sector_rotation_replay_v1.py",
    ]
    forbidden = ("selection", "decision_gate", "execution_planner", "executor", "broker", "account")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not [name for name in imports if any(token in name for token in forbidden)]


def test_migration_contract_and_participation_terminology() -> None:
    migration = (ROOT / "db/migrations/20260716_sector_rotation_engine_v1.sql").read_text(encoding="utf-8")
    lowered = migration.lower()
    assert "create table if not exists sector_rotation_snapshot" in lowered
    assert "sector_code, venue, window_code, asof_ts_utc, model_version" in lowered
    assert "positive_participation_pct" in lowered
    assert "negative_participation_pct" in lowered
    assert "participation_ratio" in lowered
    assert "account_id" not in lowered
    assert "order_id" not in lowered
    assert "asset_class" not in lowered
    assert MODEL_VERSION == "sector-rotation-v1.0.0"
