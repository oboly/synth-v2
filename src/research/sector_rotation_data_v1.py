from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from src.research.sector_rotation_engine_v1 import (
    AssetWindowObservation,
    BenchmarkWindow,
    MODEL_VERSION,
    PERSISTENCE_LOOKBACK,
    SOURCE_INTERVAL_CODE,
    SectorRotationSnapshot,
    TaxonomyMembership,
    WINDOW_HOURS,
    membership_valid_at,
    normalize_multi_cluster_memberships,
)


TARGET_TABLE = "sector_rotation_snapshot"
SOURCE_TABLES = (
    "asset",
    "venue_market",
    "obs_market_candle",
    "sector_definition",
    "asset_taxonomy_profile",
    "asset_cluster_membership",
    "liquidity_market_cap_definition",
)
MIGRATION_PATH = "db/migrations/20260716_sector_rotation_engine_v1.sql"
WRITE_LOCK_NAME = "synth:sector_rotation_engine_v1:writer"
MIN_WINDOW_COVERAGE_RATIO = 0.90
MAX_STALENESS_HOURS = 2
FETCH_BATCH_ROWS = 2000


@dataclass(frozen=True)
class UniverseAsset:
    asset_id: int
    asset_symbol: str
    market: str
    liquidity_market_cap_code: str


@dataclass(frozen=True)
class CandlePoint:
    asset_id: int
    close_ts_utc: datetime
    close_price: float
    volume_quote: float | None


@dataclass(frozen=True)
class ReconciliationCounts:
    inserts: int = 0
    updates: int = 0
    unchanged: int = 0
    stale: int = 0

    def __add__(self, other: "ReconciliationCounts") -> "ReconciliationCounts":
        return ReconciliationCounts(
            self.inserts + other.inserts,
            self.updates + other.updates,
            self.unchanged + other.unchanged,
            self.stale + other.stale,
        )


@dataclass(frozen=True)
class ComputeInputs:
    sector_codes: tuple[str, ...]
    memberships: tuple[Any, ...]
    universe_assets: tuple[UniverseAsset, ...]
    candles_by_asset: dict[int, tuple[CandlePoint, ...]]


def snapshot_key(snapshot: SectorRotationSnapshot) -> tuple[str, str, str, datetime, str]:
    return (
        snapshot.sector_code,
        snapshot.venue,
        snapshot.window_code,
        snapshot.asof_ts_utc,
        snapshot.model_version,
    )


def check_schema(conn: Any) -> tuple[tuple[str, ...], bool]:
    required = SOURCE_TABLES + (TARGET_TABLE,)
    placeholders = ", ".join(["%s"] * len(required))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ({placeholders})",
            list(required),
        )
        present = {str(row["TABLE_NAME"]) for row in cur.fetchall()}
    missing_source = tuple(table for table in SOURCE_TABLES if table not in present)
    return missing_source, TARGET_TABLE in present


def resolve_benchmark_asset_ids(conn: Any) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id, symbol FROM asset WHERE symbol IN ('BTC', 'ETH') ORDER BY symbol")
        rows = cur.fetchall()
    result = {str(row["symbol"]): int(row["asset_id"]) for row in rows}
    if set(result) != {"BTC", "ETH"}:
        raise RuntimeError("BTC_AND_ETH_ASSET_IDENTITIES_REQUIRED")
    return result


