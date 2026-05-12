from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean
from typing import Any


VERSION = "0.1"
DEFAULT_OUT_DIR = Path("data/research/breath_curve_policy_backtest_v1")


@dataclass(frozen=True)
class PolicyConfig:
    policy_name: str
    min_partial_score: Decimal
    checkpoints: tuple[str, ...]
    tp1_weight: Decimal
    tp2_weight: Decimal
    require_offset_match: bool
    cost_bps: Decimal


@dataclass(frozen=True)
class PolicyRow:
    symbol: str
    anchor_date: str
    checkpoint_ratio: str
    selected_partial_offset_days: str
    selected_partial_score: Decimal
    selected_partial_shape: Decimal
    selected_partial_timing: Decimal
    offset_matches_best_full: bool
    return_to_1000_pct: Decimal | None
    return_to_1272_pct: Decimal | None
    policy_return_pct: Decimal
    policy_state: str
    policy_name: str


def dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null", "nan"}:
        return default

    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: Decimal | None, places: int = 4) -> str:
    if value is None:
        return ""
    q = Decimal("1").scaleb(-places)
    return format(value.quantize(q), "f")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def eligible(row: dict[str, str], config: PolicyConfig) -> tuple[bool, str]:
    checkpoint = str(row.get("checkpoint_ratio", "")).strip()
    if checkpoint not in config.checkpoints:
        return False, "CHECKPOINT_NOT_SELECTED"

    partial_score = dec(row.get("selected_partial_score"))
    if partial_score is None:
        return False, "MISSING_PARTIAL_SCORE"

    if partial_score < config.min_partial_score:
        return False, "PARTIAL_SCORE_BELOW_THRESHOLD"

    if config.require_offset_match and not truthy(row.get("offset_matches_best_full")):
        return False, "OFFSET_MATCH_REQUIRED"

    if dec(row.get("return_to_1000_pct")) is None and dec(row.get("return_to_1272_pct")) is None:
        return False, "NO_RETURN_TARGET"

    future_flag = row.get("future_target_is_future")
    if future_flag is not None and str(future_flag).strip() != "" and not truthy(future_flag):
        return False, "TARGET_NOT_FUTURE"

    return True, "ELIGIBLE"


def calc_policy_return(row: dict[str, str], config: PolicyConfig) -> Decimal:
    ret1000 = dec(row.get("return_to_1000_pct"))
    ret1272 = dec(row.get("return_to_1272_pct"))

    tp1_weight = config.tp1_weight
    tp2_weight = config.tp2_weight

    if ret1272 is None:
        tp1_weight = Decimal("1")
        tp2_weight = Decimal("0")

    if ret1000 is None:
        tp1_weight = Decimal("0")
        tp2_weight = Decimal("1")

    gross = Decimal("0")
    if ret1000 is not None:
        gross += tp1_weight * ret1000
    if ret1272 is not None:
        gross += tp2_weight * ret1272

    cost_pct = config.cost_bps / Decimal("100")
    return gross - cost_pct


def run_policy(rows: list[dict[str, str]], config: PolicyConfig) -> list[PolicyRow]:
    out: list[PolicyRow] = []

    for row in rows:
        is_eligible, state = eligible(row, config)
        if not is_eligible:
            continue

        out.append(
            PolicyRow(
                symbol=str(row.get("symbol", "")),
                anchor_date=str(row.get("anchor_date", "")),
                checkpoint_ratio=str(row.get("checkpoint_ratio", "")),
                selected_partial_offset_days=str(row.get("selected_partial_offset_days", "")),
                selected_partial_score=dec(row.get("selected_partial_score"), Decimal("0")) or Decimal("0"),
                selected_partial_shape=dec(row.get("selected_partial_shape"), Decimal("0")) or Decimal("0"),
                selected_partial_timing=dec(row.get("selected_partial_timing"), Decimal("0")) or Decimal("0"),
                offset_matches_best_full=truthy(row.get("offset_matches_best_full")),
                return_to_1000_pct=dec(row.get("return_to_1000_pct")),
                return_to_1272_pct=dec(row.get("return_to_1272_pct")),
                policy_return_pct=calc_policy_return(row, config),
                policy_state=state,
                policy_name=config.policy_name,
            )
        )

    return out


