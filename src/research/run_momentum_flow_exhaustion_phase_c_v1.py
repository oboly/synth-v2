"""Historical PIT replay and outcome evaluation for Issue #306 Phase C.

Research-only. Feature rows are computed strictly at each historical as-of using
only finalized candles available at that as-of. Forward candles are joined only
after feature construction to measure outcomes. No thresholds are promoted to
selection or execution authority here.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Final, Iterable

import pandas as pd

from src.common.db import get_connection
from src.research.momentum_flow_exhaustion_candidate_v1 import (
    MIN_WARMUP_BARS,
    STATE_INSUFFICIENT,
    build_exhaustion_candidate,
)

MODEL_VERSION: Final[str] = "momentum_flow_exhaustion_phase_c_v1"
DEFAULT_OUTPUT_DIR: Final[Path] = Path("data/research/momentum_flow_exhaustion_phase_c_v1")
INTERVAL_DELTAS: Final[dict[str, timedelta]] = {
    "15m": timedelta(minutes=15), "1h": timedelta(hours=1),
    "4h": timedelta(hours=4), "1d": timedelta(days=1), "1w": timedelta(days=7),
}
DEFAULT_HORIZON_BARS: Final[tuple[int, ...]] = (1, 3, 6)
SCORE_BUCKETS: Final[tuple[tuple[str, float, float], ...]] = (
    ("0_25", 0.0, 25.0), ("25_45", 25.0, 45.0),
    ("45_70", 45.0, 70.0), ("70_100", 70.0, 100.000001),
)

@dataclass(frozen=True)
class ReplayConfig:
    interval: str = "4h"
    horizon_bars: tuple[int, ...] = DEFAULT_HORIZON_BARS
    sample_every_n: int = 1
    max_samples_per_market: int = 0


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _mean(values: Iterable[float | None]) -> float | None:
    xs = [float(v) for v in values if v is not None]
    return None if not xs else round(mean(xs), 6)


def _median(values: Iterable[float | None]) -> float | None:
    xs = [float(v) for v in values if v is not None]
    return None if not xs else round(median(xs), 6)


def _bucket(score: float) -> str:
    for label, lo, hi in SCORE_BUCKETS:
        if lo <= score < hi:
            return label
    raise ValueError(f"score outside expected range: {score}")


def _validate_candles(frame: pd.DataFrame, config: ReplayConfig) -> pd.DataFrame:
    required = {"market", "interval", "start_ts", "end_ts", "open", "high", "low", "close", "volume", "is_final"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing candle columns: {sorted(missing)}")
    if config.interval not in INTERVAL_DELTAS:
        raise ValueError(f"unsupported interval: {config.interval}")
    if config.sample_every_n <= 0:
        raise ValueError("sample_every_n must be positive")
    if not config.horizon_bars or any(h <= 0 for h in config.horizon_bars):
        raise ValueError("horizon_bars must be positive")
    out = frame.copy()
    out["start_ts"] = pd.to_datetime(out["start_ts"], utc=True, errors="raise")
    out["end_ts"] = pd.to_datetime(out["end_ts"], utc=True, errors="raise")
    out = out.loc[out["is_final"].astype(bool) & (out["interval"].astype(str) == config.interval)].copy()
    return out.sort_values(["market", "end_ts"], kind="mergesort").reset_index(drop=True)


def _outcome(reference: float, future: pd.DataFrame, side: str, horizon: int) -> dict[str, Any]:
    if len(future) < horizon or reference <= 0:
        return {f"complete_{horizon}b": False, f"return_{horizon}b_pct": None,
                f"side_return_{horizon}b_pct": None, f"mfe_{horizon}b_pct": None,
                f"mae_{horizon}b_pct": None,
                f"buyer_reversal_return_{horizon}b_pct": None,
                f"seller_reversal_return_{horizon}b_pct": None,
                f"buyer_mfe_{horizon}b_pct": None, f"buyer_mae_{horizon}b_pct": None,
                f"seller_mfe_{horizon}b_pct": None, f"seller_mae_{horizon}b_pct": None}
    window = future.iloc[:horizon]
    terminal = float(window.iloc[-1]["close"])
    raw_return = (terminal / reference - 1.0) * 100.0
    max_up = (float(window["high"].max()) / reference - 1.0) * 100.0
    max_down = (float(window["low"].min()) / reference - 1.0) * 100.0
    if side == "BUYER":
        side_return = -raw_return
        mfe, mae = -max_down, -max_up
    elif side == "SELLER":
        side_return = raw_return
        mfe, mae = max_up, max_down
    else:
        side_return = None
        mfe, mae = None, None
    buyer_reversal_return = -raw_return
    seller_reversal_return = raw_return
    buyer_mfe, buyer_mae = -max_down, -max_up
    seller_mfe, seller_mae = max_up, max_down
    return {f"complete_{horizon}b": True,
            f"return_{horizon}b_pct": round(raw_return, 6),
            f"side_return_{horizon}b_pct": None if side_return is None else round(side_return, 6),
            f"mfe_{horizon}b_pct": None if mfe is None else round(mfe, 6),
            f"mae_{horizon}b_pct": None if mae is None else round(mae, 6),
            f"buyer_reversal_return_{horizon}b_pct": round(buyer_reversal_return, 6),
            f"seller_reversal_return_{horizon}b_pct": round(seller_reversal_return, 6),
            f"buyer_mfe_{horizon}b_pct": round(buyer_mfe, 6),
            f"buyer_mae_{horizon}b_pct": round(buyer_mae, 6),
            f"seller_mfe_{horizon}b_pct": round(seller_mfe, 6),
            f"seller_mae_{horizon}b_pct": round(seller_mae, 6)}


def build_replay_rows(candles: pd.DataFrame, config: ReplayConfig = ReplayConfig()) -> list[dict[str, Any]]:
    source = _validate_candles(candles, config)
    rows: list[dict[str, Any]] = []
    max_h = max(config.horizon_bars)
    for market, group in source.groupby("market", sort=True):
        group = group.reset_index(drop=True)
        eligible_indices = list(range(MIN_WARMUP_BARS - 1, max(0, len(group) - max_h), config.sample_every_n))
        if config.max_samples_per_market > 0:
            eligible_indices = eligible_indices[:config.max_samples_per_market]
        for index in eligible_indices:
            history = group.iloc[: index + 1].copy()
            asof = history.iloc[-1]["end_ts"].to_pydatetime()
            # Phase B uses bounded 20-bar volume warmup; regression tests prove
            # prepended history beyond this floor cannot change the candidate.
            candidate_input = history.tail(MIN_WARMUP_BARS).reset_index(drop=True)
            candidate = build_exhaustion_candidate(candidate_input, asof_ts_utc=asof)
            if candidate.empty:
                continue
            c = candidate.iloc[0].to_dict()
            if c.get("exhaustion_state") == STATE_INSUFFICIENT:
                continue
            side = str(c.get("exhaustion_side") or "NONE")
            reference = float(history.iloc[-1]["close"])
            future = group.iloc[index + 1 : index + 1 + max_h]
            row: dict[str, Any] = {
                "market": str(market), "interval": config.interval,
                "asof_ts_utc": pd.Timestamp(asof).isoformat(), "reference_close": reference,
                "exhaustion_side": side, "exhaustion_state": str(c["exhaustion_state"]),
                "buyer_exhaustion_score": round(float(c["buyer_exhaustion_score"]), 6),
                "seller_exhaustion_score": round(float(c["seller_exhaustion_score"]), 6),
                "absorption_score_proxy": round(float(c["absorption_score_proxy"]), 6),
                "volume_ratio_20": round(float(c["volume_ratio_20"]), 6),
                "directional_price_progress_atr": round(float(c["directional_price_progress_atr"]), 6),
                "model_id": str(c["model_id"]), "model_version": str(c["model_version"]),
                "candidate_thresholds_version": str(c["candidate_thresholds_version"]),
            }
            active_score = max(row["buyer_exhaustion_score"], row["seller_exhaustion_score"])
            row["active_exhaustion_score"] = active_score
            row["score_bucket"] = _bucket(active_score)
            row["buyer_score_bucket"] = _bucket(row["buyer_exhaustion_score"])
            row["seller_score_bucket"] = _bucket(row["seller_exhaustion_score"])
            for horizon in config.horizon_bars:
                row.update(_outcome(reference, future, side, horizon))
            rows.append(row)
    return rows


def build_summary(rows: list[dict[str, Any]], config: ReplayConfig) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": MODEL_VERSION, "row_count": len(rows),
        "interval": config.interval, "horizon_bars": list(config.horizon_bars),
        "sample_every_n": config.sample_every_n, "max_samples_per_market": config.max_samples_per_market,
        "cohorts": {},
        "interpretation": "Research calibration only. Positive side_return means reversal in the direction implied by the exhaustion side.",
    }
    for dimension in ("score_bucket", "exhaustion_state", "exhaustion_side"):
        values = sorted({str(row[dimension]) for row in rows})
        dim: dict[str, Any] = {}
        for value in values:
            cohort = [r for r in rows if str(r[dimension]) == value]
            item: dict[str, Any] = {"count": len(cohort)}
            for h in config.horizon_bars:
                item[f"complete_{h}b"] = sum(1 for r in cohort if r.get(f"complete_{h}b"))
                item[f"avg_return_{h}b_pct"] = _mean(r.get(f"return_{h}b_pct") for r in cohort)
                item[f"avg_side_return_{h}b_pct"] = _mean(r.get(f"side_return_{h}b_pct") for r in cohort)
                item[f"median_side_return_{h}b_pct"] = _median(r.get(f"side_return_{h}b_pct") for r in cohort)
                item[f"avg_mfe_{h}b_pct"] = _mean(r.get(f"mfe_{h}b_pct") for r in cohort)
                item[f"avg_mae_{h}b_pct"] = _mean(r.get(f"mae_{h}b_pct") for r in cohort)
            dim[value] = item
        summary["cohorts"][dimension] = dim

    for side in ("buyer", "seller"):
        dimension = f"{side}_score_bucket"
        values = sorted({str(row[dimension]) for row in rows})
        dim: dict[str, Any] = {}
        for value in values:
            cohort = [r for r in rows if str(r[dimension]) == value]
            item: dict[str, Any] = {"count": len(cohort)}
            for h in config.horizon_bars:
                item[f"complete_{h}b"] = sum(1 for r in cohort if r.get(f"complete_{h}b"))
                item[f"avg_reversal_return_{h}b_pct"] = _mean(r.get(f"{side}_reversal_return_{h}b_pct") for r in cohort)
                item[f"median_reversal_return_{h}b_pct"] = _median(r.get(f"{side}_reversal_return_{h}b_pct") for r in cohort)
                item[f"avg_mfe_{h}b_pct"] = _mean(r.get(f"{side}_mfe_{h}b_pct") for r in cohort)
                item[f"avg_mae_{h}b_pct"] = _mean(r.get(f"{side}_mae_{h}b_pct") for r in cohort)
            dim[value] = item
        summary["cohorts"][dimension] = dim
    return summary


def fetch_candles(conn: Any, *, venue: str, interval: str, from_ts: datetime, to_ts: datetime, symbols: list[str]) -> pd.DataFrame:
    symbol_filter = ""
    params: list[Any] = [venue, interval, from_ts, to_ts]
    if symbols:
        symbol_filter = " AND a.symbol IN (" + ",".join(["%s"] * len(symbols)) + ")"
        params.extend(symbols)
    sql = f"""
    SELECT a.symbol AS market, c.interval_code AS `interval`, c.open_ts_utc AS start_ts,
           c.close_ts_utc AS end_ts, c.open_price AS `open`, c.high_price AS high,
           c.low_price AS low, c.close_price AS `close`, c.volume_base AS volume
    FROM obs_market_candle c JOIN asset a ON a.asset_id=c.asset_id
    WHERE c.venue=%s AND c.interval_code=%s AND c.close_ts_utc >= %s AND c.close_ts_utc <= %s
    {symbol_filter}
    ORDER BY a.symbol, c.close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        data = list(cur.fetchall())
    frame = pd.DataFrame(data)
    if not frame.empty:
        frame["is_final"] = True
    return frame


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary_v1.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if rows:
        with (output_dir / "replay_rows_v1.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run #306 Phase C historical exhaustion replay")
    p.add_argument("--database", default="synth"); p.add_argument("--venue", default="bitvavo")
    p.add_argument("--interval", default="4h", choices=sorted(INTERVAL_DELTAS))
    p.add_argument("--from-ts", required=True); p.add_argument("--to-ts", required=True)
    p.add_argument("--symbols", default=""); p.add_argument("--sample-every-n", type=int, default=6)
    p.add_argument("--max-samples-per-market", type=int, default=0)
    p.add_argument("--horizon-bars", default="1,3,6"); p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    horizons = tuple(int(x) for x in args.horizon_bars.split(",") if x.strip())
    cfg = ReplayConfig(interval=args.interval, horizon_bars=horizons, sample_every_n=args.sample_every_n,
                       max_samples_per_market=args.max_samples_per_market)
    from_ts = _utc(datetime.fromisoformat(args.from_ts.replace("Z", "+00:00")))
    to_ts = _utc(datetime.fromisoformat(args.to_ts.replace("Z", "+00:00")))
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    conn = get_connection(database=args.database)
    try:
        candles = fetch_candles(conn, venue=args.venue, interval=args.interval, from_ts=from_ts, to_ts=to_ts, symbols=symbols)
    finally:
        conn.close()
    rows = build_replay_rows(candles, cfg)
    summary = build_summary(rows, cfg)
    write_outputs(rows, summary, Path(args.output_dir))
    print(f"rows={len(rows)} markets={candles['market'].nunique() if not candles.empty else 0} output={args.output_dir}")

if __name__ == "__main__":
    main()
