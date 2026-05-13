from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from src.research.parse_aplus_canonical_table1_v1 import parse_file
from src.research.run_breath_curve_regime_gated_policy_preview_v1 import (
    build_gates,
    parse_symbols,
)


REPORT_NAME = "aplus_table1_regime_gate_validation_v1"
VERSION = "0.1"

DEFAULT_APLUS_RAW = "data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt"
DEFAULT_POLICY_DIR = "data/research/breath_curve_regime_gated_policy_preview_v1"
DEFAULT_OUT_DIR = "data/research/aplus_table1_regime_gate_validation_v1"
DEFAULT_CORE_SYMBOLS = "BTC,ETH,FIL,TAO"
DEFAULT_ALT_CORE_SYMBOLS = "ETH,FIL,TAO"


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
        writer.writerows(rows)


def latest_matching(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)

    if not matches:
        raise FileNotFoundError(f"No files matching {pattern!r} in {directory}")

    return matches[0]


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


def get_symbol(row: dict[str, Any]) -> str:
    return str(row.get("_symbol") or row.get("symbol") or "").strip().upper()


def get_source(row: dict[str, Any]) -> str:
    return str(row.get("_source") or row.get("source") or "").strip().lower()


def get_return_to_1000(row: dict[str, Any]) -> float | None:
    return as_float(
        row.get("_return_to_1000_pct")
        or row.get("return_to_1000_pct")
        or row.get("return_to_1_000_pct")
    )


def classify_aplus(row: dict[str, Any]) -> str:
    if (
        row["structural_role"] == "leader"
        and row["coherence"] == "high"
        and row["geometry"] in {"clean", "mixed"}
        and row["expansion_quality"] in {"strong", "moderate"}
        and row["anchor_strength"] in {"strong", "moderate"}
        and row["strategic_bias"] in {"accumulation", "continuation"}
    ):
        return "APLUS_CANONICAL_CORE"

    if row["strategic_bias"] == "avoid":
        return "APLUS_AVOID"

    if (
        row["structural_role"] in {"defensive", "confirmer"}
        and row["anchor_strength"] in {"strong", "moderate"}
        and row["strategic_bias"] in {"accumulation", "continuation", "neutral"}
    ):
        return "APLUS_ANCHOR_CONTEXT"

    if row["strategic_bias"] == "caution":
        return "APLUS_CAUTION"

    return "APLUS_OTHER"


def load_aplus_map(path: Path) -> dict[str, dict[str, Any]]:
    rows = parse_file(path)
    out: dict[str, dict[str, Any]] = {}

    for row in rows:
        enriched = dict(row)
        enriched["aplus_bucket"] = classify_aplus(row)
        out[str(row["token"]).upper()] = enriched

    return out


