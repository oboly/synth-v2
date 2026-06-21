"""
FFG Research Universe Import v1

Reads ffg_research_universe_seed_v1.json and persists it into three research-only tables.
Idempotent — safe to re-run; the imported universe is reconciled to the seed for that universe_key.

Boundary:
    - Research-only. No asset.is_enabled changes. No account plan rows. No orders.
    - Bitvavo EUR resolution is derived from local DB market data only.
    - Beta flow snapshot is stored with source_confidence=low and timeframe=UNVERIFIED_BETA.
    - No decision_gate, execution_planner, executor, or broker calls.

Safety markers:
    broker_private_calls=0
    broker_writes=0
    order_submission=0
    live_orders=0
    decision_gate=none
    execution_planner=none
    executor=none

Usage:
    python -m src.research.run_ffg_research_universe_import_v1 --seed-file PATH --validate-only
    python -m src.research.run_ffg_research_universe_import_v1 --seed-file PATH --dry-run
    python -m src.research.run_ffg_research_universe_import_v1 --seed-file PATH --write-db
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from src.common.db import get_connection

UNIVERSE_KEY = "FFG_RESEARCH_UNIVERSE_V1"
SOURCE_NAME = "FFG"

EXPECTED_SOURCE_ROWS = 109
EXPECTED_CANONICAL = 102
EXPECTED_MEMBERS = 100
EXPECTED_EXCLUDED = 2

BITVAVO_VENUE = "bitvavo"
MIGRATION_PATH = "db/migrations/20260620_ffg_research_universe_v1.sql"
PRECHECK_FAILURE_EXIT_CODE = 2
REQUIRED_RESEARCH_TABLES = (
    "ffg_research_universe_member_v1",
    "ffg_research_source_pair_v1",
    "ffg_external_signal_snapshot_v1",
)


class ResearchUniversePreflightError(Exception):
    def __init__(self, reason: str, *, missing_tables: Iterable[str] | None = None, detail: str | None = None) -> None:
        self.reason = reason
        self.missing_tables = tuple(missing_tables or ())
        self.detail = detail or ""
        super().__init__(self.format_message())

    def format_message(self) -> str:
        parts = [f"reason={self.reason}"]
        if self.missing_tables:
            parts.append(f"missing_tables={','.join(self.missing_tables)}")
        parts.append(f"migration={MIGRATION_PATH}")
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Pure-data helpers (no DB, fully testable)
# ---------------------------------------------------------------------------

def load_seed(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validate_seed_totals(assets: list[dict[str, Any]]) -> None:
    source_rows = sum(a["source_row_count"] for a in assets)
    canonical = len(assets)
    excluded = sum(1 for a in assets if a["research_status"] == "EXCLUDED")
    members = canonical - excluded

    mismatches: list[str] = []
    if source_rows != EXPECTED_SOURCE_ROWS:
        mismatches.append(f"source_rows: expected {EXPECTED_SOURCE_ROWS}, got {source_rows}")
    if canonical != EXPECTED_CANONICAL:
        mismatches.append(f"canonical: expected {EXPECTED_CANONICAL}, got {canonical}")
    if excluded != EXPECTED_EXCLUDED:
        mismatches.append(f"excluded: expected {EXPECTED_EXCLUDED}, got {excluded}")
    if members != EXPECTED_MEMBERS:
        mismatches.append(f"members: expected {EXPECTED_MEMBERS}, got {members}")

    if mismatches:
        raise ValueError("Seed total mismatch — do not silently change counts:\n  " + "\n  ".join(mismatches))


def validate_canonical_uniqueness(assets: Iterable[dict[str, Any]]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for asset in assets:
        symbol = str(asset["source_symbol"]).strip().upper()
        if symbol in seen:
            duplicates.add(symbol)
        seen.add(symbol)
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(
            f"Duplicate canonical source_symbol entries are not allowed in the seed: {joined}"
        )


def validate_seed(assets: list[dict[str, Any]]) -> None:
    validate_canonical_uniqueness(assets)
    validate_seed_totals(assets)


def derive_bitvavo_resolution(
    source_symbol: str,
    identity_status: str,
    bitvavo_asset_ids: set[int],
    symbol_to_asset_id: dict[str, int],
) -> str:
    """Derive bitvavo_eur_resolution from local DB state.

    Priority:
      1. requires_identity_resolution / do_not_import → REQUIRES_MANUAL_RESOLUTION
      2. symbol not in asset table → UNAVAILABLE_ON_BITVAVO
      3. symbol in asset table but no Bitvavo market data → UNAVAILABLE_ON_BITVAVO
      4. symbol in asset table with Bitvavo market data → RESOLVED
    """
    if identity_status in ("requires_identity_resolution", "do_not_import"):
        return "REQUIRES_MANUAL_RESOLUTION"
    asset_id = symbol_to_asset_id.get(source_symbol.upper())
    if asset_id is None:
        return "UNAVAILABLE_ON_BITVAVO"
    if asset_id in bitvavo_asset_ids:
        return "RESOLVED"
    return "UNAVAILABLE_ON_BITVAVO"


def extract_source_exchange(source_pair: str) -> str:
    """Extract exchange prefix from 'EXCHANGE:PAIRUSDT' → 'EXCHANGE'."""
    if ":" in source_pair:
        return source_pair.split(":", 1)[0].upper()
    return ""


def normalize_member_rows(member_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize authoritative member rows per (universe_key, source_symbol)."""
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in member_rows:
        key = (str(row["universe_key"]), str(row["source_symbol"]).upper())
        if key in deduped:
            raise ValueError(
                f"Duplicate member row for universe_key={key[0]} source_symbol={key[1]}"
            )
        normalized = dict(row)
        normalized["source_symbol"] = key[1]
        deduped[key] = normalized
    return [deduped[key] for key in sorted(deduped)]


