from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev


VERSION = "0.1"


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("status") == "OK"]


def f(value: str) -> float:
    return float(value)


def nearest_half_phase(delta: float, half_phase: float = 10.5, tolerance: float = 2.0) -> bool:
    return abs(abs(delta) - half_phase) <= tolerance


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze phase-offset behavior from breath curve batch CSV output."
    )
    parser.add_argument("--csv", required=True, help="Batch CSV path.")
    parser.add_argument("--btc-symbol", default="BTC")
    parser.add_argument("--half-phase-days", type=float, default=10.5)
    parser.add_argument("--half-phase-tolerance-days", type=float, default=2.0)
    args = parser.parse_args()

    rows = load_rows(Path(args.csv))
    if not rows:
        raise RuntimeError("No OK rows found in CSV.")

    rows_by_anchor: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        rows_by_anchor[row["anchor_ts_utc"]].append(row)
        rows_by_symbol[row["symbol"]].append(row)

    print(f"analyzer=analyze_breath_curve_offsets_v1 version={VERSION}")
    print(f"source={args.csv}")
    print("")

    print("PHASE COHORTS BY ANCHOR")
    for anchor in sorted(rows_by_anchor):
        grouped: dict[float, list[str]] = defaultdict(list)
        for row in rows_by_anchor[anchor]:
            grouped[f(row["best_phase_offset_days"])].append(row["symbol"])

        print(f"\nanchor={anchor[:10]}")
        for offset in sorted(grouped):
            symbols = ",".join(sorted(grouped[offset]))
            print(f"  offset={offset:>5.1f} symbols={symbols}")

    print("\nOFFSET TRANSITIONS BY SYMBOL")
    for symbol in sorted(rows_by_symbol):
        symbol_rows = sorted(rows_by_symbol[symbol], key=lambda r: r["anchor_ts_utc"])
        offsets = [f(r["best_phase_offset_days"]) for r in symbol_rows]
        scores = [f(r["template_match_score"]) for r in symbol_rows]
        deltas = [offsets[i] - offsets[i - 1] for i in range(1, len(offsets))]

        transition = " -> ".join(f"{x:+.1f}" for x in offsets)
        delta_text = " / ".join(f"{x:+.1f}" for x in deltas) if deltas else "n/a"
        print(
            f"  {symbol:7s} offsets={transition:22s} "
            f"deltas={delta_text:13s} "
            f"avg_score={mean(scores):.4f} "
            f"offset_stdev={pstdev(offsets):.4f}"
        )

    btc_by_anchor = {
        row["anchor_ts_utc"]: f(row["best_phase_offset_days"])
        for row in rows
        if row["symbol"] == args.btc_symbol
    }

    print("\nDELTA VS BTC")
    for anchor in sorted(rows_by_anchor):
        if anchor not in btc_by_anchor:
            continue

        btc_offset = btc_by_anchor[anchor]
        print(f"\nanchor={anchor[:10]} btc_offset={btc_offset:+.1f}")

        for row in sorted(rows_by_anchor[anchor], key=lambda r: r["symbol"]):
            symbol = row["symbol"]
            offset = f(row["best_phase_offset_days"])
            delta = offset - btc_offset
            half_phase = nearest_half_phase(
                delta,
                half_phase=args.half_phase_days,
                tolerance=args.half_phase_tolerance_days,
            )
            tag = "HALF_PHASE_SPLIT" if half_phase else ""
            print(
                f"  {symbol:7s} offset={offset:+5.1f} "
                f"delta_vs_btc={delta:+5.1f} {tag}"
            )

    print("\nINITIAL HEURISTIC FLAGS")
    for symbol in sorted(rows_by_symbol):
        symbol_rows = sorted(rows_by_symbol[symbol], key=lambda r: r["anchor_ts_utc"])
        offsets = [f(r["best_phase_offset_days"]) for r in symbol_rows]
        scores = [f(r["template_match_score"]) for r in symbol_rows]
        offset_sd = pstdev(offsets)
        avg_score = mean(scores)

        if offset_sd <= 1.5:
            stability = "STABLE_OFFSET"
        elif offset_sd <= 5.0:
            stability = "MODERATE_DRIFT"
        else:
            stability = "UNSTABLE_OR_REGIME_SHIFT"

        if avg_score >= 0.80:
            quality = "HIGH_AVG_ALIGNMENT"
        elif avg_score >= 0.72:
            quality = "MEDIUM_AVG_ALIGNMENT"
        else:
            quality = "LOW_AVG_ALIGNMENT"

        print(
            f"  {symbol:7s} {stability:24s} {quality:22s} "
            f"avg_score={avg_score:.4f} offset_stdev={offset_sd:.4f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
