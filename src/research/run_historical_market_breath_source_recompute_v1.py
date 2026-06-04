from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.run_historical_breath_regime_context_builder_v1 import (
    DEFAULT_INTERVAL,
    DEFAULT_VENUE,
    SAFETY_MARKERS,
    as_float,
    btc_context_from_scores,
    canonical_breath_alignment,
    canonical_breath_phase,
    confidence_bucket,
    fmt_ts,
    market_regime_from_scores,
    momentum_bucket,
    parse_symbols_arg,
    parse_ts,
    relative_strength_bucket,
    symbol_regime_from_scores,
    write_csv,
    write_json,
    write_jsonl,
)
from src.research.run_historical_market_breath_source_enrichment_v1 import quality_state_for_row
from src.research.run_market_breath_analysis_v1 import (
    Asset,
    add_breadth_and_scores,
    build_base_observation,
    fetch_assets,
    fetch_candles,
    latest_asof_ts,
    safe_return,
)


REPORT_NAME = "historical_market_breath_source_recompute_v1"
REPORT_VERSION = "1.0"

DEFAULT_OUTPUT_DIR = Path("data/research/historical_market_breath_source_recompute_v1")
ROWS_CSV = "historical_market_breath_source_recomputed_rows_v1.csv"
ROWS_JSONL = "historical_market_breath_source_recomputed_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"
DEFAULT_LOOKBACK_CANDLES = 120


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute historical market-breath source rows from candle replay "
            "(research-only, DB-read-only, file-output only)."
        )
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--start-ts", default=None)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def resolve_assets(
    conn: Any,
    *,
    requested_symbols: list[str] | None,
) -> tuple[list[Asset], Asset]:
    assets = fetch_assets(conn)
    asset_by_symbol = {asset.symbol.upper(): asset for asset in assets}
    btc_asset = asset_by_symbol.get("BTC")
    if btc_asset is None:
        raise RuntimeError("BTC asset not available; cannot compute historical market-breath replay")

    if not requested_symbols:
        selected = [asset for asset in assets if asset.symbol != "BTC"]
    else:
        missing = [symbol for symbol in requested_symbols if symbol.upper() not in asset_by_symbol]
        if missing:
            raise RuntimeError(f"Requested symbols not available in asset universe: {','.join(sorted(missing))}")
        selected = [asset_by_symbol[symbol.upper()] for symbol in requested_symbols if symbol.upper() != "BTC"]

    if not selected:
        raise RuntimeError("No replay assets selected")
    return selected, btc_asset