def normalize_source_pair_rows(
    universe_key: str,
    assets: Iterable[dict[str, Any]],
) -> list[tuple[str, str, str, str]]:
    """Return deduplicated, deterministic (universe_key, source_symbol, source_pair, source_exchange) rows."""
    normalized: set[tuple[str, str, str, str]] = set()
    for asset in assets:
        source_symbol = str(asset["source_symbol"]).upper()
        for raw_pair in asset.get("source_pairs") or []:
            source_pair = str(raw_pair).strip().upper()
            if not source_pair:
                continue
            normalized.add((universe_key, source_symbol, source_pair, extract_source_exchange(source_pair)))
    return sorted(normalized)


# ---------------------------------------------------------------------------
# DB-resolution helpers
# ---------------------------------------------------------------------------

def fetch_symbol_to_asset_id(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, asset_id FROM asset")
        return {row["symbol"].upper(): row["asset_id"] for row in cur.fetchall()}


def fetch_bitvavo_asset_ids(conn) -> set[int]:
    """Asset IDs that have at least one Bitvavo candle or ticker record."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT asset_id FROM obs_venue_ticker_24h WHERE venue = %s",
            (BITVAVO_VENUE,),
        )
        ids: set[int] = {row["asset_id"] for row in cur.fetchall()}
        cur.execute(
            "SELECT DISTINCT asset_id FROM obs_market_candle WHERE venue = %s",
            (BITVAVO_VENUE,),
        )
        ids.update(row["asset_id"] for row in cur.fetchall())
    return ids


def fetch_existing_member_symbols(conn, universe_key: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_symbol
            FROM ffg_research_universe_member_v1
            WHERE universe_key = %s
            """,
            (universe_key,),
        )
        return {str(row["source_symbol"]).upper() for row in cur.fetchall()}


