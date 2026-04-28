from __future__ import annotations

"""
Synth v2 - Swing Pullback V5 Paper Candidate Preview V1.

LAYER:
research / paper-candidate preview

BOUNDARY:
Allowed:
- read synth_bt replay/eval market research rows
- apply the canonical swing_pullback_recovery_v5 market-only policy
- emit deterministic candidate previews
- simulate candidate throttling using market-only timestamp/symbol rules

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions
- decision_gate writes
- execution_intent writes
- execution_plan writes

Purpose:
Provide a clean research-only wrapper around the promoted
swing_pullback_recovery_v5 candidate, without wiring it into account-aware
or execution layers.
"""

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v1"

POLICY_NAME = "swing_pullback_recovery_v5"
POLICY_VERSION = "paper_candidate_preview_v1"

TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class PreviewCandidate:
    replay_id: int
    asset_id: int
    symbol: str
    venue: str
    replay_asof_ts_utc: datetime
    selection_state: str
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    sleeve_fit_code: str | None
    net_return_24h: Decimal | None


@dataclass(frozen=True)
class AcceptedPreview:
    candidate_state: str
    policy_name: str
    policy_version: str
    replay_id: int
    asset_id: int
    symbol: str
    venue: str
    candidate_ts_utc: datetime
    selection_state: str
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    sleeve_fit_code: str | None
    suggested_hold_hours: int
    max_per_snapshot: int
    cooldown_hours_per_symbol: int
    simulated_net_return_24h: Decimal | None
    notes: str


@dataclass(frozen=True)
class RejectedPreview:
    policy_name: str
    replay_id: int
    symbol: str
    venue: str
    candidate_ts_utc: datetime
    reject_reason: str
    priority_rank: int | None
    selection_score: Decimal | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview canonical swing_pullback_recovery_v5 paper candidates."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--max-per-snapshot", type=int, default=2)
    parser.add_argument("--cooldown-hours", type=int, default=24)
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--limit-snapshots", type=int, default=None)
    parser.add_argument("--include-rejected", action="store_true")
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--output", choices=("table", "json", "jsonl"), default="table")
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_RE.fullmatch(table_name):
        raise ValueError(f"Unsafe eval table name: {table_name}")
    return table_name


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def fmt_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return str(value)
    return value


