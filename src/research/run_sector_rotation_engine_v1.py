from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from src.common.db import get_connection
from src.research.sector_rotation_data_v1 import (
    MIGRATION_PATH,
    ReconciliationCounts,
    acquire_write_lock,
    build_benchmark_window,
    build_reconciliation_counts,
    build_window_observations,
    check_schema,
    fetch_existing_hashes,
    fetch_prior_rotation_scores,
    load_compute_inputs,
    release_write_lock,
    resolve_benchmark_asset_ids,
    resolve_latest_common_benchmark_asof,
    universe_quote_volume,
    write_snapshots,
)
from src.research.sector_rotation_engine_v1 import (
    MAX_ASSET_CONTRIBUTION,
    MAX_LIQUIDITY_WEIGHT,
    MIN_COVERAGE_RATIO,
    MIN_EFFECTIVE_MEMBERS,
    MIN_ELIGIBLE_MEMBERS,
    MIN_PARTICIPATION_RATIO,
    MODEL_VERSION,
    SCORE_WEIGHTS,
    SOURCE_INTERVAL_CODE,
    WINDOW_HOURS,
    WINDOW_ORDER,
    SectorRotationSnapshot,
    compute_sector_snapshot,
)


RUNNER_NAME = "sector_rotation_engine_v1"
DEFAULT_VENUE = "bitvavo"
EVIDENCE_SECTORS = (
    "DEFI_LENDING",
    "RWA",
    "AI_COMPUTE",
    "PERP_DEX",
    "INSTITUTIONAL_FINANCE_INFRA",
)


@dataclass(frozen=True)
class ComputeResult:
    snapshots: tuple[SectorRotationSnapshot, ...]
    benchmark_rows: tuple[tuple[str, datetime | None, datetime | None, bool, str | None], ...]
    sector_count: int
    membership_count: int
    universe_asset_count: int
    candle_count: int