def summarize(rows: list[PolicyRow]) -> dict[str, Any]:
    returns = [r.policy_return_pct for r in rows]
    positive = [r for r in rows if r.policy_return_pct > 0]

    if not rows:
        return {
            "trades": 0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "positive_rate_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
        }

    sorted_returns = sorted(returns)
    n = len(sorted_returns)
    if n % 2:
        median = sorted_returns[n // 2]
    else:
        median = (sorted_returns[n // 2 - 1] + sorted_returns[n // 2]) / Decimal("2")

    return {
        "trades": len(rows),
        "avg_return_pct": sum(returns) / Decimal(str(len(returns))),
        "median_return_pct": median,
        "positive_rate_pct": Decimal(str(len(positive))) / Decimal(str(len(rows))) * Decimal("100"),
        "best_return_pct": max(returns),
        "worst_return_pct": min(returns),
    }


def grouped_summary(rows: list[PolicyRow], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[PolicyRow]] = {}

    for row in rows:
        value = str(getattr(row, key))
        groups.setdefault(value, []).append(row)

    out: list[dict[str, Any]] = []
    for value, group_rows in sorted(groups.items()):
        summary = summarize(group_rows)
        summary[key] = value
        out.append(summary)

    return out


def print_summary(title: str, summary: dict[str, Any]) -> None:
    print(title)
    print(f"trades={summary['trades']}")
    print(f"avg_return_pct={fmt(summary['avg_return_pct'])}")
    print(f"median_return_pct={fmt(summary['median_return_pct'])}")
    print(f"positive_rate_pct={fmt(summary['positive_rate_pct'], 2)}")
    print(f"best_return_pct={fmt(summary['best_return_pct'])}")
    print(f"worst_return_pct={fmt(summary['worst_return_pct'])}")


def write_outputs(rows: list[PolicyRow], out_dir: Path, config: PolicyConfig) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_policy_name = "".join(
        ch if ch.isalnum() or ch in {"_", "-"} else "_"
        for ch in config.policy_name
    )

    file_stem = f"breath_curve_research_policy_backtest_v1_{safe_policy_name}_{stamp}"

    csv_path = out_dir / f"{file_stem}.csv"
    jsonl_path = out_dir / f"{file_stem}.jsonl"
    summary_path = out_dir / f"{file_stem}_summary.json"

    fieldnames = list(asdict(rows[0]).keys()) if rows else list(PolicyRow.__dataclass_fields__.keys())

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            record = asdict(row)
            writer.writerow({k: str(v) for k, v in record.items()})

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            record = asdict(row)
            f.write(json.dumps({k: str(v) for k, v in record.items()}, sort_keys=True) + "\n")

    summary = {
        "version": VERSION,
        "config": {k: str(v) for k, v in asdict(config).items()},
        "overall": {k: str(v) for k, v in summarize(rows).items()},
        "by_symbol": [{k: str(v) for k, v in item.items()} for item in grouped_summary(rows, "symbol")],
        "by_checkpoint": [{k: str(v) for k, v in item.items()} for item in grouped_summary(rows, "checkpoint_ratio")],
        "by_offset_match": [{k: str(v) for k, v in item.items()} for item in grouped_summary(rows, "offset_matches_best_full")],
    }

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return csv_path, jsonl_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only breath curve policy backtest from partial-to-full labels."
    )
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--policy-name", default="breath_curve_research_policy_v1")
    parser.add_argument("--min-partial-score", default="0.70")
    parser.add_argument("--checkpoints", default="0.618")
    parser.add_argument("--tp1-weight", default="0.50")
    parser.add_argument("--tp2-weight", default="0.50")
    parser.add_argument("--cost-bps", default="20")
    parser.add_argument("--require-offset-match", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_csv = Path(args.input_csv)
    if not input_csv.exists():
        print(f"FAIL: input CSV not found: {input_csv}")
        return 1

    config = PolicyConfig(
        policy_name=str(args.policy_name),
        min_partial_score=Decimal(str(args.min_partial_score)),
        checkpoints=tuple(x.strip() for x in str(args.checkpoints).split(",") if x.strip()),
        tp1_weight=Decimal(str(args.tp1_weight)),
        tp2_weight=Decimal(str(args.tp2_weight)),
        require_offset_match=bool(args.require_offset_match),
        cost_bps=Decimal(str(args.cost_bps)),
    )

    raw_rows = load_rows(input_csv)
    policy_rows = run_policy(raw_rows, config)
    csv_path, jsonl_path, summary_path = write_outputs(policy_rows, Path(args.out_dir), config)

    if args.output == "table":
        print(f"report=breath_curve_research_policy_backtest_v1 version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("orders=none decision_gate=none execution_planner=none executor=none")
        print(f"input_csv={input_csv}")
        print(f"raw_rows={len(raw_rows)}")
        print(f"policy_rows={len(policy_rows)}")
        print(f"policy_name={config.policy_name}")
        print(f"checkpoints={','.join(config.checkpoints)}")
        print(f"min_partial_score={config.min_partial_score}")
        print(f"tp1_weight={config.tp1_weight} tp2_weight={config.tp2_weight}")
        print(f"cost_bps={config.cost_bps}")
        print(f"require_offset_match={config.require_offset_match}")
        print()
        print_summary("--- overall ---", summarize(policy_rows))

        print()
        print("--- by checkpoint ---")
        for item in grouped_summary(policy_rows, "checkpoint_ratio"):
            print(
                f"checkpoint={item['checkpoint_ratio']} "
                f"trades={item['trades']} "
                f"avg={fmt(item['avg_return_pct'])}% "
                f"positive={fmt(item['positive_rate_pct'], 2)}% "
                f"best={fmt(item['best_return_pct'])}% "
                f"worst={fmt(item['worst_return_pct'])}%"
            )

        print()
        print("--- by symbol ---")
        for item in grouped_summary(policy_rows, "symbol"):
            print(
                f"symbol={item['symbol']} "
                f"trades={item['trades']} "
                f"avg={fmt(item['avg_return_pct'])}% "
                f"positive={fmt(item['positive_rate_pct'], 2)}%"
            )

        print()
        print("--- outputs ---")
        print(f"csv={csv_path}")
        print(f"jsonl={jsonl_path}")
        print(f"summary={summary_path}")

        print()
        print(
            f"[DONE] research_policy_rows={len(policy_rows)} "
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