def fetch_policy_candidates(
    *,
    eval_table: str,
    from_ts: datetime,
    to_ts: datetime,
    venue: str,
) -> list[PreviewCandidate]:
    table_name = validate_table_name(eval_table)

    sql = f"""
    SELECT
        bt_selection_v2_replay_id,
        asset_id,
        symbol,
        venue,
        replay_asof_ts_utc,
        selection_state,
        selection_score,
        priority_rank,
        btc_prior_24h,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        net_return_24h
    FROM {table_name}
    WHERE replay_asof_ts_utc >= %s
      AND replay_asof_ts_utc < %s
      AND venue = %s
      AND net_return_24h IS NOT NULL
      AND selection_state = 'WATCHLIST'
      AND priority_rank BETWEEN 1 AND 10
      AND btc_prior_24h >= -0.030
      AND btc_prior_24h <= 0.000
      AND rotation_bucket = 'ROTATION_EARLY'
      AND classification_code = 'PULLBACK_WATCH'
      AND sleeve_fit_code = 'SWING_STRUCTURAL'
      AND NOT (
          selection_score >= 0.50000000
          AND selection_score < 0.52000000
          AND priority_rank BETWEEN 4 AND 6
      )
    ORDER BY
        replay_asof_ts_utc,
        priority_rank,
        selection_score DESC,
        symbol
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [from_ts, to_ts, venue])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[PreviewCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        out.append(
            PreviewCandidate(
                replay_id=int(row["bt_selection_v2_replay_id"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                replay_asof_ts_utc=row["replay_asof_ts_utc"],
                selection_state=str(row["selection_state"]),
                selection_score=to_decimal(row.get("selection_score")),
                priority_rank=None if row.get("priority_rank") is None else int(row["priority_rank"]),
                btc_prior_24h=to_decimal(row.get("btc_prior_24h")),
                rotation_bucket=row.get("rotation_bucket"),
                classification_code=row.get("classification_code"),
                sleeve_fit_code=row.get("sleeve_fit_code"),
                net_return_24h=to_decimal(row.get("net_return_24h")),
            )
        )

    return out


def apply_preview_throttle(
    *,
    candidates: list[PreviewCandidate],
    max_per_snapshot: int,
    cooldown_hours: int,
    hold_hours: int,
    limit_snapshots: int | None,
) -> tuple[list[AcceptedPreview], list[RejectedPreview]]:
    if max_per_snapshot < 1:
        raise ValueError("--max-per-snapshot must be >= 1")
    if cooldown_hours < 0:
        raise ValueError("--cooldown-hours must be >= 0")
    if hold_hours != 24:
        raise ValueError("Canonical v5 preview currently supports hold-hours=24 only")

    accepted: list[AcceptedPreview] = []
    rejected: list[RejectedPreview] = []
    last_symbol_accept_ts: dict[str, datetime] = {}

    snapshots_seen = 0
    current_snapshot: datetime | None = None
    accepted_in_snapshot = 0
    symbols_in_snapshot: set[str] = set()

    for row in candidates:
        if current_snapshot != row.replay_asof_ts_utc:
            current_snapshot = row.replay_asof_ts_utc
            accepted_in_snapshot = 0
            symbols_in_snapshot = set()
            snapshots_seen += 1

            if limit_snapshots is not None and snapshots_seen > limit_snapshots:
                break

        reject_reason: str | None = None

        if row.symbol in symbols_in_snapshot:
            reject_reason = "DUPLICATE_SYMBOL_IN_SNAPSHOT"

        last_ts = last_symbol_accept_ts.get(row.symbol)
        if reject_reason is None and last_ts is not None:
            next_allowed = last_ts + timedelta(hours=cooldown_hours)
            if row.replay_asof_ts_utc < next_allowed:
                reject_reason = "SYMBOL_COOLDOWN_ACTIVE"

        if reject_reason is None and accepted_in_snapshot >= max_per_snapshot:
            reject_reason = "MAX_PER_SNAPSHOT_REACHED"

        if reject_reason is not None:
            rejected.append(
                RejectedPreview(
                    policy_name=POLICY_NAME,
                    replay_id=row.replay_id,
                    symbol=row.symbol,
                    venue=row.venue,
                    candidate_ts_utc=row.replay_asof_ts_utc,
                    reject_reason=reject_reason,
                    priority_rank=row.priority_rank,
                    selection_score=row.selection_score,
                )
            )
            continue

        accepted_in_snapshot += 1
        symbols_in_snapshot.add(row.symbol)
        last_symbol_accept_ts[row.symbol] = row.replay_asof_ts_utc

        accepted.append(
            AcceptedPreview(
                candidate_state="RESEARCH_PAPER_CANDIDATE_PREVIEW",
                policy_name=POLICY_NAME,
                policy_version=POLICY_VERSION,
                replay_id=row.replay_id,
                asset_id=row.asset_id,
                symbol=row.symbol,
                venue=row.venue,
                candidate_ts_utc=row.replay_asof_ts_utc,
                selection_state=row.selection_state,
                selection_score=row.selection_score,
                priority_rank=row.priority_rank,
                btc_prior_24h=row.btc_prior_24h,
                rotation_bucket=row.rotation_bucket,
                classification_code=row.classification_code,
                sleeve_fit_code=row.sleeve_fit_code,
                suggested_hold_hours=hold_hours,
                max_per_snapshot=max_per_snapshot,
                cooldown_hours_per_symbol=cooldown_hours,
                simulated_net_return_24h=row.net_return_24h,
                notes=(
                    "Research-only paper candidate preview. "
                    "Not a decision, not an execution intent, not an order."
                ),
            )
        )

    return accepted, rejected


def summarize(
    accepted: list[AcceptedPreview],
    rejected: list[RejectedPreview],
) -> dict[str, Any]:
    returns = [
        row.simulated_net_return_24h
        for row in accepted
        if row.simulated_net_return_24h is not None
    ]
    symbols = sorted({row.symbol for row in accepted})
    active_days = sorted({row.candidate_ts_utc.date() for row in accepted})

    if returns:
        avg_return = sum(returns) / Decimal(len(returns))
        winrate = sum(1 for value in returns if value > 0) / len(returns)
        worst = min(returns)
        best = max(returns)
        total = sum(returns)
    else:
        avg_return = None
        winrate = None
        worst = None
        best = None
        total = None

    reject_counts: dict[str, int] = {}
    for row in rejected:
        reject_counts[row.reject_reason] = reject_counts.get(row.reject_reason, 0) + 1

    return {
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "accepted_candidates": len(accepted),
        "rejected_candidates": len(rejected),
        "symbols": len(symbols),
        "active_days": len(active_days),
        "first_ts": min((row.candidate_ts_utc for row in accepted), default=None),
        "last_ts": max((row.candidate_ts_utc for row in accepted), default=None),
        "avg_simulated_net_return_24h": avg_return,
        "winrate_24h": winrate,
        "worst_simulated_net_return_24h": worst,
        "best_simulated_net_return_24h": best,
        "sum_simulated_net_return_24h": total,
        "reject_counts": reject_counts,
    }


def print_table(
    *,
    accepted: list[AcceptedPreview],
    rejected: list[RejectedPreview],
    top: int,
) -> None:
    summary = summarize(accepted, rejected)

    print("Swing Pullback V5 paper-candidate preview")
    print(f"policy={POLICY_NAME}")
    print(f"policy_version={POLICY_VERSION}")

    print()
    print("=== SUMMARY ===")
    for key, value in summary.items():
        if key == "reject_counts":
            continue
        if isinstance(value, Decimal):
            value = fmt_decimal(value)
        elif isinstance(value, float):
            value = f"{value:.4f}"
        print(f"{key}: {value}")

    print()
    print("reject_counts:")
    if summary["reject_counts"]:
        for reason, count in sorted(summary["reject_counts"].items()):
            print(f"- {reason}: {count}")
    else:
        print("- none")

    print()
    print("=== ACCEPTED PREVIEW CANDIDATES ===")
    rows = accepted[:top]
    if not rows:
        print("(no rows)")
        return

    print("ts | symbol | rank | score | btc24 | net24 | state")
    print("-" * 86)

    for row in rows:
        print(
            " | ".join(
                [
                    row.candidate_ts_utc.strftime("%Y-%m-%d %H:%M"),
                    row.symbol,
                    "" if row.priority_rank is None else str(row.priority_rank),
                    fmt_decimal(row.selection_score),
                    fmt_decimal(row.btc_prior_24h),
                    fmt_decimal(row.simulated_net_return_24h),
                    row.candidate_state,
                ]
            )
        )

    if len(accepted) > top:
        print(f"... {len(accepted) - top} more accepted rows not shown")

    if rejected:
        print()
        print("=== REJECTED PREVIEW SAMPLE ===")
        for row in rejected[: min(top, 20)]:
            print(
                {
                    "ts": row.candidate_ts_utc.strftime("%Y-%m-%d %H:%M"),
                    "symbol": row.symbol,
                    "reason": row.reject_reason,
                    "rank": row.priority_rank,
                    "score": fmt_decimal(row.selection_score),
                }
            )


def main() -> int:
    args = parse_args()

    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)

    raw_candidates = fetch_policy_candidates(
        eval_table=args.eval_table,
        from_ts=from_ts,
        to_ts=to_ts,
        venue=args.venue,
    )

    accepted, rejected = apply_preview_throttle(
        candidates=raw_candidates,
        max_per_snapshot=args.max_per_snapshot,
        cooldown_hours=args.cooldown_hours,
        hold_hours=args.hold_hours,
        limit_snapshots=args.limit_snapshots,
    )

    if args.output == "json":
        payload = {
            "summary": summarize(accepted, rejected),
            "accepted": [asdict(row) for row in accepted[: args.top]],
            "rejected": [asdict(row) for row in rejected[: args.top]]
            if args.include_rejected
            else [],
        }
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
        return 0

    if args.output == "jsonl":
        for row in accepted:
            print(json.dumps(asdict(row), default=json_default, sort_keys=True))
        if args.include_rejected:
            for row in rejected:
                print(json.dumps(asdict(row), default=json_default, sort_keys=True))
        return 0

    print_table(
        accepted=accepted,
        rejected=rejected if args.include_rejected else [],
        top=args.top,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