def fetch_existing_source_pairs(conn, universe_key: str) -> set[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_symbol, source_pair
            FROM ffg_research_source_pair_v1
            WHERE universe_key = %s
            """,
            (universe_key,),
        )
        return {
            (str(row["source_symbol"]).upper(), str(row["source_pair"]).upper())
            for row in cur.fetchall()
        }


def assert_required_research_tables(conn) -> None:
    placeholders = ", ".join(["%s"] * len(REQUIRED_RESEARCH_TABLES))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name IN ({placeholders})
            """,
            REQUIRED_RESEARCH_TABLES,
        )
        present = {str(row["table_name"]) for row in cur.fetchall()}
    missing = [table for table in REQUIRED_RESEARCH_TABLES if table not in present]
    if missing:
        raise ResearchUniversePreflightError(
            "MIGRATION_REQUIRED",
            missing_tables=missing,
        )


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def upsert_member(conn, row: dict[str, Any], dry_run: bool) -> None:
    sql = """
        INSERT INTO ffg_research_universe_member_v1 (
            universe_key, source_symbol, asset_id, source_name,
            ffg_virtual_portfolio_return_pct, research_status, identity_status,
            priority_tier, bitvavo_eur_resolution, account_plan_default,
            theme_tags, exclusion_reason, seed_schema_version
        ) VALUES (
            %(universe_key)s, %(source_symbol)s, %(asset_id)s, %(source_name)s,
            %(ffg_virtual_portfolio_return_pct)s, %(research_status)s, %(identity_status)s,
            %(priority_tier)s, %(bitvavo_eur_resolution)s, %(account_plan_default)s,
            %(theme_tags)s, %(exclusion_reason)s, %(seed_schema_version)s
        )
        ON DUPLICATE KEY UPDATE
            asset_id = VALUES(asset_id),
            source_name = VALUES(source_name),
            ffg_virtual_portfolio_return_pct = VALUES(ffg_virtual_portfolio_return_pct),
            research_status = VALUES(research_status),
            identity_status = VALUES(identity_status),
            priority_tier = VALUES(priority_tier),
            bitvavo_eur_resolution = VALUES(bitvavo_eur_resolution),
            account_plan_default = VALUES(account_plan_default),
            theme_tags = VALUES(theme_tags),
            exclusion_reason = VALUES(exclusion_reason),
            seed_schema_version = VALUES(seed_schema_version),
            updated_at_utc = CURRENT_TIMESTAMP(6)
    """
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(sql, row)


def delete_member_symbols(conn, universe_key: str, source_symbols: Iterable[str], dry_run: bool) -> None:
    symbols = sorted({str(symbol).upper() for symbol in source_symbols})
    if dry_run or not symbols:
        return
    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"""
        DELETE FROM ffg_research_universe_member_v1
        WHERE universe_key = %s
          AND source_symbol IN ({placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, (universe_key, *symbols))


def delete_source_pairs(conn, universe_key: str, source_pairs: Iterable[tuple[str, str]], dry_run: bool) -> None:
    normalized = sorted({(str(symbol).upper(), str(pair).upper()) for symbol, pair in source_pairs})
    if dry_run or not normalized:
        return
    placeholders = ", ".join(["(%s, %s)"] * len(normalized))
    params: list[str] = [universe_key]
    for symbol, pair in normalized:
        params.extend([symbol, pair])
    sql = f"""
        DELETE FROM ffg_research_source_pair_v1
        WHERE universe_key = %s
          AND (source_symbol, source_pair) IN ({placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))


def synchronize_members(conn, universe_key: str, member_rows: Iterable[dict[str, Any]], dry_run: bool) -> set[str]:
    normalized_rows = normalize_member_rows(member_rows)
    incoming_symbols = {str(row["source_symbol"]).upper() for row in normalized_rows}
    existing_symbols = fetch_existing_member_symbols(conn, universe_key)
    stale_symbols = existing_symbols - incoming_symbols

    for row in normalized_rows:
        upsert_member(conn, row, dry_run=dry_run)
    delete_member_symbols(conn, universe_key, stale_symbols, dry_run=dry_run)
    return stale_symbols