def resolve_latest_common_benchmark_asof(conn: Any, venue: str) -> datetime | None:
    ids = resolve_benchmark_asset_ids(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(b.close_ts_utc) AS asof_ts_utc
            FROM obs_market_candle b
            JOIN obs_market_candle e
              ON e.venue=b.venue
             AND e.interval_code=b.interval_code
             AND e.close_ts_utc=b.close_ts_utc
            WHERE b.asset_id=%s
              AND e.asset_id=%s
              AND b.venue=%s
              AND b.interval_code=%s
            """,
            (ids["BTC"], ids["ETH"], venue, SOURCE_INTERVAL_CODE),
        )
        row = cur.fetchone()
    return row["asof_ts_utc"] if row and row["asof_ts_utc"] is not None else None


def fetch_sector_codes(conn: Any) -> tuple[str, ...]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sector_code FROM sector_definition WHERE is_active=1 "
            "ORDER BY sort_order, sector_code"
        )
        return tuple(str(row["sector_code"]) for row in cur.fetchall())


def fetch_point_in_time_memberships(conn: Any, asof_ts_utc: datetime) -> tuple[Any, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                acm.asset_symbol,
                acm.asset_id,
                acm.sector_code,
                acm.membership_weight,
                acm.membership_type,
                acm.seed_schema_version,
                acm.valid_from_ts_utc,
                acm.valid_to_ts_utc,
                atp.liquidity_market_cap_code
            FROM asset_cluster_membership acm
            JOIN asset_taxonomy_profile atp ON atp.asset_symbol=acm.asset_symbol
            JOIN sector_definition sd ON sd.sector_code=acm.sector_code
            WHERE sd.is_active=1
              AND (atp.is_enabled_universe=1 OR atp.is_research_universe=1)
              AND acm.valid_from_ts_utc <= %s
              AND (acm.valid_to_ts_utc IS NULL OR %s < acm.valid_to_ts_utc)
            ORDER BY acm.asset_symbol, acm.sector_code, acm.membership_type
            """,
            (asof_ts_utc, asof_ts_utc),
        )
        rows = cur.fetchall()
    memberships = []
    for row in rows:
        if not membership_valid_at(
            row["valid_from_ts_utc"], row["valid_to_ts_utc"], asof_ts_utc
        ):
            raise RuntimeError("TAXONOMY_VALIDITY_QUERY_VIOLATION")
        memberships.append(
            TaxonomyMembership(
                asset_symbol=str(row["asset_symbol"]),
                asset_id=int(row["asset_id"]) if row["asset_id"] is not None else None,
                sector_code=str(row["sector_code"]),
                membership_weight=float(row["membership_weight"]),
                liquidity_market_cap_code=str(row["liquidity_market_cap_code"]),
                membership_type=str(row["membership_type"]),
                taxonomy_version=str(row["seed_schema_version"]),
            )
        )
    return normalize_multi_cluster_memberships(memberships)


