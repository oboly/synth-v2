from __future__ import annotations

import argparse
import bisect
import json
import signal
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
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


class _RunnerInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _signal_handler(signum: int, _frame: Any) -> None:
    raise _RunnerInterrupted(signum)


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
    parser.add_argument("--breadth-scope", choices=("selected", "all-enabled"), default="selected")
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
        selected = [asset_by_symbol[symbol.upper()] for symbol in requested_symbols]

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


def fetch_breadth_close_history(
    conn: Any,
    *,
    assets: list[Asset],
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
    lookback_candles: int,
) -> dict[int, tuple[list[datetime], list[float]]]:
    """Load close-only history for full-universe breadth using bounded DB fetches."""
    if not assets:
        return {}
    interval_seconds = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(interval_code, 14400)
    history_start = start_ts - timedelta(seconds=interval_seconds * lookback_candles * 4)
    asset_ids = [asset.asset_id for asset in assets]
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT asset_id, close_ts_utc, close_price
        FROM obs_market_candle
        WHERE venue=%s AND interval_code=%s
          AND close_ts_utc > %s AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, history_start, end_ts, *asset_ids]
    grouped: dict[int, tuple[list[datetime], list[float]]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        while True:
            batch = cur.fetchmany(5000)
            if not batch:
                break
            for row in batch:
                asset_id = int(row["asset_id"])
                if asset_id not in grouped:
                    grouped[asset_id] = ([], [])
                grouped[asset_id][0].append(row["close_ts_utc"])
                grouped[asset_id][1].append(float(row["close_price"]))
    return grouped


def breadth_dummy_rows_at_asof(
    history: dict[int, tuple[list[datetime], list[float]]],
    *,
    asof_ts: datetime,
    exclude_asset_ids: set[int],
) -> list[dict[str, Any]]:
    """Return minimal rows whose return_6 participates in canonical breadth logic."""
    rows: list[dict[str, Any]] = []
    for asset_id, (times, closes) in history.items():
        if asset_id in exclude_asset_ids:
            continue
        idx = bisect.bisect_right(times, asof_ts) - 1
        if idx < 6:
            continue
        old = closes[idx - 6]
        new = closes[idx]
        if old <= 0:
            continue
        rows.append({
            "return_6": (new / old - 1.0) * 100.0,
            "market_breath_phase": "INSUFFICIENT_DATA",
        })
    return rows


def replay_rows_for_timestamp(
    conn: Any,
    *,
    selected_assets: list[Asset],
    btc_asset: Asset,
    venue: str,
    interval_code: str,
    lookback_candles: int,
    asof_ts: datetime,
    breadth_history: dict[int, tuple[list[datetime], list[float]]] | None = None,
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
    breadth_rows = []
    if breadth_history is not None:
        breadth_rows = breadth_dummy_rows_at_asof(
            breadth_history,
            asof_ts=asof_ts,
            exclude_asset_ids={asset.asset_id for asset in selected_assets},
        )
    observations = add_breadth_and_scores(base_rows + breadth_rows, lookback_candles)[: len(base_rows)]
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
    breadth_scope: str = "selected",
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

    breadth_history = None
    breadth_asset_count = len(selected_assets)
    if breadth_scope == "all-enabled":
        print("PHASE_STARTED phase=load_breadth_history", flush=True)
        breadth_assets = fetch_assets(conn)
        breadth_asset_count = len(breadth_assets)
        breadth_history = fetch_breadth_close_history(
            conn,
            assets=breadth_assets,
            venue=venue,
            interval_code=interval,
            start_ts=timestamps[0],
            end_ts=timestamps[-1],
            lookback_candles=lookback_candles,
        )
        print(
            f"PHASE_FINISHED phase=load_breadth_history assets={breadth_asset_count} assets_with_history={len(breadth_history)}",
            flush=True,
        )
    elif breadth_scope != "selected":
        raise ValueError(f"unsupported breadth_scope: {breadth_scope}")

    rows: list[dict[str, Any]] = []
    print(
        f"PHASE_STARTED phase=replay timestamps={len(timestamps)} assets={len(selected_assets)} interval={interval}",
        flush=True,
    )
    progress_every = max(1, len(timestamps) // 10)
    for timestamp_index, asof_ts in enumerate(timestamps, start=1):
        rows.extend(
            replay_rows_for_timestamp(
                conn,
                selected_assets=selected_assets,
                btc_asset=btc_asset,
                venue=venue,
                interval_code=interval,
                lookback_candles=lookback_candles,
                asof_ts=asof_ts,
                breadth_history=breadth_history,
            )
        )
        if timestamp_index == 1 or timestamp_index % progress_every == 0 or timestamp_index == len(timestamps):
            print(
                f"PHASE_PROGRESS phase=replay timestamp_index={timestamp_index}/{len(timestamps)} rows={len(rows)} asof_ts_utc={fmt_ts(asof_ts)}",
                flush=True,
            )
        if max_rows > 0 and len(rows) >= max_rows:
            rows = rows[:max_rows]
            break

    print(f"PHASE_FINISHED phase=replay rows={len(rows)}", flush=True)
    rows.sort(key=lambda item: (item["symbol"], item["asof_ts_utc"]))
    measures = {
        "row_count": len(rows),
        "symbol_count": len({row["symbol"] for row in rows}),
        "breadth_scope": breadth_scope,
        "breadth_asset_count": breadth_asset_count,
        "min_asof_ts_utc": min((row["asof_ts_utc"] for row in rows), default=None),
        "max_asof_ts_utc": max((row["asof_ts_utc"] for row in rows), default=None),
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
        "breadth_scope": args.breadth_scope,
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
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    for signum in previous_handlers:
        signal.signal(signum, _signal_handler)

    print(
        f"STARTED runner={REPORT_NAME} version={REPORT_VERSION} venue={args.venue} interval={args.interval} start_ts={args.start_ts} end_ts={args.end_ts}",
        flush=True,
    )
    try:
        symbols = parse_symbols_arg(args.symbols)
        venue = str(args.venue).lower()
        interval = str(args.interval)
        output_dir = Path(args.output_dir)
        start_ts = parse_ts(args.start_ts)
        end_ts = parse_ts(args.end_ts)

        print("PHASE_STARTED phase=db_recompute", flush=True)
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
                breadth_scope=args.breadth_scope,
            )
        finally:
            conn.close()
        print(f"PHASE_FINISHED phase=db_recompute rows={len(rows)}", flush=True)

        output_paths: dict[str, str] = {}
        if args.write_files:
            print("PHASE_STARTED phase=write_outputs", flush=True)
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
            print(f"PHASE_FINISHED phase=write_outputs output_dir={output_dir}", flush=True)
        else:
            manifest = build_manifest(args=args, rows=rows, measures=measures, output_paths=output_paths)

        if args.output == "json":
            print(json.dumps({"rows": rows, "manifest": manifest}, indent=2, sort_keys=True))
        else:
            print_summary(rows=rows, measures=measures)
    except _RunnerInterrupted as exc:
        print(
            f"INTERRUPTED runner={REPORT_NAME} signal={signal.Signals(exc.signum).name} "
            "db_writes=0 broker_calls=0 order_submission=0",
            flush=True,
        )
        return 130
    except Exception as exc:
        print(
            f"FAILED runner={REPORT_NAME} error_type={type(exc).__name__} error={str(exc)!r} "
            "db_writes=0 broker_calls=0 order_submission=0",
            flush=True,
        )
        return 1
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)

    print(f"FINISHED runner={REPORT_NAME} rows={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
