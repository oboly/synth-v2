from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable


REPORT_NAME = "breath_curve_regime_gated_policy_preview_v1"
VERSION = "0.1"

CORE_SYMBOLS_DEFAULT = "BTC,ETH,FIL,TAO"
ALT_CORE_SYMBOLS_DEFAULT = "ETH,FIL,TAO"
TARGET_COMPOSITE_DEFAULT = "minus8_core_symbols_v1"

MINUS8_POLICY = "0618_selected_minus8_v1"
EARLY_BAND_POLICY = "0618_selected_early_band_v1"


@dataclass(frozen=True)
class RunMeta:
    run_dir: Path
    run_id: str
    regime_class: str
    target_edge: float | None
    target_real_eligible: int


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    description: str
    fn: Callable[[dict[str, Any]], bool]


def as_float(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def as_int(value: Any) -> int:
    parsed = as_float(value)
    if parsed is None:
        return 0
    return int(parsed)


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


def read_csv(path: Path) -> list[dict[str, Any]]:
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


def discover_run_dirs(default_dir: str) -> list[Path]:
    root = Path(default_dir)
    return sorted(
        [
            path
            for path in root.glob("breath_curve_broader_history_v1_*")
            if path.is_dir() and (path / "aggregate_comparison_summary.csv").exists()
        ],
        key=lambda path: path.stat().st_mtime,
    )


def manifest_is_zero_post_pad(run_dir: Path) -> bool:
    path = run_dir / "cohort_manifest.csv"

    if not path.exists():
        return False

    rows = read_csv(path)

    if not rows:
        return False

    for row in rows:
        anchors = [x.strip() for x in str(row.get("anchors", "")).split(",") if x.strip()]
        random_window_end = str(row.get("random_window_end", "")).strip()

        if not anchors:
            return False

        latest_anchor = anchors[-1]

        if random_window_end != latest_anchor:
            return False

    return True


def manifest_signature(run_dir: Path) -> str:
    path = run_dir / "cohort_manifest.csv"

    if not path.exists():
        return f"NO_MANIFEST::{run_dir.name}"

    rows = read_csv(path)
    parts = []

    for row in rows:
        parts.append(
            "|".join(
                [
                    str(row.get("anchors", "")),
                    str(row.get("random_window_start", "")),
                    str(row.get("random_window_end", "")),
                ]
            )
        )

    return "\n".join(sorted(parts))


def dedupe_run_dirs_by_manifest(run_dirs: list[Path]) -> list[Path]:
    by_signature: dict[str, Path] = {}

    for run_dir in run_dirs:
        signature = manifest_signature(run_dir)
        current = by_signature.get(signature)

        if current is None or run_dir.stat().st_mtime > current.stat().st_mtime:
            by_signature[signature] = run_dir

    return sorted(by_signature.values(), key=lambda path: path.stat().st_mtime)


def classify_run(
    run_dir: Path,
    *,
    target_composite: str,
    min_winning_real_eligible: int,
) -> RunMeta:
    aggregate_rows = read_csv(run_dir / "aggregate_comparison_summary.csv")

    target = next(
        (row for row in aggregate_rows if row.get("composite_name") == target_composite),
        None,
    )

    if target is None:
        return RunMeta(
            run_dir=run_dir,
            run_id=run_dir.name,
            regime_class="UNKNOWN_NO_TARGET",
            target_edge=None,
            target_real_eligible=0,
        )

    edge = as_float(target.get("edge_avg_return_to_1000_pct"))
    real_eligible = as_int(target.get("real_eligible"))

    if edge is not None and edge > 0 and real_eligible >= min_winning_real_eligible:
        regime_class = "WINNING_REGIME"
    elif edge is not None and edge <= 0:
        regime_class = "FAILING_REGIME"
    else:
        regime_class = "NEUTRAL_OR_SAMPLE_THIN"

    return RunMeta(
        run_dir=run_dir,
        run_id=run_dir.name,
        regime_class=regime_class,
        target_edge=edge,
        target_real_eligible=real_eligible,
    )


def latest_matching(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        return None
    return matches[0]


def row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return ""


def get_return_to_1000(row: dict[str, Any]) -> float | None:
    return as_float(
        row_value(
            row,
            "return_to_1000_pct",
            "return_to_1_000_pct",
            "return_to_1000",
            "target_return_to_1000_pct",
            "real_return_to_1000_pct",
        )
    )


def get_policy(row: dict[str, Any]) -> str:
    return str(row_value(row, "policy_name", "policy", "filter_name")).strip()


def get_source(row: dict[str, Any]) -> str:
    return str(row_value(row, "source", "row_source")).strip().lower()


def get_symbol(row: dict[str, Any]) -> str:
    return str(row_value(row, "symbol")).strip().upper()


def get_btc_eth_context(row: dict[str, Any]) -> str:
    return str(row_value(row, "btc_eth_context_bucket", "btc_eth_context")).strip().upper()


def get_volume_bucket(row: dict[str, Any]) -> str:
    return str(row_value(row, "symbol_volume_bucket", "volume_bucket")).strip().upper()


def get_rsi_bucket(row: dict[str, Any]) -> str:
    return str(row_value(row, "symbol_rsi_bucket", "rsi_bucket")).strip().upper()


def get_trend_bucket(row: dict[str, Any]) -> str:
    return str(row_value(row, "symbol_trend_bucket", "trend_bucket")).strip().upper()


def is_minus8(row: dict[str, Any]) -> bool:
    policy = get_policy(row)
    selected_band = str(row_value(row, "selected_band_w1_0", "selected_band")).strip()

    return policy == MINUS8_POLICY or selected_band == "-8"


def is_early_band(row: dict[str, Any]) -> bool:
    return get_policy(row) == EARLY_BAND_POLICY


def build_gates(core_symbols: set[str], alt_core_symbols: set[str]) -> list[GateSpec]:
    return [
        GateSpec(
            gate_id="gate_01_minus8_core_symbols",
            description="selected -8 + core symbols",
            fn=lambda row: is_minus8(row) and get_symbol(row) in core_symbols,
        ),
        GateSpec(
            gate_id="gate_02_minus8_core_btc_eth_bear",
            description="selected -8 + core symbols + BTC_ETH_BEAR",
            fn=lambda row: is_minus8(row)
            and get_symbol(row) in core_symbols
            and get_btc_eth_context(row) == "BTC_ETH_BEAR",
        ),
        GateSpec(
            gate_id="gate_03_minus8_core_volume_expansion",
            description="selected -8 + core symbols + VOLUME_EXPANSION",
            fn=lambda row: is_minus8(row)
            and get_symbol(row) in core_symbols
            and get_volume_bucket(row) == "VOLUME_EXPANSION",
        ),
        GateSpec(
            gate_id="gate_04_minus8_core_rsi_mid_high",
            description="selected -8 + core symbols + RSI_MID/HIGH",
            fn=lambda row: is_minus8(row)
            and get_symbol(row) in core_symbols
            and get_rsi_bucket(row) in {"RSI_MID", "RSI_HIGH"},
        ),
        GateSpec(
            gate_id="gate_05_minus8_core_bear_volume",
            description="selected -8 + core symbols + BTC_ETH_BEAR + VOLUME_EXPANSION",
            fn=lambda row: is_minus8(row)
            and get_symbol(row) in core_symbols
            and get_btc_eth_context(row) == "BTC_ETH_BEAR"
            and get_volume_bucket(row) == "VOLUME_EXPANSION",
        ),
        GateSpec(
            gate_id="gate_06_minus8_alt_core_participation_proxy",
            description="selected -8 + alt-core participation proxy ETH/FIL/TAO",
            fn=lambda row: is_minus8(row) and get_symbol(row) in alt_core_symbols,
        ),
        GateSpec(
            gate_id="gate_07_minus8_alt_core_bear_volume_or_rsi",
            description="selected -8 + alt-core proxy + BTC_ETH_BEAR + volume expansion or RSI_MID/HIGH",
            fn=lambda row: is_minus8(row)
            and get_symbol(row) in alt_core_symbols
            and get_btc_eth_context(row) == "BTC_ETH_BEAR"
            and (
                get_volume_bucket(row) == "VOLUME_EXPANSION"
                or get_rsi_bucket(row) in {"RSI_MID", "RSI_HIGH"}
            ),
        ),
        GateSpec(
            gate_id="gate_08_early_band_core_bear_or_volume",
            description="early band + core symbols + BTC_ETH_BEAR or VOLUME_EXPANSION",
            fn=lambda row: is_early_band(row)
            and get_symbol(row) in core_symbols
            and (
                get_btc_eth_context(row) == "BTC_ETH_BEAR"
                or get_volume_bucket(row) == "VOLUME_EXPANSION"
            ),
        ),
    ]


def load_policy_rows(run_metas: list[RunMeta]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for run_meta in run_metas:
        for cohort_dir in sorted(run_meta.run_dir.glob("cohort_*")):
            if not cohort_dir.is_dir():
                continue

            symbol_regime_dir = cohort_dir / "symbol_regime"
            if not symbol_regime_dir.exists():
                continue

            policy_path = latest_matching(symbol_regime_dir, "*_policy_rows.csv")
            if policy_path is None:
                policy_path = latest_matching(symbol_regime_dir, "*_enriched_rows.csv")

            if policy_path is None:
                continue

            for row in read_csv(policy_path):
                row_source = get_source(row)
                if row_source not in {"real", "random"}:
                    continue

                row_return = get_return_to_1000(row)
                if row_return is None:
                    continue

                out.append(
                    {
                        **row,
                        "run_id": run_meta.run_id,
                        "run_dir": str(run_meta.run_dir),
                        "regime_class": run_meta.regime_class,
                        "target_edge_for_run": run_meta.target_edge,
                        "target_real_eligible_for_run": run_meta.target_real_eligible,
                        "cohort_id": cohort_dir.name,
                        "row_source_file": str(policy_path),
                        "_source": row_source,
                        "_symbol": get_symbol(row),
                        "_return_to_1000_pct": row_return,
                        "_policy_name": get_policy(row),
                        "_btc_eth_context": get_btc_eth_context(row),
                        "_volume_bucket": get_volume_bucket(row),
                        "_rsi_bucket": get_rsi_bucket(row),
                        "_trend_bucket": get_trend_bucket(row),
                    }
                )

    return out


def summarize_returns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [
        value
        for value in (as_float(row.get("_return_to_1000_pct")) for row in rows)
        if value is not None
    ]

    if not returns:
        return {
            "eligible_rows": 0,
            "avg_return_to_1000_pct": None,
            "positive_to_1000_pct": None,
            "worst_return_to_1000_pct": None,
            "best_return_to_1000_pct": None,
        }

    return {
        "eligible_rows": len(returns),
        "avg_return_to_1000_pct": round(mean(returns), 4),
        "positive_to_1000_pct": round(sum(1 for value in returns if value > 0) / len(returns) * 100.0, 4),
        "worst_return_to_1000_pct": round(min(returns), 4),
        "best_return_to_1000_pct": round(max(returns), 4),
    }


def gate_source_summary(rows: list[dict[str, Any]], gates: list[GateSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for gate in gates:
        matched = [row for row in rows if gate.fn(row)]

        for regime_class in sorted({str(row.get("regime_class")) for row in rows}):
            for source in ["real", "random"]:
                subset = [
                    row
                    for row in matched
                    if row.get("regime_class") == regime_class and row.get("_source") == source
                ]
                summary = summarize_returns(subset)

                out.append(
                    {
                        "gate_id": gate.gate_id,
                        "description": gate.description,
                        "regime_class": regime_class,
                        "source": source,
                        **summary,
                    }
                )

    return out


def gate_regime_comparison(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for row in summary_rows:
        by_key[(str(row.get("gate_id")), str(row.get("regime_class")) + "::" + str(row.get("source")))] = row

    gates = sorted({str(row.get("gate_id")) for row in summary_rows})
    out: list[dict[str, Any]] = []

    for gate_id in gates:
        win_real = by_key.get((gate_id, "WINNING_REGIME::real"), {})
        win_random = by_key.get((gate_id, "WINNING_REGIME::random"), {})
        fail_real = by_key.get((gate_id, "FAILING_REGIME::real"), {})
        fail_random = by_key.get((gate_id, "FAILING_REGIME::random"), {})

        win_edge = edge_between(win_real, win_random)
        fail_edge = edge_between(fail_real, fail_random)

        separation = None
        if win_edge is not None and fail_edge is not None:
            separation = round(win_edge - fail_edge, 4)

        out.append(
            {
                "gate_id": gate_id,
                "description": next(
                    (str(row.get("description")) for row in summary_rows if row.get("gate_id") == gate_id),
                    "",
                ),
                "winning_real_eligible": as_int(win_real.get("eligible_rows")),
                "winning_random_eligible": as_int(win_random.get("eligible_rows")),
                "winning_real_avg1000": win_real.get("avg_return_to_1000_pct"),
                "winning_random_avg1000": win_random.get("avg_return_to_1000_pct"),
                "winning_edge1000": win_edge,
                "winning_real_worst1000": win_real.get("worst_return_to_1000_pct"),
                "failing_real_eligible": as_int(fail_real.get("eligible_rows")),
                "failing_random_eligible": as_int(fail_random.get("eligible_rows")),
                "failing_real_avg1000": fail_real.get("avg_return_to_1000_pct"),
                "failing_random_avg1000": fail_random.get("avg_return_to_1000_pct"),
                "failing_edge1000": fail_edge,
                "failing_real_worst1000": fail_real.get("worst_return_to_1000_pct"),
                "edge_separation": separation,
                "preview_status": preview_status(win_real, win_random, fail_real, fail_random, win_edge, fail_edge, separation),
            }
        )

    return sorted(
        out,
        key=lambda row: as_float(row.get("edge_separation")) if as_float(row.get("edge_separation")) is not None else -9999,
        reverse=True,
    )


def edge_between(real_row: dict[str, Any], random_row: dict[str, Any]) -> float | None:
    real_avg = as_float(real_row.get("avg_return_to_1000_pct"))
    random_avg = as_float(random_row.get("avg_return_to_1000_pct"))

    if real_avg is None or random_avg is None:
        return None

    return round(real_avg - random_avg, 4)


def preview_status(
    win_real: dict[str, Any],
    win_random: dict[str, Any],
    fail_real: dict[str, Any],
    fail_random: dict[str, Any],
    win_edge: float | None,
    fail_edge: float | None,
    separation: float | None,
) -> str:
    win_real_n = as_int(win_real.get("eligible_rows"))
    win_random_n = as_int(win_random.get("eligible_rows"))
    fail_real_n = as_int(fail_real.get("eligible_rows"))
    fail_random_n = as_int(fail_random.get("eligible_rows"))
    win_worst = as_float(win_real.get("worst_return_to_1000_pct"))

    if win_edge is None or fail_edge is None or separation is None:
        return "INSUFFICIENT_COMPARISON"

    if win_real_n < 5:
        return "SAMPLE_THIN"

    if win_random_n < 10:
        return "RANDOM_SAMPLE_THIN"

    if win_edge <= 0:
        return "NO_WINNING_EDGE"

    if separation < 5:
        return "LOW_REGIME_SEPARATION"

    if win_worst is None or win_worst <= 0:
        return "BAD_WINNING_WORST"

    if fail_real_n < 3 or fail_random_n < 10:
        return "REGIME_GATE_CANDIDATE_SAMPLE_THIN"

    return "REGIME_GATE_CANDIDATE"


def gate_symbol_summary(rows: list[dict[str, Any]], gates: list[GateSpec]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for gate in gates:
        matched = [row for row in rows if gate.fn(row)]

        for row in matched:
            grouped[
                (
                    gate.gate_id,
                    str(row.get("regime_class")),
                    str(row.get("_source")),
                    str(row.get("_symbol")),
                )
            ].append(row)

    out: list[dict[str, Any]] = []

    for (gate_id, regime_class, source, symbol), group in sorted(grouped.items()):
        summary = summarize_returns(group)
        out.append(
            {
                "gate_id": gate_id,
                "regime_class": regime_class,
                "source": source,
                "symbol": symbol,
                **summary,
            }
        )

    return out


def parse_symbols(value: str) -> set[str]:
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def print_run_metas(rows: list[RunMeta]) -> None:
    print("--- run classification ---")
    print_table(
        ["run", "class", "target_edge", "real_elig"],
        [
            [
                row.run_id,
                row.regime_class,
                fmt(row.target_edge),
                str(row.target_real_eligible),
            ]
            for row in rows
        ],
    )


def print_gate_comparison(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- regime-gated policy preview comparison ---")
    print_table(
        [
            "gate",
            "status",
            "win_real",
            "win_rand",
            "win_edge",
            "win_worst",
            "fail_real",
            "fail_rand",
            "fail_edge",
            "separation",
        ],
        [
            [
                str(row.get("gate_id")),
                str(row.get("preview_status")),
                str(row.get("winning_real_eligible")),
                str(row.get("winning_random_eligible")),
                fmt(row.get("winning_edge1000")),
                fmt(row.get("winning_real_worst1000")),
                str(row.get("failing_real_eligible")),
                str(row.get("failing_random_eligible")),
                fmt(row.get("failing_edge1000")),
                fmt(row.get("edge_separation")),
            ]
            for row in rows
        ],
    )


def print_symbol_summary(rows: list[dict[str, Any]], limit: int) -> None:
    print()
    print("--- gate symbol summary ---")
    print_table(
        [
            "gate",
            "regime",
            "source",
            "symbol",
            "eligible",
            "avg1000",
            "worst1000",
            "pos1000",
        ],
        [
            [
                str(row.get("gate_id")),
                str(row.get("regime_class")),
                str(row.get("source")),
                str(row.get("symbol")),
                str(row.get("eligible_rows")),
                fmt(row.get("avg_return_to_1000_pct")),
                fmt(row.get("worst_return_to_1000_pct")),
                fmt(row.get("positive_to_1000_pct"), 2),
            ]
            for row in rows[:limit]
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only regime-gated policy preview for Breath Curve selected -8."
    )
    parser.add_argument("--default-dir", default="data/research/breath_curve_broader_history_v1")
    parser.add_argument("--target-composite", default=TARGET_COMPOSITE_DEFAULT)
    parser.add_argument("--core-symbols", default=CORE_SYMBOLS_DEFAULT)
    parser.add_argument("--alt-core-symbols", default=ALT_CORE_SYMBOLS_DEFAULT)
    parser.add_argument("--min-winning-real-eligible", type=int, default=10)
    parser.add_argument("--include-duplicate-manifests", action="store_true")
    parser.add_argument("--include-non-zero-post-pad-runs", action="store_true")
    parser.add_argument("--out-dir", default="data/research/breath_curve_regime_gated_policy_preview_v1")
    parser.add_argument("--limit-print", type=int, default=120)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    run_dirs = discover_run_dirs(args.default_dir)
    discovered_run_count = len(run_dirs)

    if not args.include_non_zero_post_pad_runs:
        run_dirs = [run_dir for run_dir in run_dirs if manifest_is_zero_post_pad(run_dir)]

    zero_post_pad_filtered_count = len(run_dirs)

    if not args.include_duplicate_manifests:
        run_dirs = dedupe_run_dirs_by_manifest(run_dirs)

    deduped_run_count = len(run_dirs)

    run_metas = [
        classify_run(
            run_dir,
            target_composite=args.target_composite,
            min_winning_real_eligible=args.min_winning_real_eligible,
        )
        for run_dir in run_dirs
    ]

    core_symbols = parse_symbols(args.core_symbols)
    alt_core_symbols = parse_symbols(args.alt_core_symbols)
    gates = build_gates(core_symbols, alt_core_symbols)

    policy_rows = load_policy_rows(run_metas)
    source_summary_rows = gate_source_summary(policy_rows, gates)
    comparison_rows = gate_regime_comparison(source_summary_rows)
    symbol_summary_rows = gate_symbol_summary(policy_rows, gates)

    out_dir = Path(args.out_dir)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    run_meta_path = out_dir / f"breath_curve_regime_gated_policy_preview_v1_{run_stamp}_run_meta.csv"
    policy_rows_path = out_dir / f"breath_curve_regime_gated_policy_preview_v1_{run_stamp}_policy_rows.csv"
    source_summary_path = out_dir / f"breath_curve_regime_gated_policy_preview_v1_{run_stamp}_source_summary.csv"
    comparison_path = out_dir / f"breath_curve_regime_gated_policy_preview_v1_{run_stamp}_comparison.csv"
    symbol_summary_path = out_dir / f"breath_curve_regime_gated_policy_preview_v1_{run_stamp}_symbol_summary.csv"

    write_csv(
        run_meta_path,
        [
            {
                "run_id": row.run_id,
                "run_dir": str(row.run_dir),
                "regime_class": row.regime_class,
                "target_edge": row.target_edge,
                "target_real_eligible": row.target_real_eligible,
            }
            for row in run_metas
        ],
    )
    write_csv(policy_rows_path, policy_rows)
    write_csv(source_summary_path, source_summary_rows)
    write_csv(comparison_path, comparison_rows)
    write_csv(symbol_summary_path, symbol_summary_rows)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print(f"target_composite={args.target_composite}")
        print(f"core_symbols={','.join(sorted(core_symbols))}")
        print(f"alt_core_symbols={','.join(sorted(alt_core_symbols))}")
        print(f"discovered_run_count={discovered_run_count}")
        print(f"zero_post_pad_filtered_count={zero_post_pad_filtered_count}")
        print(f"deduped_run_count={deduped_run_count}")
        print(f"loaded_policy_rows={len(policy_rows)}")
        print()

        print_run_metas(run_metas)
        print_gate_comparison(comparison_rows)
        print_symbol_summary(symbol_summary_rows, args.limit_print)

        print()
        print(f"wrote_run_meta={run_meta_path}")
        print(f"wrote_policy_rows={policy_rows_path}")
        print(f"wrote_source_summary={source_summary_path}")
        print(f"wrote_comparison={comparison_path}")
        print(f"wrote_symbol_summary={symbol_summary_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
