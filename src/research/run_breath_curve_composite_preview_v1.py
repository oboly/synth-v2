from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable


REPORT_NAME = "breath_curve_composite_preview_v1"
VERSION = "0.1"


@dataclass(frozen=True)
class CompositeSpec:
    composite_name: str
    purpose: str
    predicate: Callable[[dict[str, Any]], bool]


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def as_float(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null", "nan"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def fmt(value: Any, places: int = 4) -> str:
    parsed = as_float(value)
    if parsed is None:
        return ""

    text = f"{parsed:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def latest_input_csv(default_dir: str) -> Path:
    paths = sorted(
        Path(default_dir).glob("breath_curve_symbol_regime_validation_v1_*_enriched_rows.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not paths:
        raise RuntimeError(f"No symbol/regime enriched rows CSV found under {default_dir}")

    return paths[0]


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def is_ok(row: dict[str, Any]) -> bool:
    return str(row.get("status", "")).strip() == "OK"


def is_0618_selected_minus8(row: dict[str, Any]) -> bool:
    return (
        is_ok(row)
        and str(row.get("checkpoint_ratio", "")).strip() == "0.618"
        and str(row.get("selected_band_w1_0", "")).strip() == "-8"
    )


def is_0618_selected_early(row: dict[str, Any]) -> bool:
    return (
        is_ok(row)
        and str(row.get("checkpoint_ratio", "")).strip() == "0.618"
        and str(row.get("selected_band_w1_0", "")).strip() in {"-8", "-7"}
    )


def is_symbol_subset(row: dict[str, Any], symbols: set[str]) -> bool:
    return str(row.get("symbol", "")).strip() in symbols


def is_volume_expansion(row: dict[str, Any]) -> bool:
    return str(row.get("symbol_volume_bucket", "")).strip() == "VOLUME_EXPANSION"


def is_btc_eth_bear(row: dict[str, Any]) -> bool:
    return str(row.get("btc_eth_context_bucket", "")).strip() == "BTC_ETH_BEAR"


def is_btc_eth_not_bull(row: dict[str, Any]) -> bool:
    return str(row.get("btc_eth_context_bucket", "")).strip() != "BTC_ETH_BULL"


def composite_specs(core_symbols: set[str]) -> list[CompositeSpec]:
    return [
        CompositeSpec(
            composite_name="minus8_all_v1",
            purpose="baseline calibrated -8 early pulse candidate",
            predicate=lambda row: is_0618_selected_minus8(row),
        ),
        CompositeSpec(
            composite_name="minus8_core_symbols_v1",
            purpose="selected -8 restricted to current positive symbol subset",
            predicate=lambda row: is_0618_selected_minus8(row) and is_symbol_subset(row, core_symbols),
        ),
        CompositeSpec(
            composite_name="minus8_btc_eth_bear_v1",
            purpose="selected -8 when BTC/ETH context is bearish",
            predicate=lambda row: is_0618_selected_minus8(row) and is_btc_eth_bear(row),
        ),
        CompositeSpec(
            composite_name="minus8_volume_expansion_v1",
            purpose="selected -8 with symbol volume expansion",
            predicate=lambda row: is_0618_selected_minus8(row) and is_volume_expansion(row),
        ),
        CompositeSpec(
            composite_name="minus8_core_and_btc_eth_bear_v1",
            purpose="selected -8 in core symbols and BTC/ETH bearish context",
            predicate=lambda row: (
                is_0618_selected_minus8(row)
                and is_symbol_subset(row, core_symbols)
                and is_btc_eth_bear(row)
            ),
        ),
        CompositeSpec(
            composite_name="minus8_core_and_volume_expansion_v1",
            purpose="selected -8 in core symbols with volume expansion",
            predicate=lambda row: (
                is_0618_selected_minus8(row)
                and is_symbol_subset(row, core_symbols)
                and is_volume_expansion(row)
            ),
        ),
        CompositeSpec(
            composite_name="minus8_core_and_bear_or_volume_v1",
            purpose="selected -8 in core symbols with BTC/ETH bear or volume expansion",
            predicate=lambda row: (
                is_0618_selected_minus8(row)
                and is_symbol_subset(row, core_symbols)
                and (is_btc_eth_bear(row) or is_volume_expansion(row))
            ),
        ),
        CompositeSpec(
            composite_name="early_band_core_and_bear_or_volume_v1",
            purpose="broader -7/-8 recall candidate in core symbols with context support",
            predicate=lambda row: (
                is_0618_selected_early(row)
                and is_symbol_subset(row, core_symbols)
                and (is_btc_eth_bear(row) or is_volume_expansion(row))
            ),
        ),
        CompositeSpec(
            composite_name="minus8_core_not_btc_eth_bull_v1",
            purpose="selected -8 in core symbols excluding BTC/ETH bull context",
            predicate=lambda row: (
                is_0618_selected_minus8(row)
                and is_symbol_subset(row, core_symbols)
                and is_btc_eth_not_bull(row)
            ),
        ),
    ]


def values(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []

    for row in rows:
        value = as_float(row.get(key))
        if value is not None:
            out.append(value)

    return out


def summarize(evaluated_rows: list[dict[str, Any]], selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ret1000 = values(selected_rows, "return_to_1000_pct")
    ret1272 = values(selected_rows, "return_to_1272_pct")
    partial = values(selected_rows, "selected_partial_score")

    def avg(items: list[float]) -> float | None:
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    def med(items: list[float]) -> float | None:
        if not items:
            return None
        return round(float(median(items)), 4)

    def positive_rate(items: list[float]) -> float | None:
        if not items:
            return None
        return round(sum(1 for item in items if item > 0.0) / len(items) * 100.0, 4)

    evaluated = len(evaluated_rows)
    eligible = len(selected_rows)

    return {
        "evaluated_rows": evaluated,
        "eligible_rows": eligible,
        "selection_rate_pct": round(eligible / evaluated * 100.0, 4) if evaluated else None,
        "avg_partial_score": avg(partial),
        "avg_return_to_1000_pct": avg(ret1000),
        "median_return_to_1000_pct": med(ret1000),
        "positive_to_1000_pct": positive_rate(ret1000),
        "best_return_to_1000_pct": max(ret1000) if ret1000 else None,
        "worst_return_to_1000_pct": min(ret1000) if ret1000 else None,
        "avg_return_to_1272_pct": avg(ret1272),
        "median_return_to_1272_pct": med(ret1272),
        "positive_to_1272_pct": positive_rate(ret1272),
        "best_return_to_1272_pct": max(ret1272) if ret1272 else None,
        "worst_return_to_1272_pct": min(ret1272) if ret1272 else None,
    }


def source_summary(rows: list[dict[str, Any]], specs: list[CompositeSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in specs:
        for source in ("real", "random"):
            evaluated = [row for row in rows if is_ok(row) and row.get("source") == source]
            selected = [row for row in evaluated if spec.predicate(row)]
            out.append(
                {
                    "composite_name": spec.composite_name,
                    "composite_purpose": spec.purpose,
                    "source": source,
                    **summarize(evaluated, selected),
                }
            )

    return out


def comparison_summary(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = {(row["composite_name"], row["source"]): row for row in summary_rows}
    composites = sorted({row["composite_name"] for row in summary_rows})
    out: list[dict[str, Any]] = []

    for composite in composites:
        real = grouped.get((composite, "real"), {})
        random_row = grouped.get((composite, "random"), {})

        real_avg = real.get("avg_return_to_1000_pct")
        random_avg = random_row.get("avg_return_to_1000_pct")
        real_sel = real.get("selection_rate_pct")
        random_sel = random_row.get("selection_rate_pct")
        real_worst = real.get("worst_return_to_1000_pct")
        random_worst = random_row.get("worst_return_to_1000_pct")
        real_pos = real.get("positive_to_1000_pct")
        random_pos = random_row.get("positive_to_1000_pct")

        out.append(
            {
                "composite_name": composite,
                "real_evaluated": real.get("evaluated_rows"),
                "real_eligible": real.get("eligible_rows"),
                "real_selection_rate_pct": real_sel,
                "real_avg_return_to_1000_pct": real_avg,
                "real_positive_to_1000_pct": real_pos,
                "real_worst_return_to_1000_pct": real_worst,
                "real_avg_return_to_1272_pct": real.get("avg_return_to_1272_pct"),
                "random_evaluated": random_row.get("evaluated_rows"),
                "random_eligible": random_row.get("eligible_rows"),
                "random_selection_rate_pct": random_sel,
                "random_avg_return_to_1000_pct": random_avg,
                "random_positive_to_1000_pct": random_pos,
                "random_worst_return_to_1000_pct": random_worst,
                "random_avg_return_to_1272_pct": random_row.get("avg_return_to_1272_pct"),
                "edge_avg_return_to_1000_pct": round(real_avg - random_avg, 4)
                if real_avg is not None and random_avg is not None
                else None,
                "edge_positive_to_1000_pct": round(real_pos - random_pos, 4)
                if real_pos is not None and random_pos is not None
                else None,
                "edge_worst_return_to_1000_pct": round(real_worst - random_worst, 4)
                if real_worst is not None and random_worst is not None
                else None,
                "selection_rate_delta_pct": round(real_sel - random_sel, 4)
                if real_sel is not None and random_sel is not None
                else None,
            }
        )

    return out


def selected_rows(rows: list[dict[str, Any]], specs: list[CompositeSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in specs:
        for row in rows:
            if spec.predicate(row):
                out.append(
                    {
                        **row,
                        "composite_name": spec.composite_name,
                        "composite_purpose": spec.purpose,
                    }
                )

    return out


def group_summary(
    rows: list[dict[str, Any]],
    specs: list[CompositeSpec],
    group_keys: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in specs:
        for source in ("real", "random"):
            evaluated_base = [row for row in rows if is_ok(row) and row.get("source") == source]
            group_values = sorted(
                {
                    tuple(str(row.get(group_key, "")) for group_key in group_keys)
                    for row in evaluated_base
                }
            )

            for group_value in group_values:
                group_dict = {group_keys[idx]: group_value[idx] for idx in range(len(group_keys))}
                evaluated = [
                    row
                    for row in evaluated_base
                    if all(str(row.get(key, "")) == group_dict[key] for key in group_keys)
                ]
                selected = [row for row in evaluated if spec.predicate(row)]

                out.append(
                    {
                        "composite_name": spec.composite_name,
                        "source": source,
                        **group_dict,
                        **summarize(evaluated, selected),
                    }
                )

    return out


def print_comparison(rows: list[dict[str, Any]]) -> None:
    print("--- composite real vs random comparison ---")
    print_table(
        [
            "composite",
            "real_elig",
            "real_sel",
            "real_avg1000",
            "real_pos",
            "real_worst",
            "rand_elig",
            "rand_sel",
            "rand_avg1000",
            "rand_pos",
            "rand_worst",
            "edge1000",
            "edge_pos",
            "edge_worst",
            "sel_delta",
        ],
        [
            [
                str(row["composite_name"]),
                str(row["real_eligible"]),
                fmt(row["real_selection_rate_pct"], 2),
                fmt(row["real_avg_return_to_1000_pct"]),
                fmt(row["real_positive_to_1000_pct"], 2),
                fmt(row["real_worst_return_to_1000_pct"]),
                str(row["random_eligible"]),
                fmt(row["random_selection_rate_pct"], 2),
                fmt(row["random_avg_return_to_1000_pct"]),
                fmt(row["random_positive_to_1000_pct"], 2),
                fmt(row["random_worst_return_to_1000_pct"]),
                fmt(row["edge_avg_return_to_1000_pct"]),
                fmt(row["edge_positive_to_1000_pct"], 2),
                fmt(row["edge_worst_return_to_1000_pct"]),
                fmt(row["selection_rate_delta_pct"], 2),
            ]
            for row in rows
        ],
    )


def print_source_summary(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- composite source summary ---")
    print_table(
        [
            "composite",
            "source",
            "eval",
            "eligible",
            "sel_rate",
            "partial",
            "avg1000",
            "pos1000",
            "worst1000",
            "avg1272",
            "pos1272",
        ],
        [
            [
                str(row["composite_name"]),
                str(row["source"]),
                str(row["evaluated_rows"]),
                str(row["eligible_rows"]),
                fmt(row["selection_rate_pct"], 2),
                fmt(row["avg_partial_score"]),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
            ]
            for row in rows
        ],
    )


def print_group_summary(title: str, group_keys: list[str], rows: list[dict[str, Any]], limit: int) -> None:
    print()
    print(title)
    print_table(
        ["composite", "source"]
        + group_keys
        + [
            "eval",
            "eligible",
            "sel_rate",
            "avg1000",
            "pos1000",
            "worst1000",
            "avg1272",
            "pos1272",
        ],
        [
            [
                str(row["composite_name"]),
                str(row["source"]),
                *[str(row.get(key, "")) for key in group_keys],
                str(row["evaluated_rows"]),
                str(row["eligible_rows"]),
                fmt(row["selection_rate_pct"], 2),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
            ]
            for row in rows[:limit]
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only composite preview for Breath Curve 0.618 selected -8 filters."
    )
    parser.add_argument("--input-csv", default=None)
    parser.add_argument("--default-dir", default="data/research/breath_curve_symbol_regime_validation_v1")
    parser.add_argument("--out-dir", default="data/research/breath_curve_composite_preview_v1")
    parser.add_argument("--core-symbols", default="TAO,ETH,FIL,BTC")
    parser.add_argument("--limit-print", type=int, default=120)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_csv = Path(args.input_csv) if args.input_csv else latest_input_csv(args.default_dir)
    rows = [row for row in load_rows(input_csv) if is_ok(row)]
    core_symbols = set(parse_csv_list(args.core_symbols))
    specs = composite_specs(core_symbols)

    selected = selected_rows(rows, specs)
    source_rows = source_summary(rows, specs)
    comparison_rows = comparison_summary(source_rows)
    symbol_rows = group_summary(rows, specs, ["symbol"])
    btc_eth_rows = group_summary(rows, specs, ["btc_eth_context_bucket"])
    volume_rows = group_summary(rows, specs, ["symbol_volume_bucket"])
    rsi_rows = group_summary(rows, specs, ["symbol_rsi_bucket"])
    trend_rows = group_summary(rows, specs, ["symbol_trend_bucket"])

    out_dir = Path(args.out_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    selected_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_selected_rows.csv"
    source_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_source_summary.csv"
    comparison_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_comparison.csv"
    symbol_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_symbol_summary.csv"
    btc_eth_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_btc_eth_summary.csv"
    volume_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_volume_summary.csv"
    rsi_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_rsi_summary.csv"
    trend_path = out_dir / f"breath_curve_composite_preview_v1_{stamp}_trend_summary.csv"

    write_csv(selected_path, selected)
    write_csv(source_path, source_rows)
    write_csv(comparison_path, comparison_rows)
    write_csv(symbol_path, symbol_rows)
    write_csv(btc_eth_path, btc_eth_rows)
    write_csv(volume_path, volume_rows)
    write_csv(rsi_path, rsi_rows)
    write_csv(trend_path, trend_rows)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print("post_hoc_fields_used_as_filters=0")
        print(f"input_csv={input_csv}")
        print(f"core_symbols={','.join(sorted(core_symbols))}")
        print(f"ok_rows={len(rows)} selected_rows={len(selected)}")
        print()

        print_comparison(comparison_rows)
        print_source_summary(source_rows)
        print_group_summary(
            "--- composite by symbol ---",
            ["symbol"],
            symbol_rows,
            args.limit_print,
        )
        print_group_summary(
            "--- composite by BTC/ETH context ---",
            ["btc_eth_context_bucket"],
            btc_eth_rows,
            args.limit_print,
        )
        print_group_summary(
            "--- composite by volume bucket ---",
            ["symbol_volume_bucket"],
            volume_rows,
            args.limit_print,
        )
        print_group_summary(
            "--- composite by RSI bucket ---",
            ["symbol_rsi_bucket"],
            rsi_rows,
            args.limit_print,
        )
        print_group_summary(
            "--- composite by trend bucket ---",
            ["symbol_trend_bucket"],
            trend_rows,
            args.limit_print,
        )

        print()
        print(f"wrote_selected_rows={selected_path}")
        print(f"wrote_source_summary={source_path}")
        print(f"wrote_comparison={comparison_path}")
        print(f"wrote_symbol_summary={symbol_path}")
        print(f"wrote_btc_eth_summary={btc_eth_path}")
        print(f"wrote_volume_summary={volume_path}")
        print(f"wrote_rsi_summary={rsi_path}")
        print(f"wrote_trend_summary={trend_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
