from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from src.research.breath_curve_template_matcher_v1 import (
    Candle,
    MarkerMatch,
    load_db,
    match,
    parse_dt,
    parse_offsets,
)
from src.research.run_breath_curve_template_partial_v1 import (
    partial_match,
)


VERSION = "0.1"


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expected_ts(anchor: datetime, cycle_days: float, ratio: float, offset_days: float) -> datetime:
    return anchor + timedelta(days=(cycle_days * ratio) + offset_days)


def last_close_at_or_before(candles: list[Candle], ts: datetime) -> float | None:
    prior = [c for c in candles if c.ts <= ts]
    if not prior:
        return None
    return prior[-1].close


def marker_by_code(markers: list[MarkerMatch], code: str) -> MarkerMatch | None:
    for marker in markers:
        if marker.code == code:
            return marker
    return None


def pct_return(from_price: float | None, to_price: float | None) -> float | None:
    if from_price is None or to_price is None or from_price == 0:
        return None
    return round(((to_price / from_price) - 1.0) * 100.0, 4)


def safe_float(value: float | None) -> str:
    if value is None:
        return ""
    return str(value)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "status",
        "symbol",
        "anchor_ts_utc",
        "checkpoint_ratio",
        "as_of_ts_utc",
        "selected_partial_offset_days",
        "selected_partial_score",
        "selected_partial_shape",
        "selected_partial_timing",
        "selected_partial_coverage",
        "selected_partial_due_markers",
        "selected_partial_observed_markers",
        "future_target_ratio",
        "future_target_expected_ts_utc",
        "future_target_is_future",
        "as_of_close",
        "return_to_1000_pct",
        "return_to_1272_pct",
        "same_offset_full_score",
        "same_offset_full_shape",
        "same_offset_full_timing",
        "best_full_offset_days",
        "best_full_score",
        "best_full_shape",
        "best_full_timing",
        "offset_matches_best_full",
        "venue",
        "interval_code",
        "cycle_days",
        "tolerance_hours",
        "error",
    ]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def summarize(rows: list[dict[str, Any]]) -> None:
    ok_rows = [r for r in rows if r.get("status") == "OK"]
    if not ok_rows:
        print("summary=no_ok_rows")
        return

    print("")
    print("SUMMARY BY CHECKPOINT")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in ok_rows:
        grouped.setdefault(str(row["checkpoint_ratio"]), []).append(row)

    for checkpoint, checkpoint_rows in sorted(grouped.items(), key=lambda kv: float(kv[0])):
        eligible = [r for r in checkpoint_rows if r["future_target_is_future"] is True]
        selected = [
            r for r in eligible
            if r["selected_partial_score"] is not None
            and float(r["selected_partial_score"]) >= 0.70
        ]

        returns_1000 = [
            float(r["return_to_1000_pct"])
            for r in selected
            if r.get("return_to_1000_pct") not in ("", None)
        ]

        offset_matches = [
            r for r in selected
            if r.get("offset_matches_best_full") is True
        ]

        if selected and returns_1000:
            win_rate = sum(1 for value in returns_1000 if value > 0.0) / len(returns_1000)
            avg_return = mean(returns_1000)
        else:
            win_rate = 0.0
            avg_return = 0.0

        print(
            f"checkpoint={checkpoint} "
            f"ok={len(checkpoint_rows)} "
            f"eligible_future={len(eligible)} "
            f"partial_score_ge_0.70={len(selected)} "
            f"avg_return_to_1000={avg_return:.4f}% "
            f"positive_return_rate={win_rate:.4f} "
            f"offset_match_rate={(len(offset_matches) / len(selected)) if selected else 0.0:.4f}"
        )

    print("")
    print("TOP PARTIAL CANDIDATES")
    ranked = sorted(
        ok_rows,
        key=lambda r: (
            float(r["selected_partial_score"] or 0.0),
            float(r["return_to_1000_pct"] or -9999.0),
        ),
        reverse=True,
    )

    for row in ranked[:20]:
        print(
            f'{row["symbol"]:7s} '
            f'anchor={row["anchor_ts_utc"][:10]} '
            f'cp={row["checkpoint_ratio"]} '
            f'offset={row["selected_partial_offset_days"]:+.1f} '
            f'partial={row["selected_partial_score"]:.4f} '
            f'full_same={row["same_offset_full_score"]:.4f} '
            f'best_full={row["best_full_score"]:.4f} '
            f'ret1000={row["return_to_1000_pct"]} '
            f'future={row["future_target_is_future"]} '
            f'offset_match={row["offset_matches_best_full"]}'
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest partial breath curve checkpoint recognition against future full-cycle outcome."
    )
    parser.add_argument(
        "--symbols",
        default="BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE",
    )
    parser.add_argument(
        "--anchors",
        required=True,
        help="Comma-separated anchor dates.",
    )
    parser.add_argument(
        "--checkpoints",
        default="0.618,0.786",
        help="Comma-separated checkpoint ratios.",
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--min-due-markers", type=int, default=3)
    parser.add_argument(
        "--future-target-ratio",
        type=float,
        default=1.000,
        help="Candidate offset is only eligible if this target is still future at as-of time.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/research/breath_curve_template_matcher_v1",
    )
    args = parser.parse_args()

    symbols = parse_csv_list(args.symbols)
    anchors = [parse_dt(x) for x in parse_csv_list(args.anchors)]
    checkpoints = [float(x) for x in parse_csv_list(args.checkpoints)]
    offsets = parse_offsets(args.offsets)
    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    summary_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []

    for anchor in anchors:
        query_start = anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours + 48)
        query_end = anchor + timedelta(days=args.cycle_days * 1.272 + max(offsets)) + timedelta(
            hours=args.tolerance_hours + 48
        )

        for symbol in symbols:
            try:
                full_candles = load_db(
                    symbol=symbol,
                    asset_id=None,
                    venue=args.venue,
                    interval_code=args.interval_code,
                    start=query_start,
                    end=query_end,
                )

                if len(full_candles) < 5:
                    raise RuntimeError(f"Not enough full-cycle candles loaded: {len(full_candles)}")

                full_results = [
                    match(
                        candles=full_candles,
                        symbol=symbol,
                        venue=args.venue,
                        interval_code=args.interval_code,
                        anchor=anchor,
                        cycle_days=args.cycle_days,
                        offset_days=offset,
                        tolerance_hours=args.tolerance_hours,
                    )
                    for offset in offsets
                ]

                best_full = max(full_results, key=lambda r: r.template_match_score)
                full_by_offset = {r.phase_offset_days: r for r in full_results}

                for checkpoint in checkpoints:
                    as_of = expected_ts(anchor, args.cycle_days, checkpoint, 0.0)
                    partial_candles = [c for c in full_candles if c.ts <= as_of]

                    if len(partial_candles) < 3:
                        raise RuntimeError(
                            f"Not enough partial candles loaded for {symbol} {iso(anchor)} checkpoint {checkpoint}: {len(partial_candles)}"
                        )

                    partial_results = []
                    ranked_candidates = []

                    for offset in offsets:
                        pr = partial_match(
                            candles=partial_candles,
                            symbol=symbol,
                            venue=args.venue,
                            interval_code=args.interval_code,
                            anchor=anchor,
                            as_of=as_of,
                            cycle_days=args.cycle_days,
                            offset_days=offset,
                            tolerance_hours=args.tolerance_hours,
                            min_due_markers=args.min_due_markers,
                            required_ratio=checkpoint,
                        )

                        target_ts = expected_ts(anchor, args.cycle_days, args.future_target_ratio, offset)
                        target_is_future = target_ts > as_of
                        ranking_score = pr.partial_match_score if target_is_future else 0.0

                        partial_results.append(
                            {
                                "result": pr,
                                "ranking_score": ranking_score,
                                "future_target_expected_ts_utc": iso(target_ts),
                                "future_target_is_future": target_is_future,
                            }
                        )
                        ranked_candidates.append((ranking_score, pr.partial_match_score, offset, pr))

                    ranked_candidates.sort(reverse=True, key=lambda x: (x[0], x[1]))
                    selected = ranked_candidates[0][3]
                    selected_offset = selected.phase_offset_days
                    selected_meta = next(x for x in partial_results if x["result"].phase_offset_days == selected_offset)

                    same_full = full_by_offset[selected_offset]
                    same_full_1000 = marker_by_code(same_full.markers, "MAIN_PULSE_TP_HIGH")
                    same_full_1272 = marker_by_code(same_full.markers, "OVERSHOOT_EXTENSION_TP")

                    as_of_close = last_close_at_or_before(full_candles, as_of)

                    return_to_1000 = pct_return(
                        as_of_close,
                        same_full_1000.observed_price if same_full_1000 and same_full_1000.matched else None,
                    )
                    return_to_1272 = pct_return(
                        as_of_close,
                        same_full_1272.observed_price if same_full_1272 and same_full_1272.matched else None,
                    )

                    offset_matches_best_full = selected_offset == best_full.phase_offset_days

                    row = {
                        "status": "OK",
                        "symbol": symbol,
                        "anchor_ts_utc": iso(anchor),
                        "checkpoint_ratio": checkpoint,
                        "as_of_ts_utc": iso(as_of),
                        "selected_partial_offset_days": selected_offset,
                        "selected_partial_score": selected.partial_match_score,
                        "selected_partial_shape": selected.partial_shape_score,
                        "selected_partial_timing": selected.partial_timing_score,
                        "selected_partial_coverage": selected.marker_coverage_score,
                        "selected_partial_due_markers": selected.due_marker_count,
                        "selected_partial_observed_markers": selected.observed_marker_count,
                        "future_target_ratio": args.future_target_ratio,
                        "future_target_expected_ts_utc": selected_meta["future_target_expected_ts_utc"],
                        "future_target_is_future": selected_meta["future_target_is_future"],
                        "as_of_close": as_of_close,
                        "return_to_1000_pct": return_to_1000,
                        "return_to_1272_pct": return_to_1272,
                        "same_offset_full_score": same_full.template_match_score,
                        "same_offset_full_shape": same_full.shape_score,
                        "same_offset_full_timing": same_full.timing_score,
                        "best_full_offset_days": best_full.phase_offset_days,
                        "best_full_score": best_full.template_match_score,
                        "best_full_shape": best_full.shape_score,
                        "best_full_timing": best_full.timing_score,
                        "offset_matches_best_full": offset_matches_best_full,
                        "venue": args.venue,
                        "interval_code": args.interval_code,
                        "cycle_days": args.cycle_days,
                        "tolerance_hours": args.tolerance_hours,
                        "error": "",
                    }

                    summary_rows.append(row)

                    detail_rows.append(
                        {
                            "status": "OK",
                            "symbol": symbol,
                            "anchor_ts_utc": iso(anchor),
                            "checkpoint_ratio": checkpoint,
                            "as_of_ts_utc": iso(as_of),
                            "selected_partial_offset_days": selected_offset,
                            "selected_partial": asdict(selected),
                            "selected_full_same_offset": asdict(same_full),
                            "best_full": asdict(best_full),
                            "all_partial_offsets": [
                                {
                                    "ranking_score": item["ranking_score"],
                                    "future_target_expected_ts_utc": item["future_target_expected_ts_utc"],
                                    "future_target_is_future": item["future_target_is_future"],
                                    "result": asdict(item["result"]),
                                }
                                for item in partial_results
                            ],
                            "all_full_offsets": [asdict(r) for r in full_results],
                        }
                    )

                    print(
                        f"OK symbol={symbol} anchor={iso(anchor)} cp={checkpoint} "
                        f"partial_offset={selected_offset:+.1f} "
                        f"partial_score={selected.partial_match_score:.4f} "
                        f"future={selected_meta['future_target_is_future']} "
                        f"ret1000={return_to_1000} "
                        f"full_same={same_full.template_match_score:.4f} "
                        f"best_full_offset={best_full.phase_offset_days:+.1f} "
                        f"best_full={best_full.template_match_score:.4f} "
                        f"offset_match={offset_matches_best_full}"
                    )

            except Exception as exc:
                err = str(exc)
                for checkpoint in checkpoints:
                    summary_rows.append(
                        {
                            "status": "ERROR",
                            "symbol": symbol,
                            "anchor_ts_utc": iso(anchor),
                            "checkpoint_ratio": checkpoint,
                            "as_of_ts_utc": "",
                            "error": err,
                            "venue": args.venue,
                            "interval_code": args.interval_code,
                            "cycle_days": args.cycle_days,
                            "tolerance_hours": args.tolerance_hours,
                        }
                    )
                    detail_rows.append(
                        {
                            "status": "ERROR",
                            "symbol": symbol,
                            "anchor_ts_utc": iso(anchor),
                            "checkpoint_ratio": checkpoint,
                            "error": err,
                        }
                    )
                print(f"ERROR symbol={symbol} anchor={iso(anchor)} error={err}")

    csv_path = out_dir / f"breath_curve_partial_to_full_v1_{stamp}.csv"
    jsonl_path = out_dir / f"breath_curve_partial_to_full_v1_{stamp}.jsonl"

    write_csv(csv_path, summary_rows)
    write_jsonl(jsonl_path, detail_rows)

    print("")
    print(f"wrote_csv={csv_path}")
    print(f"wrote_jsonl={jsonl_path}")

    summarize(summary_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