def enrich_policy_rows(policy_rows: list[dict[str, Any]], aplus_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in policy_rows:
        symbol = get_symbol(row)
        aplus = aplus_map.get(symbol)

        if aplus is None:
            enriched = dict(row)
            enriched.update(
                {
                    "symbol": symbol,
                    "aplus_bucket": "APLUS_MISSING",
                    "aplus_phase": "",
                    "aplus_coherence": "",
                    "aplus_field": "",
                    "aplus_geometry": "",
                    "aplus_structural_role": "",
                    "aplus_expansion_quality": "",
                    "aplus_anchor_strength": "",
                    "aplus_strategic_bias": "",
                    "aplus_notes": "",
                }
            )
            out.append(enriched)
            continue

        enriched = dict(row)
        enriched.update(
            {
                "symbol": symbol,
                "aplus_bucket": aplus["aplus_bucket"],
                "aplus_phase": aplus["phase"],
                "aplus_coherence": aplus["coherence"],
                "aplus_field": aplus["field"],
                "aplus_geometry": aplus["geometry"],
                "aplus_structural_role": aplus["structural_role"],
                "aplus_expansion_quality": aplus["expansion_quality"],
                "aplus_anchor_strength": aplus["anchor_strength"],
                "aplus_strategic_bias": aplus["strategic_bias"],
                "aplus_notes": aplus["notes"],
            }
        )
        out.append(enriched)

    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [
        value
        for value in (get_return_to_1000(row) for row in rows)
        if value is not None
    ]

    if not returns:
        return {
            "eligible": 0,
            "avg1000": None,
            "pos1000": None,
            "worst1000": None,
            "best1000": None,
        }

    return {
        "eligible": len(returns),
        "avg1000": round(mean(returns), 4),
        "pos1000": round(sum(1 for value in returns if value > 0) / len(returns) * 100.0, 4),
        "worst1000": round(min(returns), 4),
        "best1000": round(max(returns), 4),
    }


def summarize_by_gate_aplus(rows: list[dict[str, Any]], gates: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for gate in gates:
        for row in rows:
            if not gate.fn(row):
                continue

            grouped[
                (
                    gate.gate_id,
                    str(row.get("regime_class", "")),
                    get_source(row),
                    str(row.get("aplus_bucket", "APLUS_MISSING")),
                )
            ].append(row)

    out: list[dict[str, Any]] = []

    for (gate_id, regime_class, source, aplus_bucket), group in sorted(grouped.items()):
        summary = summarize(group)
        out.append(
            {
                "gate_id": gate_id,
                "regime_class": regime_class,
                "source": source,
                "aplus_bucket": aplus_bucket,
                **summary,
            }
        )

    return out


def summarize_gate_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for row in rows:
        by_key[
            (
                str(row.get("gate_id")),
                str(row.get("regime_class")),
                str(row.get("source")),
                str(row.get("aplus_bucket")),
            )
        ] = row

    gate_ids = sorted({str(row.get("gate_id")) for row in rows})
    buckets = sorted({str(row.get("aplus_bucket")) for row in rows})

    out: list[dict[str, Any]] = []

    for gate_id in gate_ids:
        for bucket in buckets:
            win_real = by_key.get((gate_id, "WINNING_REGIME", "real", bucket), {})
            win_random = by_key.get((gate_id, "WINNING_REGIME", "random", bucket), {})
            fail_real = by_key.get((gate_id, "FAILING_REGIME", "real", bucket), {})
            fail_random = by_key.get((gate_id, "FAILING_REGIME", "random", bucket), {})

            win_edge = edge(win_real, win_random)
            fail_edge = edge(fail_real, fail_random)
            separation = None
            if win_edge is not None and fail_edge is not None:
                separation = round(win_edge - fail_edge, 4)

            out.append(
                {
                    "gate_id": gate_id,
                    "aplus_bucket": bucket,
                    "win_real": int(win_real.get("eligible", 0) or 0),
                    "win_rand": int(win_random.get("eligible", 0) or 0),
                    "win_edge": win_edge,
                    "win_worst": win_real.get("worst1000"),
                    "fail_real": int(fail_real.get("eligible", 0) or 0),
                    "fail_rand": int(fail_random.get("eligible", 0) or 0),
                    "fail_edge": fail_edge,
                    "fail_worst": fail_real.get("worst1000"),
                    "separation": separation,
                    "read": read_edge_bucket(win_real, win_random, fail_real, fail_random, win_edge, fail_edge, separation),
                }
            )

    return sorted(
        out,
        key=lambda row: (
            as_float(row.get("separation")) if as_float(row.get("separation")) is not None else -9999,
            int(row.get("win_real", 0)),
        ),
        reverse=True,
    )


def edge(real_row: dict[str, Any], random_row: dict[str, Any]) -> float | None:
    real_avg = as_float(real_row.get("avg1000"))
    random_avg = as_float(random_row.get("avg1000"))

    if real_avg is None or random_avg is None:
        return None

    return round(real_avg - random_avg, 4)


def read_edge_bucket(
    win_real: dict[str, Any],
    win_random: dict[str, Any],
    fail_real: dict[str, Any],
    fail_random: dict[str, Any],
    win_edge: float | None,
    fail_edge: float | None,
    separation: float | None,
) -> str:
    win_real_n = int(win_real.get("eligible", 0) or 0)
    win_rand_n = int(win_random.get("eligible", 0) or 0)
    fail_real_n = int(fail_real.get("eligible", 0) or 0)
    fail_rand_n = int(fail_random.get("eligible", 0) or 0)
    win_worst = as_float(win_real.get("worst1000"))

    if win_edge is None:
        return "NO_WINNING_COMPARISON"

    if win_real_n < 3:
        return "SAMPLE_TOO_THIN"

    if win_rand_n < 10:
        return "RANDOM_TOO_THIN"

    if win_edge <= 0:
        return "NO_WINNING_EDGE"

    if win_worst is None or win_worst <= 0:
        return "BAD_WINNING_WORST"

    if fail_edge is None or separation is None or fail_real_n < 2 or fail_rand_n < 10:
        return "REGIME_SAMPLE_THIN"

    if separation >= 5:
        return "APLUS_REGIME_GATE_CANDIDATE"

    return "WEAK_SEPARATION"


def summarize_symbols(rows: list[dict[str, Any]], gates: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for gate in gates:
        for row in rows:
            if not gate.fn(row):
                continue

            grouped[
                (
                    gate.gate_id,
                    str(row.get("regime_class", "")),
                    get_source(row),
                    str(row.get("aplus_bucket", "APLUS_MISSING")),
                    get_symbol(row),
                )
            ].append(row)

    out: list[dict[str, Any]] = []

    for (gate_id, regime_class, source, aplus_bucket, symbol), group in sorted(grouped.items()):
        summary = summarize(group)
        out.append(
            {
                "gate_id": gate_id,
                "regime_class": regime_class,
                "source": source,
                "aplus_bucket": aplus_bucket,
                "symbol": symbol,
                **summary,
            }
        )

    return out


def print_aplus_summary(aplus_map: dict[str, dict[str, Any]]) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)

    for token, row in sorted(aplus_map.items()):
        grouped[str(row["aplus_bucket"])].append(token)

    print("--- A+ Table 1 buckets ---")
    for bucket in sorted(grouped):
        print(f"{bucket}={','.join(grouped[bucket])}")


def print_edge_rows(rows: list[dict[str, Any]], limit: int) -> None:
    print()
    print("--- A+ bucket edge comparison ---")
    print_table(
        [
            "gate",
            "aplus_bucket",
            "win_real",
            "win_rand",
            "win_edge",
            "win_worst",
            "fail_real",
            "fail_rand",
            "fail_edge",
            "separation",
            "read",
        ],
        [
            [
                str(row.get("gate_id")),
                str(row.get("aplus_bucket")),
                str(row.get("win_real")),
                str(row.get("win_rand")),
                fmt(row.get("win_edge")),
                fmt(row.get("win_worst")),
                str(row.get("fail_real")),
                str(row.get("fail_rand")),
                fmt(row.get("fail_edge")),
                fmt(row.get("separation")),
                str(row.get("read")),
            ]
            for row in rows[:limit]
        ],
    )


def print_symbol_rows(rows: list[dict[str, Any]], limit: int) -> None:
    print()
    print("--- symbol summary ---")
    print_table(
        ["gate", "regime", "source", "bucket", "symbol", "eligible", "avg1000", "worst1000"],
        [
            [
                str(row.get("gate_id")),
                str(row.get("regime_class")),
                str(row.get("source")),
                str(row.get("aplus_bucket")),
                str(row.get("symbol")),
                str(row.get("eligible")),
                fmt(row.get("avg1000")),
                fmt(row.get("worst1000")),
            ]
            for row in rows[:limit]
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only validation of A+ canonical Table 1 against Breath Curve regime-gated policy preview rows."
    )
    parser.add_argument("--aplus-raw", default=DEFAULT_APLUS_RAW)
    parser.add_argument("--policy-dir", default=DEFAULT_POLICY_DIR)
    parser.add_argument("--policy-csv", default="")
    parser.add_argument("--core-symbols", default=DEFAULT_CORE_SYMBOLS)
    parser.add_argument("--alt-core-symbols", default=DEFAULT_ALT_CORE_SYMBOLS)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit-print", type=int, default=120)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    aplus_raw = Path(args.aplus_raw)
    aplus_map = load_aplus_map(aplus_raw)

    if args.policy_csv:
        policy_csv = Path(args.policy_csv)
    else:
        policy_csv = latest_matching(Path(args.policy_dir), "*_policy_rows.csv")

    policy_rows = read_csv(policy_csv)
    enriched_rows = enrich_policy_rows(policy_rows, aplus_map)

    core_symbols = parse_symbols(args.core_symbols)
    alt_core_symbols = parse_symbols(args.alt_core_symbols)
    gates = build_gates(core_symbols, alt_core_symbols)

    bucket_summary = summarize_by_gate_aplus(enriched_rows, gates)
    edge_summary = summarize_gate_edges(bucket_summary)
    symbol_summary = summarize_symbols(enriched_rows, gates)

    out_dir = Path(args.out_dir)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    enriched_path = out_dir / f"aplus_table1_regime_gate_validation_v1_{run_stamp}_enriched_rows.csv"
    bucket_summary_path = out_dir / f"aplus_table1_regime_gate_validation_v1_{run_stamp}_bucket_summary.csv"
    edge_summary_path = out_dir / f"aplus_table1_regime_gate_validation_v1_{run_stamp}_edge_summary.csv"
    symbol_summary_path = out_dir / f"aplus_table1_regime_gate_validation_v1_{run_stamp}_symbol_summary.csv"

    write_csv(enriched_path, enriched_rows)
    write_csv(bucket_summary_path, bucket_summary)
    write_csv(edge_summary_path, edge_summary)
    write_csv(symbol_summary_path, symbol_summary)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print(f"aplus_raw={aplus_raw}")
        print(f"policy_csv={policy_csv}")
        print(f"aplus_rows={len(aplus_map)}")
        print(f"policy_rows={len(policy_rows)}")
        print(f"enriched_rows={len(enriched_rows)}")
        print()

        print_aplus_summary(aplus_map)
        print_edge_rows(edge_summary, args.limit_print)
        print_symbol_rows(symbol_summary, args.limit_print)

        print()
        print(f"wrote_enriched_rows={enriched_path}")
        print(f"wrote_bucket_summary={bucket_summary_path}")
        print(f"wrote_edge_summary={edge_summary_path}")
        print(f"wrote_symbol_summary={symbol_summary_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