def fetch_universe_assets(conn: Any, venue: str) -> tuple[UniverseAsset, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT atp.asset_id, atp.asset_symbol, atp.liquidity_market_cap_code, vm.market
            FROM asset_taxonomy_profile atp
            JOIN venue_market vm ON vm.base_asset_id=atp.asset_id
            WHERE (atp.is_enabled_universe=1 OR atp.is_research_universe=1)
              AND atp.asset_id IS NOT NULL
              AND vm.venue=%s
              AND vm.is_market_data_enabled=1
            ORDER BY atp.asset_id, vm.market
            """,
            (venue,),
        )
        rows = cur.fetchall()
    seen: set[int] = set()
    result = []
    for row in rows:
        asset_id = int(row["asset_id"])
        if asset_id in seen:
            continue
        seen.add(asset_id)
        result.append(
            UniverseAsset(
                asset_id=asset_id,
                asset_symbol=str(row["asset_symbol"]),
                market=str(row["market"]),
                liquidity_market_cap_code=str(row["liquidity_market_cap_code"]),
            )
        )
    return tuple(result)


def fetch_candles(
    conn: Any,
    *,
    asset_ids: Sequence[int],
    venue: str,
    oldest_ts_utc: datetime,
    asof_ts_utc: datetime,
) -> dict[int, tuple[CandlePoint, ...]]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT asset_id, close_ts_utc, close_price, volume_quote_eur
        FROM obs_market_candle
        WHERE venue=%s
          AND interval_code=%s
          AND asset_id IN ({placeholders})
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, SOURCE_INTERVAL_CODE, *asset_ids, oldest_ts_utc, asof_ts_utc]
    result: dict[int, list[CandlePoint]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(FETCH_BATCH_ROWS)
            if not rows:
                break
            for row in rows:
                asset_id = int(row["asset_id"])
                result.setdefault(asset_id, []).append(
                    CandlePoint(
                        asset_id=asset_id,
                        close_ts_utc=row["close_ts_utc"],
                        close_price=float(row["close_price"]),
                        volume_quote=(
                            float(row["volume_quote_eur"])
                            if row["volume_quote_eur"] is not None else None
                        ),
                    )
                )
    return {key: tuple(value) for key, value in result.items()}


def load_compute_inputs(
    conn: Any,
    *,
    venue: str,
    asof_ts_utc: datetime,
) -> ComputeInputs:
    sector_codes = fetch_sector_codes(conn)
    memberships = fetch_point_in_time_memberships(conn, asof_ts_utc)
    universe_assets = fetch_universe_assets(conn, venue)
    benchmark_ids = resolve_benchmark_asset_ids(conn)
    asset_ids = sorted({asset.asset_id for asset in universe_assets} | set(benchmark_ids.values()))
    oldest = asof_ts_utc - timedelta(hours=2 * max(WINDOW_HOURS.values()) + 1)
    candles = fetch_candles(
        conn,
        asset_ids=asset_ids,
        venue=venue,
        oldest_ts_utc=oldest,
        asof_ts_utc=asof_ts_utc,
    )
    return ComputeInputs(sector_codes, memberships, universe_assets, candles)


def _latest_at_or_before(candles: Sequence[CandlePoint], timestamp: datetime) -> CandlePoint | None:
    candidates = [row for row in candles if row.close_ts_utc <= timestamp]
    return candidates[-1] if candidates else None


def build_window_observations(
    *,
    universe_assets: Sequence[UniverseAsset],
    candles_by_asset: Mapping[int, Sequence[CandlePoint]],
    asof_ts_utc: datetime,
    window_code: str,
) -> dict[int, AssetWindowObservation]:
    window_h = WINDOW_HOURS[window_code]
    current_start = asof_ts_utc - timedelta(hours=window_h)
    baseline_start = asof_ts_utc - timedelta(hours=2 * window_h)
    result: dict[int, AssetWindowObservation] = {}
    for asset in universe_assets:
        candles = sorted(
            candles_by_asset.get(asset.asset_id, ()),
            key=lambda row: row.close_ts_utc,
        )
        current = [row for row in candles if current_start < row.close_ts_utc <= asof_ts_utc]
        baseline = [row for row in candles if baseline_start < row.close_ts_utc <= current_start]
        current_reference = _latest_at_or_before(candles, current_start)
        baseline_reference = _latest_at_or_before(candles, baseline_start)
        current_coverage = len(current) / window_h
        baseline_coverage = len(baseline) / window_h
        reason = None
        if not current:
            reason = "NO_CURRENT_CANDLES"
        elif not baseline:
            reason = "NO_BASELINE_CANDLES"
        elif current_reference is None or baseline_reference is None:
            reason = "MISSING_WINDOW_REFERENCE"
        elif current_coverage < MIN_WINDOW_COVERAGE_RATIO:
            reason = "LOW_CURRENT_COVERAGE"
        elif baseline_coverage < MIN_WINDOW_COVERAGE_RATIO:
            reason = "LOW_BASELINE_COVERAGE"
        elif current[-1].close_ts_utc < asof_ts_utc - timedelta(hours=MAX_STALENESS_HOURS):
            reason = "STALE_CANDLES"
        elif current_reference.close_price <= 0 or baseline_reference.close_price <= 0:
            reason = "INVALID_REFERENCE_PRICE"
        elif current[-1].close_price <= 0:
            reason = "INVALID_CURRENT_PRICE"
        elif any(row.volume_quote is None or row.volume_quote < 0 for row in current + baseline):
            reason = "MISSING_QUOTE_VOLUME"

        eligible = reason is None
        current_return = None
        baseline_return = None
        current_volume = None
        baseline_volume = None
        if eligible:
            current_return = (current[-1].close_price / current_reference.close_price - 1.0) * 100.0
            baseline_return = (current_reference.close_price / baseline_reference.close_price - 1.0) * 100.0
            current_volume = sum(float(row.volume_quote) for row in current if row.volume_quote is not None)
            baseline_volume = sum(float(row.volume_quote) for row in baseline if row.volume_quote is not None)
            if current_volume <= 0 or baseline_volume <= 0:
                eligible = False
                reason = "NON_POSITIVE_QUOTE_VOLUME"
        result[asset.asset_id] = AssetWindowObservation(
            asset_id=asset.asset_id,
            asset_symbol=asset.asset_symbol,
            current_return_pct=current_return if eligible else None,
            baseline_return_pct=baseline_return if eligible else None,
            current_quote_volume=current_volume if eligible else None,
            baseline_quote_volume=baseline_volume if eligible else None,
            current_coverage_ratio=current_coverage,
            baseline_coverage_ratio=baseline_coverage,
            latest_close_ts_utc=current[-1].close_ts_utc if current else None,
            eligible=eligible,
            exclusion_reason=reason,
        )
    return result


def build_benchmark_window(
    *,
    observations_by_asset: Mapping[int, AssetWindowObservation],
    benchmark_asset_ids: Mapping[str, int],
) -> BenchmarkWindow:
    btc = observations_by_asset.get(benchmark_asset_ids["BTC"])
    eth = observations_by_asset.get(benchmark_asset_ids["ETH"])
    if btc is None or not btc.eligible:
        return BenchmarkWindow(None, None, None, None, False, "BTC_BENCHMARK_UNAVAILABLE")
    if eth is None or not eth.eligible:
        return BenchmarkWindow(None, None, btc.latest_close_ts_utc, None, False, "ETH_BENCHMARK_UNAVAILABLE")
    return BenchmarkWindow(
        btc_return_pct=btc.current_return_pct,
        eth_return_pct=eth.current_return_pct,
        btc_asof_ts_utc=btc.latest_close_ts_utc,
        eth_asof_ts_utc=eth.latest_close_ts_utc,
        available=True,
        reason=None,
    )


def universe_quote_volume(
    observations_by_asset: Mapping[int, AssetWindowObservation],
) -> tuple[float, float]:
    eligible = [row for row in observations_by_asset.values() if row.eligible]
    return (
        sum(float(row.current_quote_volume) for row in eligible if row.current_quote_volume is not None),
        sum(float(row.baseline_quote_volume) for row in eligible if row.baseline_quote_volume is not None),
    )


def fetch_prior_rotation_scores(
    conn: Any,
    *,
    venue: str,
    before_ts_utc: datetime,
    target_table_present: bool,
) -> dict[tuple[str, str], tuple[float, ...]]:
    if not target_table_present:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sector_code, window_code, rotation_score, asof_ts_utc
            FROM sector_rotation_snapshot
            WHERE venue=%s AND model_version=%s AND asof_ts_utc<%s
            ORDER BY sector_code, window_code, asof_ts_utc DESC
            """,
            (venue, MODEL_VERSION, before_ts_utc),
        )
        rows = cur.fetchall()
    result: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (str(row["sector_code"]), str(row["window_code"]))
        bucket = result.setdefault(key, [])
        if len(bucket) < PERSISTENCE_LOOKBACK:
            bucket.append(float(row["rotation_score"]))
    return {key: tuple(values) for key, values in result.items()}


