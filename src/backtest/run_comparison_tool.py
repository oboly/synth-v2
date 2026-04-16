#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare exported backtest trades with external analysis predictions."
    )
    parser.add_argument("--trades-csv", required=True)
    parser.add_argument("--analysis-csv", required=True)
    parser.add_argument("--trades-symbol-col", default="symbol")
    parser.add_argument("--trades-ts-col", default="ts_utc")
    parser.add_argument("--trades-return-col", default="trade_return")
    parser.add_argument("--analysis-symbol-col", default="symbol")
    parser.add_argument("--analysis-ts-col", default="ts_utc")
    parser.add_argument("--analysis-direction-col", default="direction")
    parser.add_argument("--analysis-confidence-col", default="confidence")
    parser.add_argument("--timestamp-round", default="1h")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output-dir", default="artifacts/backtest_comparison")
    return parser.parse_args()


def fmt_float(value: float | None, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.{digits}f}"


def safe_mean(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.mean())


def safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    mask = a_num.notna() & b_num.notna()
    if int(mask.sum()) < 2:
        return None
    corr = a_num[mask].corr(b_num[mask])
    if pd.isna(corr):
        return None
    return float(corr)


def normalize_direction(value: object) -> str:
    if value is None:
        return "NEUTRAL"

    text = str(value).strip().upper()
    mapping = {
        "UP": "UP",
        "LONG": "UP",
        "BUY": "UP",
        "BULL": "UP",
        "BULLISH": "UP",
        "POSITIVE": "UP",
        "DOWN": "DOWN",
        "SHORT": "DOWN",
        "SELL": "DOWN",
        "BEAR": "DOWN",
        "BEARISH": "DOWN",
        "NEGATIVE": "DOWN",
        "NEUTRAL": "NEUTRAL",
        "FLAT": "NEUTRAL",
        "WAIT": "NEUTRAL",
        "WATCH": "NEUTRAL",
        "NONE": "NEUTRAL",
    }
    return mapping.get(text, "NEUTRAL")


def return_to_direction(value: float) -> str:
    if pd.isna(value):
        return "NEUTRAL"
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "NEUTRAL"


def prepare_trades(df: pd.DataFrame, symbol_col: str, ts_col: str, return_col: str, round_freq: str) -> pd.DataFrame:
    required = [symbol_col, ts_col, return_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Trades CSV missing required columns: {missing}")

    out = df.rename(
        columns={
            symbol_col: "symbol",
            ts_col: "ts_utc",
            return_col: "trade_return",
        }
    ).copy()

    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], errors="coerce")
    out["trade_return"] = pd.to_numeric(out["trade_return"], errors="coerce")
    out = out[out["symbol"].notna() & out["ts_utc"].notna() & out["trade_return"].notna()].copy()
    out["ts_bucket"] = out["ts_utc"].dt.floor(round_freq)
    out["actual_direction"] = out["trade_return"].apply(return_to_direction)
    return out


def prepare_analysis(
    df: pd.DataFrame,
    symbol_col: str,
    ts_col: str,
    direction_col: str,
    confidence_col: str,
    round_freq: str,
) -> pd.DataFrame:
    required = [symbol_col, ts_col, direction_col, confidence_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Analysis CSV missing required columns: {missing}")

    out = df.rename(
        columns={
            symbol_col: "symbol",
            ts_col: "ts_utc",
            direction_col: "pred_direction",
            confidence_col: "confidence",
        }
    ).copy()

    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], errors="coerce")
    out["pred_direction"] = out["pred_direction"].apply(normalize_direction)
    out["confidence"] = pd.to_numeric(out["confidence"], errors="coerce")
    out = out[out["symbol"].notna() & out["ts_utc"].notna()].copy()
    out["ts_bucket"] = out["ts_utc"].dt.floor(round_freq)
    return out


def compare(trades: pd.DataFrame, analysis: pd.DataFrame, top_k: int) -> tuple[pd.DataFrame, dict[str, object]]:
    merged = trades.merge(
        analysis,
        on=["symbol", "ts_bucket"],
        how="inner",
        suffixes=("_trade", "_analysis"),
    ).copy()

    if merged.empty:
        return merged, {
            "matched_rows": 0,
            "match_rate": None,
            "avg_return_when_match": None,
            "avg_return_when_mismatch": None,
            "confidence_return_corr": None,
            "precision_at_k": None,
        }

    merged["direction_match"] = merged["actual_direction"] == merged["pred_direction"]
    merged["signed_confidence"] = merged["pred_direction"].map({"UP": 1.0, "DOWN": -1.0, "NEUTRAL": 0.0}) * merged["confidence"]

    summary = {
        "matched_rows": int(len(merged)),
        "match_rate": float(merged["direction_match"].mean()),
        "avg_return_when_match": safe_mean(merged.loc[merged["direction_match"], "trade_return"]),
        "avg_return_when_mismatch": safe_mean(merged.loc[~merged["direction_match"], "trade_return"]),
        "confidence_return_corr": safe_corr(merged["signed_confidence"], merged["trade_return"]),
        "precision_at_k": None,
    }

    if top_k > 0:
        top = merged.sort_values("confidence", ascending=False).head(top_k).copy()
        if not top.empty:
            summary["precision_at_k"] = float(top["direction_match"].mean())

    return merged, summary


def main() -> int:
    args = parse_args()

    trades = prepare_trades(
        pd.read_csv(args.trades_csv),
        args.trades_symbol_col,
        args.trades_ts_col,
        args.trades_return_col,
        args.timestamp_round,
    )

    analysis = prepare_analysis(
        pd.read_csv(args.analysis_csv),
        args.analysis_symbol_col,
        args.analysis_ts_col,
        args.analysis_direction_col,
        args.analysis_confidence_col,
        args.timestamp_round,
    )

    merged, summary = compare(trades, analysis, args.top_k)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    merged_path = output_dir / "comparison_merged.csv"
    summary_path = output_dir / "comparison_summary.csv"

    merged.to_csv(merged_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    print()
    print("COMPARISON TOOL — SUMMARY")
    print("=========================")
    print(f"matched_rows: {summary['matched_rows']}")
    print(f"match_rate: {fmt_float(summary['match_rate'])}")
    print(f"avg_return_when_match: {fmt_float(summary['avg_return_when_match'])}")
    print(f"avg_return_when_mismatch: {fmt_float(summary['avg_return_when_mismatch'])}")
    print(f"confidence_return_corr: {fmt_float(summary['confidence_return_corr'])}")
    print(f"precision_at_{args.top_k}: {fmt_float(summary['precision_at_k'])}")
    print(f"merged_csv: {merged_path}")
    print(f"summary_csv: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