def synchronize_source_pairs(
    conn,
    universe_key: str,
    assets: Iterable[dict[str, Any]],
    dry_run: bool,
) -> set[tuple[str, str]]:
    normalized_rows = normalize_source_pair_rows(universe_key, assets)
    incoming_pairs = {(source_symbol, source_pair) for _, source_symbol, source_pair, _ in normalized_rows}
    existing_pairs = fetch_existing_source_pairs(conn, universe_key)
    stale_pairs = existing_pairs - incoming_pairs

    if not dry_run:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO ffg_research_source_pair_v1
                    (universe_key, source_symbol, source_pair, source_exchange)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    source_exchange = VALUES(source_exchange)
            """
            for row in normalized_rows:
                cur.execute(sql, row)
    delete_source_pairs(conn, universe_key, stale_pairs, dry_run=dry_run)
    return stale_pairs


def upsert_signal_snapshot(conn, snapshot: dict[str, Any], dry_run: bool) -> None:
    sql = """
        INSERT INTO ffg_external_signal_snapshot_v1 (
            source, captured_on, timeframe, source_confidence,
            reported_inflow_count, captured_inflow_count,
            reported_outflow_count, inflows, outflow_symbols, snapshot_notes
        ) VALUES (
            %(source)s, %(captured_on)s, %(timeframe)s, %(source_confidence)s,
            %(reported_inflow_count)s, %(captured_inflow_count)s,
            %(reported_outflow_count)s, %(inflows)s, %(outflow_symbols)s, %(snapshot_notes)s
        )
        ON DUPLICATE KEY UPDATE
            source_confidence = VALUES(source_confidence),
            reported_inflow_count = VALUES(reported_inflow_count),
            captured_inflow_count = VALUES(captured_inflow_count),
            reported_outflow_count = VALUES(reported_outflow_count),
            inflows = VALUES(inflows),
            outflow_symbols = VALUES(outflow_symbols),
            snapshot_notes = VALUES(snapshot_notes)
    """
    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(sql, snapshot)


# ---------------------------------------------------------------------------
# Verification query
# ---------------------------------------------------------------------------

def print_verification(conn, universe_key: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM ffg_research_source_pair_v1 WHERE universe_key = %s",
            (universe_key,),
        )
        source_pair_count = cur.fetchone()["n"]

        cur.execute(
            """
            SELECT
                COUNT(*) AS canonical_total,
                SUM(research_status = 'EXCLUDED') AS excluded_count,
                SUM(research_status = 'RESEARCH_UNIVERSE') AS member_count,
                SUM(bitvavo_eur_resolution = 'RESOLVED') AS resolved_count,
                SUM(bitvavo_eur_resolution = 'UNAVAILABLE_ON_BITVAVO') AS unavailable_count,
                SUM(bitvavo_eur_resolution = 'REQUIRES_MANUAL_RESOLUTION') AS manual_count,
                SUM(bitvavo_eur_resolution = 'PENDING_LOCAL_MARKET_SYNC') AS pending_count
            FROM ffg_research_universe_member_v1
            WHERE universe_key = %s
            """,
            (universe_key,),
        )
        row = cur.fetchone()

    print(f"\n--- FFG Research Universe Verification: {universe_key} ---")
    print(f"  source_pairs:         {source_pair_count:>4}  (expected {EXPECTED_SOURCE_ROWS})")
    print(f"  canonical_symbols:    {row['canonical_total']:>4}  (expected {EXPECTED_CANONICAL})")
    print(f"  research_universe:    {row['member_count']:>4}  (expected {EXPECTED_MEMBERS})")
    print(f"  excluded:             {row['excluded_count']:>4}  (expected {EXPECTED_EXCLUDED})")
    print(f"  bitvavo RESOLVED:     {row['resolved_count']:>4}")
    print(f"  bitvavo UNAVAILABLE:  {row['unavailable_count']:>4}")
    print(f"  bitvavo MANUAL:       {row['manual_count']:>4}")
    print(f"  bitvavo PENDING:      {row['pending_count']:>4}")
    print(f"  account rows modified: 0")
    print(f"  orders generated:      0")
    print("--- End verification ---\n")


def synchronize_universe(
    conn,
    universe_key: str,
    member_rows: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    beta_flow: dict[str, Any],
    dry_run: bool,
) -> tuple[set[str], set[tuple[str, str]], int]:
    stale_member_symbols = synchronize_members(conn, universe_key, member_rows, dry_run=dry_run)
    stale_source_pairs = synchronize_source_pairs(conn, universe_key, assets, dry_run=dry_run)
    normalized_source_pair_rows = normalize_source_pair_rows(universe_key, assets)

    if beta_flow:
        snapshot_row = {
            "source": SOURCE_NAME,
            "captured_on": beta_flow.get("captured_on"),
            "timeframe": beta_flow.get("timeframe", "UNVERIFIED_BETA"),
            "source_confidence": beta_flow.get("source_confidence", "low"),
            "reported_inflow_count": beta_flow.get("reported_inflow_count", 0),
            "captured_inflow_count": len(beta_flow.get("inflows") or []),
            "reported_outflow_count": beta_flow.get("reported_outflow_count", 0),
            "inflows": json.dumps(beta_flow.get("inflows") or []),
            "outflow_symbols": json.dumps(beta_flow.get("captured_outflow_symbols") or []),
            "snapshot_notes": json.dumps(beta_flow.get("notes") or []),
        }
        upsert_signal_snapshot(conn, snapshot_row, dry_run=dry_run)
        print(f"  Beta flow snapshot: timeframe={snapshot_row['timeframe']} confidence={snapshot_row['source_confidence']}")

    return stale_member_symbols, stale_source_pairs, len(normalized_source_pair_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import FFG research universe seed into Synth research tables."
    )
    parser.add_argument("--seed-file", required=True, type=Path, help="Path to ffg_research_universe_seed_v1.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true", help="Seed-only validation; no DB connection required.")
    mode.add_argument("--dry-run", action="store_true", help="DB-backed import plan; no writes.")
    mode.add_argument("--write-db", action="store_true", help="Apply the DB-backed import plan transactionally.")
    args = parser.parse_args()

    mode_label = (
        "validate-only"
        if args.validate_only
        else "dry-run"
        if args.dry_run
        else "write-db"
    )

    now_utc = datetime.now(UTC).isoformat()
    print(f"STARTED ffg_research_universe_import_v1 at {now_utc}")
    print(f"  seed_file: {args.seed_file}")
    print(f"  mode:      {mode_label}")
    print("  broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print(f"  universe_key: {UNIVERSE_KEY}")

    # --- Load and validate seed ---
    conn = None
    try:
        seed = load_seed(args.seed_file)
        seed_schema_version = seed.get("schema_version", "")
        assets: list[dict[str, Any]] = seed["assets"]
        beta_flow: dict[str, Any] = seed.get("beta_flow_snapshot", {})

        validate_seed(assets)
        print(f"  Seed validation passed: {len(assets)} canonical, {EXPECTED_SOURCE_ROWS} source rows")

        if args.validate_only:
            print("  Validation-only mode: no DB connection opened")
            print("FINISHED ffg_research_universe_import_v1")
            return 0

        conn = get_connection()
        assert_required_research_tables(conn)

        # --- Resolve Bitvavo availability ---
        print("  Resolving Bitvavo EUR market availability from local DB...")
        symbol_to_asset_id = fetch_symbol_to_asset_id(conn)
        bitvavo_asset_ids = fetch_bitvavo_asset_ids(conn)
        print(f"  Known assets in DB: {len(symbol_to_asset_id)}")
        print(f"  Assets with Bitvavo market data: {len(bitvavo_asset_ids)}")

        member_rows: list[dict[str, Any]] = []
        resolution_counts: dict[str, int] = {}

        for asset in assets:
            sym = asset["source_symbol"]
            identity_status = asset["identity_status"]
            bitvavo_resolution = derive_bitvavo_resolution(
                sym, identity_status, bitvavo_asset_ids, symbol_to_asset_id
            )
            resolution_counts[bitvavo_resolution] = resolution_counts.get(bitvavo_resolution, 0) + 1

            member_rows.append({
                "universe_key": UNIVERSE_KEY,
                "source_symbol": sym,
                "asset_id": symbol_to_asset_id.get(sym.upper()),
                "source_name": (asset.get("source_names") or [""])[0],
                "ffg_virtual_portfolio_return_pct": asset.get("ffg_virtual_portfolio_return_pct"),
                "research_status": asset["research_status"],
                "identity_status": identity_status,
                "priority_tier": asset.get("priority_tier", ""),
                "bitvavo_eur_resolution": bitvavo_resolution,
                "account_plan_default": "NOT_ENABLED",
                "theme_tags": json.dumps(asset.get("theme_tags") or []),
                "exclusion_reason": asset.get("exclusion_reason"),
                "seed_schema_version": seed_schema_version,
            })

        print(f"  Synchronizing {len(member_rows)} canonical symbols...")
        stale_members, stale_pairs, total_pairs = synchronize_universe(
            conn=conn,
            universe_key=UNIVERSE_KEY,
            member_rows=member_rows,
            assets=assets,
            beta_flow=beta_flow,
            dry_run=not args.write_db,
        )
        print(f"  Imported {total_pairs} normalized source pair rows")
        print(f"  Removed stale member rows: {len(stale_members)}")
        print(f"  Removed stale source pairs: {len(stale_pairs)}")

        if args.write_db:
            conn.commit()
            print("  Committed.")
        else:
            print("  Dry-run only: no DB writes committed")

        print(f"  Bitvavo resolution: {resolution_counts}")

        if args.write_db:
            print_verification(conn, UNIVERSE_KEY)

    except (ResearchUniversePreflightError, ValueError) as exc:
        print(f"FAILED run_ffg_research_universe_import_v1 {exc}")
        return PRECHECK_FAILURE_EXIT_CODE
    finally:
        if conn is not None:
            conn.close()

    print(f"FINISHED ffg_research_universe_import_v1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