def fetch_timestamp_spine(
    conn: Any,
    *,
    asset_ids: list[int],
    venue: str,
    interval_code: str,
    start_ts: datetime | None,
    end_ts: datetime | None,
) -> list[datetime]:
    if not asset_ids:
        return []
    effective_end = end_ts or latest_asof_ts(conn, venue, interval_code)
    clauses = [
        "venue = %s",
        "interval_code = %s",
    ]
    params: list[Any] = [venue, interval_code]
    if start_ts is not None:
        clauses.append("close_ts_utc >= %s")
        params.append(start_ts)
    clauses.append("close_ts_utc <= %s")
    params.append(effective_end)
    placeholders = ",".join(["%s"] * len(asset_ids))
    clauses.append(f"asset_id IN ({placeholders})")
    params.extend(asset_ids)
    sql = f"""
        SELECT DISTINCT close_ts_utc
        FROM obs_market_candle
        WHERE {' AND '.join(clauses)}
        ORDER BY close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [row["close_ts_utc"].replace(tzinfo=None) for row in rows if row.get("close_ts_utc") is not None]


def build_recomputed_row(
    observation: dict[str, Any],
    *,
    source_tag: str = REPORT_NAME,
) -> dict[str, Any]:
    asof_ts = parse_ts(observation.get("asof_ts_utc"))
    if asof_ts is None:
        raise ValueError("Observation missing asof_ts_utc")

    market_breath_phase_raw = str(observation.get("market_breath_phase") or "UNKNOWN").strip().upper()
    market_breath_state_raw = str(observation.get("market_breath_state") or "UNKNOWN").strip().upper()

    row = {
        "symbol": str(observation.get("symbol") or "").strip().upper(),
        "venue": str(observation.get("venue") or DEFAULT_VENUE).strip().lower(),
        "interval": str(observation.get("interval_code") or observation.get("interval") or DEFAULT_INTERVAL).strip(),
        "asof_ts_utc": fmt_ts(asof_ts),
        "source_event_ts_utc": fmt_ts(asof_ts),
        "compression_score": as_float(observation.get("compression_score")),
        "expansion_score": as_float(observation.get("expansion_score")),
        "momentum_score": as_float(observation.get("momentum_score")),
        "reversal_pressure_score": as_float(observation.get("reversal_pressure_score")),
        "relative_strength_score": as_float(observation.get("relative_strength_score")),
        "btc_alignment_score": as_float(observation.get("btc_alignment_score")),
        "breadth_alignment_score": as_float(observation.get("breadth_alignment_score")),
        "market_breath_phase_raw": market_breath_phase_raw,
        "market_breath_state_raw": market_breath_state_raw,
        "market_breath_confidence": as_float(observation.get("market_breath_confidence")),
        "breath_phase": canonical_breath_phase(market_breath_phase_raw),
        "breath_alignment": canonical_breath_alignment(market_breath_state_raw),
        "market_regime": market_regime_from_scores(observation),
        "btc_context": btc_context_from_scores(observation),
        "symbol_regime": symbol_regime_from_scores(observation),
        "relative_strength_bucket": relative_strength_bucket(as_float(observation.get("relative_strength_score"))),
        "momentum_bucket": momentum_bucket(as_float(observation.get("momentum_score"))),
        "confidence_bucket": confidence_bucket(as_float(observation.get("market_breath_confidence"))),
        "source_refs": [
            {
                "source": source_tag,
                "source_input": "obs_market_candle",
                "asof_ts_utc": fmt_ts(asof_ts),
                "interval": str(observation.get("interval_code") or observation.get("interval") or DEFAULT_INTERVAL).strip(),
            }
        ],
        "research_only": True,
    }
    row["quality_state"] = quality_state_for_row(row)
    return row


def replay_rows_for_timestamp(
    conn: Any,
    *,
    selected_assets: list[Asset],
    btc_asset: Asset,
    venue: str,
    interval_code: str,
    lookback_candles: int,
    asof_ts: datetime,
) -> list[dict[str, Any]]:
    candle_assets = list(selected_assets)
    if all(asset.asset_id != btc_asset.asset_id for asset in candle_assets):
        candle_assets.append(btc_asset)

    candles_by_asset = fetch_candles(
        conn,
        assets=candle_assets,
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
        lookback_candles=lookback_candles,
    )
    btc_candles = candles_by_asset.get(btc_asset.asset_id, [])
    btc_r6 = safe_return(btc_candles, 6) if btc_candles else None
    btc_r12 = safe_return(btc_candles, 12) if btc_candles else None

    base_rows = [
        build_base_observation(
            asset=asset,
            candles=candles_by_asset.get(asset.asset_id, []),
            venue=venue,
            interval_code=interval_code,
            lookback_candles=lookback_candles,
            asof_ts=asof_ts,
            btc_r6=btc_r6,
            btc_r12=btc_r12,
        )
        for asset in selected_assets
    ]
    observations = add_breadth_and_scores(base_rows, lookback_candles)
    return [build_recomputed_row(observation) for observation in observations]


def recompute_rows(
    *,
    conn: Any,
    symbols: list[str] | None,
    venue: str,
    interval: str,
    start_ts: datetime | None,
    end_ts: datetime | None,
    max_rows: int = 0,
    lookback_candles: int = DEFAULT_LOOKBACK_CANDLES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_assets, btc_asset = resolve_assets(conn, requested_symbols=symbols)
    timestamps = fetch_timestamp_spine(
        conn,
        asset_ids=[asset.asset_id for asset in selected_assets],
        venue=venue,
        interval_code=interval,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    if not timestamps:
        raise RuntimeError("No candle timestamps available for requested replay scope")

    rows: list[dict[str, Any]] = []
    for asof_ts in timestamps:
        rows.extend(
            replay_rows_for_timestamp(
                conn,
                selected_assets=selected_assets,
                btc_asset=btc_asset,
                venue=venue,
                interval_code=interval,
                lookback_candles=lookback_candles,
                asof_ts=asof_ts,
            )
        )
        if max_rows > 0 and len(rows) >= max_rows:
            rows = rows[:max_rows]
            break

    rows.sort(key=lambda item: (item["symbol"], item["asof_ts_utc"]))
    measures = {
        "row_count": len(rows),
        "breath_phase_distribution": dict(Counter(row["breath_phase"] for row in rows)),
        "breath_alignment_distribution": dict(Counter(row["breath_alignment"] for row in rows)),
        "symbol_regime_distribution": dict(Counter(row["symbol_regime"] for row in rows)),
        "quality_state_distribution": dict(Counter(row["quality_state"] for row in rows)),
    }
    return rows, measures


def build_manifest(
    *,
    args: argparse.Namespace,
    rows: list[dict[str, Any]],
    measures: dict[str, Any],
    output_paths: dict[str, str],
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "scope": "research-only market-only db-read-only file-output",
        "symbols": parse_symbols_arg(args.symbols) or [],
        "venue": args.venue,
        "interval": args.interval,
        "start_ts": args.start_ts,
        "end_ts": args.end_ts,
        "row_count": len(rows),
        "measures": measures,
        "output_paths": output_paths,
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(*, rows: list[dict[str, Any]], measures: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"row_count={len(rows)}")
    print(
        "breath_phase "
        + " ; ".join(f"{key}:{value}" for key, value in sorted(measures["breath_phase_distribution"].items()))
    )
    print(
        "breath_alignment "
        + " ; ".join(
            f"{key}:{value}" for key, value in sorted(measures["breath_alignment_distribution"].items())
        )
    )
    print(
        "symbol_regime "
        + " ; ".join(f"{key}:{value}" for key, value in sorted(measures["symbol_regime_distribution"].items()))
    )
    print(
        "quality_state "
        + " ; ".join(f"{key}:{value}" for key, value in sorted(measures["quality_state_distribution"].items()))
    )
    print(
        "safety "
        + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in SAFETY_MARKERS.items()
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    venue = str(args.venue).lower()
    interval = str(args.interval)
    output_dir = Path(args.output_dir)
    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)

    conn = get_connection()
    try:
        rows, measures = recompute_rows(
            conn=conn,
            symbols=symbols,
            venue=venue,
            interval=interval,
            start_ts=start_ts,
            end_ts=end_ts,
            max_rows=int(args.max_rows or 0),
        )
    finally:
        conn.close()

    output_paths: dict[str, str] = {}
    if args.write_files:
        csv_path = output_dir / ROWS_CSV
        jsonl_path = output_dir / ROWS_JSONL
        manifest_path = output_dir / MANIFEST_JSON
        write_csv(csv_path, rows)
        write_jsonl(jsonl_path, rows)
        output_paths = {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "manifest": str(manifest_path),
        }
        manifest = build_manifest(args=args, rows=rows, measures=measures, output_paths=output_paths)
        write_json(manifest_path, manifest)
    else:
        manifest = build_manifest(args=args, rows=rows, measures=measures, output_paths=output_paths)

    if args.output == "json":
        print(json.dumps({"rows": rows, "manifest": manifest}, indent=2, sort_keys=True))
    else:
        print_summary(rows=rows, measures=measures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
