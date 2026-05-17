from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT = "kite_watchlist_candidate_check"
VERSION = "1.0"
DEFAULT_OUTPUT_DIR = Path("data/research/kite_watchlist_candidate_check_v1")
INTERVALS = ["1h", "4h", "1d"]
LOW_LIQUIDITY_MEDIAN_QUOTE_EUR = 25_000.0


@dataclass(frozen=True)
class RepoReference:
    path: str
    line: int
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check KITE local watchlist candidate readiness.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--symbol", default="KITE")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def fetch_all(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_one(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def table_columns(conn: Any, table_name: str) -> set[str]:
    rows = fetch_all(
        conn,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
        """,
        (table_name,),
    )
    return {str(row["column_name"]) for row in rows}


def qident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            numeric = to_float(value)
            out[key] = numeric if numeric is not None and not isinstance(value, str) else value
    return out


def fetch_asset_metadata(conn: Any, symbol: str, quote: str) -> dict[str, Any] | None:
    columns = table_columns(conn, "asset")
    wanted = [
        "asset_id",
        "symbol",
        "name",
        "is_enabled",
        "is_tradeable",
        "is_portfolio",
        "quote_asset",
        "asset_class",
        "sector",
        "base_asset",
        "venue",
    ]
    selected = [column for column in wanted if column in columns]
    if not selected:
        return None

    where = ["UPPER(symbol) = UPPER(%s)"]
    params: list[Any] = [symbol]
    if "quote_asset" in columns:
        where.append("(quote_asset IS NULL OR UPPER(quote_asset) = UPPER(%s))")
        params.append(quote)

    row = fetch_one(
        conn,
        "SELECT "
        + ", ".join(qident(column) for column in selected)
        + " FROM asset WHERE "
        + " AND ".join(where)
        + " ORDER BY asset_id LIMIT 1",
        tuple(params),
    )
    return normalize_row(row)


def fetch_candle_coverage(
    conn: Any,
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
) -> dict[str, Any]:
    row = fetch_one(
        conn,
        """
        SELECT
            COUNT(*) AS row_count,
            MIN(open_ts_utc) AS min_open_ts_utc,
            MAX(close_ts_utc) AS max_close_ts_utc,
            MAX(open_ts_utc) AS max_open_ts_utc
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
        """,
        (asset_id, venue, interval_code),
    )
    coverage = normalize_row(row) or {}
    row_count = int(coverage.get("row_count") or 0)

    latest = fetch_one(
        conn,
        """
        SELECT open_ts_utc, close_ts_utc, close_price, volume_quote_eur, volume_base
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
        ORDER BY close_ts_utc DESC
        LIMIT 1
        """,
        (asset_id, venue, interval_code),
    )
    latest_normalized = normalize_row(latest)
    if latest_normalized:
        coverage["latest_close_price"] = latest_normalized.get("close_price")
        coverage["latest_volume_quote_eur"] = latest_normalized.get("volume_quote_eur")
        coverage["latest_volume_base"] = latest_normalized.get("volume_base")
        coverage["latest_open_ts_utc"] = latest_normalized.get("open_ts_utc")
        coverage["latest_close_ts_utc"] = latest_normalized.get("close_ts_utc")
    else:
        coverage["latest_close_price"] = None
        coverage["latest_volume_quote_eur"] = None
        coverage["latest_volume_base"] = None
        coverage["latest_open_ts_utc"] = None
        coverage["latest_close_ts_utc"] = None

    recent_rows = fetch_all(
        conn,
        """
        SELECT close_ts_utc, volume_quote_eur
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
        ORDER BY close_ts_utc DESC
        LIMIT 30
        """,
        (asset_id, venue, interval_code),
    )
    volumes = [
        volume
        for volume in (to_float(row.get("volume_quote_eur")) for row in recent_rows)
        if volume is not None
    ]
    coverage["recent_30_median_volume_quote_eur"] = statistics.median(volumes) if volumes else None
    coverage["has_rows"] = row_count > 0
    coverage["recent_gap_hint"] = "NO_ROWS" if row_count == 0 else "LATEST_CLOSE_RECORDED"
    return coverage


def scan_repo_references(symbol: str) -> list[dict[str, Any]]:
    root = Path(".")
    skip_dirs = {
        ".git",
        "venv",
        ".venv",
        "__pycache__",
        "data",
        "artifacts",
        ".pytest_cache",
    }
    references: list[RepoReference] = []
    needle = symbol.upper()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if needle in line.upper():
                references.append(
                    RepoReference(
                        path=str(path),
                        line=line_no,
                        text=line.strip()[:220],
                    )
                )

    return [reference.__dict__ for reference in references]


def liquidity_summary(candle_coverage: dict[str, dict[str, Any]]) -> dict[str, Any]:
    interval = "1h" if "1h" in candle_coverage else next(iter(candle_coverage), None)
    if interval is None:
        return {
            "source_interval": None,
            "latest_volume_quote_eur": None,
            "median_volume_quote_eur_recent_window": None,
            "low_liquidity_warning": True,
        }
    coverage = candle_coverage[interval]
    median_volume = to_float(coverage.get("recent_30_median_volume_quote_eur"))
    latest_volume = to_float(coverage.get("latest_volume_quote_eur"))
    return {
        "source_interval": interval,
        "latest_volume_quote_eur": latest_volume,
        "median_volume_quote_eur_recent_window": median_volume,
        "low_liquidity_warning": median_volume is None or median_volume < LOW_LIQUIDITY_MEDIAN_QUOTE_EUR,
    }


def choose_recommendation(local_asset_found: bool, coverage: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if not local_asset_found:
        return (
            "MISSING_LOCAL_ASSET",
            "Open a separate reviewed metadata/ingestion-universe task before local Synth analysis.",
        )

    has_any_candles = any(bool(item.get("has_rows")) for item in coverage.values())
    if not has_any_candles:
        return (
            "MISSING_CANDLES",
            "Open a separate reviewed candle-ingestion universe task before watchlist monitoring.",
        )

    has_research_intervals = bool(coverage.get("1h", {}).get("has_rows")) and bool(
        coverage.get("4h", {}).get("has_rows")
    )
    if has_research_intervals:
        return (
            "RESEARCH_WATCHLIST_READY",
            "Review this report manually, then monitor as research-only watchlist context without runtime promotion.",
        )

    return (
        "NEEDS_MANUAL_REVIEW",
        "Review partial candle coverage before deciding whether to add more ingestion coverage.",
    )


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    conn = get_connection()
    try:
        asset = fetch_asset_metadata(conn, args.symbol, args.quote)
        local_asset_found = asset is not None
        candle_coverage: dict[str, dict[str, Any]] = {}

        if asset and asset.get("asset_id") is not None:
            asset_id = int(asset["asset_id"])
            for interval_code in INTERVALS:
                candle_coverage[interval_code] = fetch_candle_coverage(
                    conn,
                    asset_id=asset_id,
                    venue=args.venue,
                    interval_code=interval_code,
                )
        else:
            for interval_code in INTERVALS:
                candle_coverage[interval_code] = {
                    "row_count": 0,
                    "min_open_ts_utc": None,
                    "max_close_ts_utc": None,
                    "latest_close_price": None,
                    "has_rows": False,
                    "recent_gap_hint": "NO_LOCAL_ASSET",
                }
    finally:
        conn.close()

    repo_references = scan_repo_references(args.symbol)
    recommendation, next_step = choose_recommendation(local_asset_found, candle_coverage)

    availability_parts = []
    if not local_asset_found:
        availability_parts.append("KITE is not present in local asset metadata.")
    else:
        availability_parts.append("KITE is present in local asset metadata.")
    intervals_with_rows = [
        interval for interval, coverage in candle_coverage.items() if coverage.get("has_rows")
    ]
    if intervals_with_rows:
        availability_parts.append("Local candles exist for: " + ", ".join(intervals_with_rows) + ".")
    else:
        availability_parts.append("No local candle rows were found for the checked intervals.")

    return {
        "report": REPORT,
        "version": VERSION,
        "generated_ts_utc": utc_now_iso(),
        "scope": "research_only_market_only_account_agnostic_watchlist_intake",
        "venue": args.venue,
        "symbol": args.symbol.upper(),
        "market": args.symbol.upper() + "-" + args.quote.upper(),
        "local_asset_found": local_asset_found,
        "asset_metadata": asset,
        "candle_coverage_by_interval": candle_coverage,
        "repo_references": repo_references,
        "availability_summary": " ".join(availability_parts),
        "liquidity_proxy_summary": liquidity_summary(candle_coverage),
        "recommendation": recommendation,
        "next_step": next_step,
        "no_runtime_promotion": True,
        "no_selection_changes": True,
        "no_advice_changes": True,
        "no_decision_changes": True,
        "no_execution_changes": True,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "db_writes": 0,
        "selection_engine_changes": 0,
        "advice_engine_changes": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor_changes": 0,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "kite_watchlist_candidate_check_v1.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=json_default) + "\n")
    return path


def print_table(report: dict[str, Any]) -> None:
    print(f"report={report['report']} version={report['version']}")
    print(f"venue={report['venue']} market={report['market']}")
    print(f"local_asset_found={report['local_asset_found']}")
    asset = report.get("asset_metadata") or {}
    if asset:
        print(
            "asset="
            + f"id={asset.get('asset_id')} "
            + f"enabled={asset.get('is_enabled')} "
            + f"tradeable={asset.get('is_tradeable')} "
            + f"portfolio={asset.get('is_portfolio')} "
            + f"name={asset.get('name')}"
        )
    print("candle_coverage:")
    for interval, coverage in report["candle_coverage_by_interval"].items():
        print(
            f"- {interval}: rows={coverage.get('row_count')} "
            f"min_open={coverage.get('min_open_ts_utc')} "
            f"max_close={coverage.get('max_close_ts_utc')} "
            f"latest_close={coverage.get('latest_close_price')} "
            f"median_vol_quote_30={coverage.get('recent_30_median_volume_quote_eur')}"
        )
    liquidity = report["liquidity_proxy_summary"]
    print(
        "liquidity_proxy="
        + f"interval={liquidity.get('source_interval')} "
        + f"latest_quote={liquidity.get('latest_volume_quote_eur')} "
        + f"median_quote={liquidity.get('median_volume_quote_eur_recent_window')} "
        + f"low_warning={liquidity.get('low_liquidity_warning')}"
    )
    print(f"repo_references={len(report['repo_references'])}")
    print(f"recommendation={report['recommendation']}")
    print(f"next_step={report['next_step']}")
    print("safety=db_writes=0 broker_private_calls=0 broker_writes=0 order_submission=0")


def main() -> None:
    args = parse_args()
    report = build_report(args)

    if args.write_files:
        path = write_report(report, Path(args.output_dir))
        if args.output == "table":
            print(f"wrote={path}")

    if args.output == "json":
        print(json.dumps(report, indent=2, sort_keys=True, default=json_default))
    else:
        print_table(report)


if __name__ == "__main__":
    main()