def fetch_existing_hashes(
    conn: Any,
    snapshots: Sequence[SectorRotationSnapshot],
    *,
    target_table_present: bool,
) -> dict[tuple[str, str, str, datetime, str], str]:
    if not target_table_present or not snapshots:
        return {}
    asof_values = sorted({snapshot.asof_ts_utc for snapshot in snapshots})
    placeholders = ", ".join(["%s"] * len(asof_values))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT sector_code, venue, window_code, asof_ts_utc, model_version, input_hash
            FROM sector_rotation_snapshot
            WHERE venue=%s AND model_version=%s AND asof_ts_utc IN ({placeholders})
            ORDER BY asof_ts_utc, window_code, sector_code
            """,
            [snapshots[0].venue, MODEL_VERSION, *asof_values],
        )
        rows = cur.fetchall()
    return {
        (
            str(row["sector_code"]),
            str(row["venue"]),
            str(row["window_code"]),
            row["asof_ts_utc"],
            str(row["model_version"]),
        ): str(row["input_hash"])
        for row in rows
    }


def build_reconciliation_counts(
    snapshots: Sequence[SectorRotationSnapshot],
    existing_hashes: Mapping[tuple[str, str, str, datetime, str], str],
) -> ReconciliationCounts:
    inserts = updates = unchanged = 0
    for snapshot in sorted(snapshots, key=snapshot_key):
        existing = existing_hashes.get(snapshot_key(snapshot))
        if existing is None:
            inserts += 1
        elif existing == snapshot.input_hash:
            unchanged += 1
        else:
            updates += 1
    return ReconciliationCounts(inserts, updates, unchanged, 0)


SNAPSHOT_COLUMNS = (
    "sector_code", "venue", "source_interval_code", "window_code", "asof_ts_utc",
    "weighted_return", "median_return", "positive_participation_pct",
    "negative_participation_pct", "benchmark_outperformance_pct",
    "relative_strength_vs_btc", "relative_strength_vs_eth", "sector_volume_share",
    "sector_volume_share_change", "momentum_positive_pct", "dispersion", "member_count",
    "eligible_member_count", "effective_weighted_member_count", "participation_ratio",
    "coverage_ratio", "liquidity_quality", "dominant_member_weight_pct", "persistence_score",
    "persistence_history_count", "persistence_status", "rotation_score", "rotation_state",
    "confidence", "component_json", "supporting_flags_json", "taxonomy_versions_json",
    "input_hash", "model_version", "generated_ts_utc",
)


def _snapshot_values(snapshot: SectorRotationSnapshot, generated_ts_utc: datetime) -> tuple[object, ...]:
    return tuple(
        getattr(snapshot, column) if column != "generated_ts_utc" else generated_ts_utc
        for column in SNAPSHOT_COLUMNS
    )


def write_snapshots(
    conn: Any,
    snapshots: Sequence[SectorRotationSnapshot],
    existing_hashes: Mapping[tuple[str, str, str, datetime, str], str],
    *,
    generated_ts_utc: datetime,
) -> ReconciliationCounts:
    counts = build_reconciliation_counts(snapshots, existing_hashes)
    columns = ", ".join(SNAPSHOT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(SNAPSHOT_COLUMNS))
    update_columns = [
        column for column in SNAPSHOT_COLUMNS
        if column not in {"sector_code", "venue", "window_code", "asof_ts_utc", "model_version"}
    ]
    update_sql = ", ".join(f"{column}=VALUES({column})" for column in update_columns)
    sql = (
        f"INSERT INTO sector_rotation_snapshot ({columns}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )
    with conn.cursor() as cur:
        for snapshot in sorted(snapshots, key=snapshot_key):
            existing = existing_hashes.get(snapshot_key(snapshot))
            if existing == snapshot.input_hash:
                continue
            cur.execute(sql, _snapshot_values(snapshot, generated_ts_utc))
    return counts


def acquire_write_lock(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (WRITE_LOCK_NAME,))
        row = cur.fetchone()
    if row is None or int(row.get("acquired") or 0) != 1:
        raise RuntimeError("SECTOR_ROTATION_SINGLE_WRITER_LOCK_UNAVAILABLE")


def release_write_lock(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT RELEASE_LOCK(%s) AS released", (WRITE_LOCK_NAME,))