def parse_utc_hour(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("as-of timestamp must be aligned to a UTC hour")
    return parsed


def compute_asof(
    conn: Any,
    *,
    venue: str,
    asof_ts_utc: datetime,
    window_codes: Sequence[str],
    target_table_present: bool,
) -> ComputeResult:
    inputs = load_compute_inputs(conn, venue=venue, asof_ts_utc=asof_ts_utc)
    benchmark_ids = resolve_benchmark_asset_ids(conn)
    prior_scores = fetch_prior_rotation_scores(
        conn,
        venue=venue,
        before_ts_utc=asof_ts_utc,
        target_table_present=target_table_present,
    )
    snapshots: list[SectorRotationSnapshot] = []
    benchmark_rows = []
    for window_code in window_codes:
        observations = build_window_observations(
            universe_assets=inputs.universe_assets,
            candles_by_asset=inputs.candles_by_asset,
            asof_ts_utc=asof_ts_utc,
            window_code=window_code,
        )
        benchmark = build_benchmark_window(
            observations_by_asset=observations,
            benchmark_asset_ids=benchmark_ids,
        )
        current_volume, baseline_volume = universe_quote_volume(observations)
        benchmark_rows.append(
            (
                window_code,
                benchmark.btc_asof_ts_utc,
                benchmark.eth_asof_ts_utc,
                benchmark.available,
                benchmark.reason,
            )
        )
        for sector_code in inputs.sector_codes:
            snapshots.append(
                compute_sector_snapshot(
                    sector_code=sector_code,
                    venue=venue,
                    window_code=window_code,
                    asof_ts_utc=asof_ts_utc,
                    memberships=inputs.memberships,
                    observations_by_asset=observations,
                    benchmark=benchmark,
                    universe_current_quote_volume=current_volume,
                    universe_baseline_quote_volume=baseline_volume,
                    prior_rotation_scores=prior_scores.get((sector_code, window_code), ()),
                )
            )
    snapshots.sort(key=lambda row: (WINDOW_ORDER.index(row.window_code), row.sector_code))
    return ComputeResult(
        snapshots=tuple(snapshots),
        benchmark_rows=tuple(benchmark_rows),
        sector_count=len(inputs.sector_codes),
        membership_count=len(inputs.memberships),
        universe_asset_count=len(inputs.universe_assets),
        candle_count=sum(len(rows) for rows in inputs.candles_by_asset.values()),
    )


def _fmt_ts(value: datetime | None) -> str:
    return "none" if value is None else value.isoformat() + "Z"


def print_compute_report(result: ComputeResult, counts: ReconciliationCounts) -> None:
    print(
        "SOURCE_COUNTS "
        f"sectors={result.sector_count} memberships={result.membership_count} "
        f"universe_assets={result.universe_asset_count} candles={result.candle_count}"
    )
    for window_code, btc_ts, eth_ts, available, reason in result.benchmark_rows:
        print(
            f"BENCHMARK window={window_code} btc_ts={_fmt_ts(btc_ts)} "
            f"eth_ts={_fmt_ts(eth_ts)} available={int(available)} reason={reason or 'none'}"
        )
    for window_code in WINDOW_ORDER:
        rows = [row for row in result.snapshots if row.window_code == window_code]
        if not rows:
            continue
        states = Counter(row.rotation_state for row in rows)
        available = sum(
            state not in {"DATA_UNAVAILABLE", "INSUFFICIENT_PARTICIPATION"}
            for state in (row.rotation_state for row in rows)
        )
        print(
            f"WINDOW window={window_code} sectors={len(rows)} available={available} "
            f"insufficient={states['INSUFFICIENT_PARTICIPATION']} "
            f"unavailable={states['DATA_UNAVAILABLE']} states="
            + json.dumps(dict(sorted(states.items())), sort_keys=True, separators=(",", ":"))
        )
        print(
            f"INSUFFICIENT_SECTORS window={window_code} sectors="
            + ",".join(
                row.sector_code
                for row in rows
                if row.rotation_state == "INSUFFICIENT_PARTICIPATION"
            )
        )
        print(
            f"UNAVAILABLE_SECTORS window={window_code} sectors="
            + ",".join(
                row.sector_code
                for row in rows
                if row.rotation_state == "DATA_UNAVAILABLE"
            )
        )
    print(
        "RECONCILIATION "
        f"inserts={counts.inserts} updates={counts.updates} "
        f"unchanged={counts.unchanged} stale={counts.stale}"
    )
    for sector_code in EVIDENCE_SECTORS:
        for row in (item for item in result.snapshots if item.sector_code == sector_code):
            components = json.loads(row.component_json)
            scores = components.get("score_components", {})
            print(
                f"EVIDENCE sector={sector_code} window={row.window_code} state={row.rotation_state} "
                f"score={row.rotation_score:+.4f} weighted_return={row.weighted_return} "
                f"positive_participation_pct={row.positive_participation_pct} "
                f"negative_participation_pct={row.negative_participation_pct} "
                f"rs_btc={row.relative_strength_vs_btc} rs_eth={row.relative_strength_vs_eth} "
                f"volume_share_change={row.sector_volume_share_change} "
                f"eligible={row.eligible_member_count}/{row.member_count} "
                f"effective={row.effective_weighted_member_count:.4f} components="
                + json.dumps(scores, sort_keys=True, separators=(",", ":"))
            )
    dominated = sorted(
        (
            row.window_code,
            row.sector_code,
            row.dominant_member_weight_pct,
            row.eligible_member_count,
            row.rotation_state,
        )
        for row in result.snapshots
        if row.dominant_member_weight_pct is not None
        and row.dominant_member_weight_pct > MAX_ASSET_CONTRIBUTION * 100 + 1e-8
    )
    print(f"DOMINATED_SECTORS count={len(dominated)}")
    for window_code, sector_code, weight, eligible, state in dominated:
        print(
            f"DOMINATED window={window_code} sector={sector_code} "
            f"dominant_member_weight_pct={weight:.4f} eligible={eligible} state={state}"
        )


def print_validation_contract() -> None:
    print(
        f"MODEL model_version={MODEL_VERSION} source_interval={SOURCE_INTERVAL_CODE} "
        f"windows={','.join(WINDOW_ORDER)}"
    )
    print("SCORE_WEIGHTS " + json.dumps(SCORE_WEIGHTS, sort_keys=True, separators=(",", ":")))
    print(
        "GUARDRAILS "
        f"max_asset_contribution={MAX_ASSET_CONTRIBUTION} "
        f"max_liquidity_weight={MAX_LIQUIDITY_WEIGHT} "
        f"min_eligible_members={MIN_ELIGIBLE_MEMBERS} "
        f"min_effective_members={MIN_EFFECTIVE_MEMBERS} "
        f"min_coverage_ratio={MIN_COVERAGE_RATIO} "
        f"min_participation_ratio={MIN_PARTICIPATION_RATIO}"
    )
    print(f"MIGRATION path={MIGRATION_PATH}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministic research-only sector proxy-rotation engine v1"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-db", action="store_true")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--as-of-ts", default=None)
    parser.add_argument("--window", action="append", choices=list(WINDOW_ORDER), default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "validate-only" if args.validate_only else ("dry-run" if args.dry_run else "write-db")
    started = time.perf_counter()
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} scope=sector+venue+window workers=1",
        flush=True,
    )
    print(
        "SAFETY broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        flush=True,
    )
    if args.validate_only:
        print_validation_contract()
        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} db_connections=0 db_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0

    conn = None
    lock_acquired = False
    try:
        conn = get_connection()
        missing_source, target_present = check_schema(conn)
        if missing_source:
            raise RuntimeError(f"SOURCE_SCHEMA_MISSING:{','.join(missing_source)}")
        if args.write_db and not target_present:
            raise RuntimeError(f"MIGRATION_REQUIRED:{MIGRATION_PATH}")
        if args.write_db:
            acquire_write_lock(conn)
            lock_acquired = True
        asof_ts_utc = (
            parse_utc_hour(args.as_of_ts)
            if args.as_of_ts
            else resolve_latest_common_benchmark_asof(conn, args.venue)
        )
        if asof_ts_utc is None:
            raise RuntimeError("NO_COMMON_BTC_ETH_BENCHMARK_TIMESTAMP")
        windows = tuple(args.window or WINDOW_ORDER)
        print(
            f"PHASE_START name=compute asof_ts_utc={asof_ts_utc.isoformat()}Z "
            f"venue={args.venue} windows={','.join(windows)} target_table_present={int(target_present)}",
            flush=True,
        )
        phase_started = time.perf_counter()
        result = compute_asof(
            conn,
            venue=args.venue,
            asof_ts_utc=asof_ts_utc,
            window_codes=windows,
            target_table_present=target_present,
        )
        print(
            f"PHASE_END name=compute rows={len(result.snapshots)} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )
        existing = fetch_existing_hashes(
            conn, result.snapshots, target_table_present=target_present
        )
        counts = build_reconciliation_counts(result.snapshots, existing)
        if args.write_db:
            counts = write_snapshots(
                conn,
                result.snapshots,
                existing,
                generated_ts_utc=datetime.now(UTC).replace(tzinfo=None),
            )
            conn.commit()
            transaction = "committed"
        else:
            conn.rollback()
            transaction = "rolled_back"
        print_compute_report(result, counts)
        if not target_present:
            print(f"TARGET_SCHEMA status=missing migration={MIGRATION_PATH}")
        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} transaction={transaction} "
            f"db_writes={int(args.write_db)} rows={len(result.snapshots)} "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        print(
            f"FAILED runner={RUNNER_NAME} mode={mode} reason={type(exc).__name__}:{exc} "
            f"db_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            if lock_acquired:
                try:
                    release_write_lock(conn)
                except Exception as exc:
                    print(f"LOCK_RELEASE_WARNING reason={type(exc).__name__}:{exc}")
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
