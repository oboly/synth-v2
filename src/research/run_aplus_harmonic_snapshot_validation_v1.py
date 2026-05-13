from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "aplus_harmonic_snapshot_validation_v1"
VERSION = "0.1"

DEFAULT_POLICY_NAMES = (
    "breath_curve_research_policy_0618_v1,"
    "breath_curve_research_policy_0786_extension_v1,"
    "breath_curve_research_policy_0618_offset_match_v1,"
    "breath_curve_research_policy_0786_offset_match_v1"
)


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal("1").scaleb(-places)
    text = format(dec.quantize(q), "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


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


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


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


def load_aplus_snapshot(path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {str(row["token"]): row for row in rows}


def aplus_bucket(row: dict[str, Any] | None) -> str:
    if row is None:
        return "NO_APLUS_LABEL"

    phase_marker = str(row.get("phase_marker", "unclear"))
    recognition = str(row.get("recognition_0618", "unclear"))
    regime_fit = str(row.get("regime_fit", "unclear"))
    clean_dirty = str(row.get("clean_or_dirty", "unclear"))
    extension = str(row.get("extension_1272", "unclear"))

    if (
        phase_marker == "0.618"
        and recognition == "confirmed"
        and regime_fit == "high"
        and clean_dirty == "clean"
    ):
        return "APLUS_CLEAN_0618_CONFIRMED"

    if phase_marker in {"1.000", "1.272"} and extension == "exceeded":
        if clean_dirty == "clean":
            return "APLUS_CLEAN_LATE_EXTENSION"
        return "APLUS_DIRTY_LATE_OVERFLOW"

    if phase_marker in {"0.236", "0.382", "0.500"} and recognition == "forming":
        return "APLUS_FORMING_EARLY"

    if phase_marker == "0.786":
        return "APLUS_0786_OVERFLOW_PRESSURE"

    if phase_marker == "unclear":
        return "APLUS_UNCLEAR"

    return "APLUS_OTHER"


def policy_label_from_row(row: dict[str, Any]) -> str:
    checkpoint = fmt(row["checkpoint_ratio"], 3)
    offset_required = bool(row["require_offset_match"])

    if checkpoint == "0.618" and offset_required:
        return "0618_offset_match"
    if checkpoint == "0.618":
        return "0618_all"
    if checkpoint == "0.786" and offset_required:
        return "0786_offset_match"
    if checkpoint == "0.786":
        return "0786_all"

    return f"{checkpoint}_{int(offset_required)}"


def fetch_real_policy_rows(conn: Any, policy_names: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join(["%s"] * len(policy_names))

    sql = f"""
    SELECT
        r.policy_name,
        r.checkpoint_set,
        r.require_offset_match,
        x.symbol,
        x.anchor_date,
        x.checkpoint_ratio,
        x.offset_matches_best_full,
        x.return_to_1000_pct,
        x.return_to_1272_pct,
        x.policy_return_pct
    FROM research_breath_curve_policy_run r
    JOIN (
        SELECT
            policy_name,
            MAX(research_breath_curve_policy_run_id) AS latest_run_id
        FROM research_breath_curve_policy_run
        WHERE policy_name IN ({placeholders})
        GROUP BY policy_name
    ) latest
      ON latest.latest_run_id = r.research_breath_curve_policy_run_id
    JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    ORDER BY
        r.policy_name,
        x.symbol,
        x.anchor_date,
        x.checkpoint_ratio
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, policy_names)
        return list(cur.fetchall())


def latest_file(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matched {directory}/{pattern}")
    return files[-1]


def load_random_samples(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def metric(values: list[float | None], total_count: int | None = None) -> dict[str, Any]:
    nums = [float(v) for v in values if v is not None]

    denominator = total_count if total_count is not None else len(nums)

    return {
        "rows": len(nums),
        "denominator": denominator,
        "selection_rate_pct": round(len(nums) / denominator * 100.0, 4) if denominator else None,
        "avg": round(sum(nums) / len(nums), 4) if nums else None,
        "median": round(float(median(nums)), 4) if nums else None,
        "positive_rate_pct": round(sum(1 for x in nums if x > 0) / len(nums) * 100.0, 4) if nums else None,
        "best": max(nums) if nums else None,
        "worst": min(nums) if nums else None,
    }


def summarize_real(rows: list[dict[str, Any]], snapshot: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float | None]] = defaultdict(list)

    for row in rows:
        symbol = str(row["symbol"])
        bucket = aplus_bucket(snapshot.get(symbol))
        policy_bucket = policy_label_from_row(row)
        grouped[(bucket, policy_bucket)].append(as_float(row["policy_return_pct"]))

    out: list[dict[str, Any]] = []

    for (bucket, policy_bucket), returns in sorted(grouped.items()):
        m = metric(returns)
        out.append(
            {
                "source": "REAL",
                "aplus_bucket": bucket,
                "policy_bucket": policy_bucket,
                **m,
            }
        )

    return out


def summarize_random(samples: list[dict[str, Any]], snapshot: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    total_by_group: dict[tuple[str, str], int] = defaultdict(int)
    returns_by_group: dict[tuple[str, str], list[float | None]] = defaultdict(list)

    for row in samples:
        symbol = str(row["symbol"])
        checkpoint = str(row["checkpoint_ratio"])
        checkpoint_prefix = checkpoint.replace("0.", "0")
        bucket = aplus_bucket(snapshot.get(symbol))

        all_bucket = f"{checkpoint_prefix}_all"
        total_by_group[(bucket, all_bucket)] += 1

        if as_bool(row.get("eligible_all")):
            returns_by_group[(bucket, all_bucket)].append(as_float(row.get("policy_return_pct")))

        offset_bucket = f"{checkpoint_prefix}_offset_match"
        total_by_group[(bucket, offset_bucket)] += 1

        if as_bool(row.get("eligible_offset_match")):
            returns_by_group[(bucket, offset_bucket)].append(as_float(row.get("policy_return_pct")))

    out: list[dict[str, Any]] = []

    for key in sorted(total_by_group):
        bucket, policy_bucket = key
        m = metric(returns_by_group.get(key, []), total_count=total_by_group[key])
        out.append(
            {
                "source": "RANDOM",
                "aplus_bucket": bucket,
                "policy_bucket": policy_bucket,
                **m,
            }
        )

    return out


def index_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (str(row["source"]), str(row["aplus_bucket"]), str(row["policy_bucket"])): row
        for row in rows
    }


def comparison_rows(real_rows: list[dict[str, Any]], random_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rindex = index_rows(real_rows)
    rndex = index_rows(random_rows)

    out: list[dict[str, Any]] = []

    for _, bucket, policy_bucket in sorted(rindex):
        real = rindex[("REAL", bucket, policy_bucket)]
        rnd = rndex.get(("RANDOM", bucket, policy_bucket))

        if rnd is None:
            continue

        real_avg = real.get("avg")
        random_avg = rnd.get("avg")

        out.append(
            {
                "aplus_bucket": bucket,
                "policy_bucket": policy_bucket,
                "real_rows": real.get("rows"),
                "random_candidates": rnd.get("denominator"),
                "random_eligible": rnd.get("rows"),
                "random_selection_rate_pct": rnd.get("selection_rate_pct"),
                "real_avg": real_avg,
                "random_avg": random_avg,
                "real_minus_random": round(real_avg - random_avg, 4) if real_avg is not None and random_avg is not None else None,
                "real_pos": real.get("positive_rate_pct"),
                "random_pos": rnd.get("positive_rate_pct"),
                "real_worst": real.get("worst"),
                "random_worst": rnd.get("worst"),
            }
        )

    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only A+ harmonic snapshot validation.")
    parser.add_argument("--snapshot-jsonl", default="data/external/aplus_harmonic_phase_overlay/aplus_breathline_harmonic_snapshot_20260513_0358.jsonl")
    parser.add_argument("--random-dir", default="data/research/breath_curve_random_anchor_baseline_v2")
    parser.add_argument("--random-samples-csv", default="")
    parser.add_argument("--real-policy-names", default=DEFAULT_POLICY_NAMES)
    parser.add_argument("--out-dir", default="data/research/aplus_harmonic_snapshot_validation_v1")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args()

    load_dotenv(dotenv_path=".env", override=False)

    snapshot_path = Path(args.snapshot_jsonl)
    snapshot = load_aplus_snapshot(snapshot_path)

    random_samples_path = Path(args.random_samples_csv) if args.random_samples_csv else latest_file(Path(args.random_dir), "*samples*.csv")
    random_samples = load_random_samples(random_samples_path)

    conn = get_db_connection()
    try:
        real_policy_rows = fetch_real_policy_rows(conn, parse_csv_list(args.real_policy_names))
    finally:
        conn.close()

    real_summary = summarize_real(real_policy_rows, snapshot)
    random_summary = summarize_random(random_samples, snapshot)
    comparisons = comparison_rows(real_summary, random_summary)

    out_dir = Path(args.out_dir)
    write_csv(out_dir / "aplus_harmonic_snapshot_validation_real_summary.csv", real_summary)
    write_csv(out_dir / "aplus_harmonic_snapshot_validation_random_summary.csv", random_summary)
    write_csv(out_dir / "aplus_harmonic_snapshot_validation_comparison.csv", comparisons)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("runtime_layer_touch=none")
        print(f"snapshot={snapshot_path}")
        print(f"random_samples={random_samples_path}")
        print(f"real_rows={len(real_policy_rows)} random_rows={len(random_samples)}")
        print("")

        print("--- A+ bucket comparison: real vs same-symbol random ---")
        print_table(
            [
                "aplus_bucket",
                "policy_bucket",
                "real_rows",
                "rand_total",
                "rand_elig",
                "rand_sel",
                "real_avg",
                "rand_avg",
                "real-rand",
                "real_pos",
                "rand_pos",
                "real_worst",
                "rand_worst",
            ],
            [
                [
                    str(row["aplus_bucket"]),
                    str(row["policy_bucket"]),
                    str(row["real_rows"]),
                    str(row["random_candidates"]),
                    str(row["random_eligible"]),
                    fmt(row["random_selection_rate_pct"], 2),
                    fmt(row["real_avg"]),
                    fmt(row["random_avg"]),
                    fmt(row["real_minus_random"]),
                    fmt(row["real_pos"], 2),
                    fmt(row["random_pos"], 2),
                    fmt(row["real_worst"]),
                    fmt(row["random_worst"]),
                ]
                for row in comparisons
            ],
        )

        print("")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
