from __future__ import annotations

"""
Synth v2 - Parking Rotation Strategy Simulation V1.

LAYER:
research/backtest simulation

BOUNDARY:
Allowed:
- read synth_bt replay eval rows
- apply named market-only research policy
- simulate deterministic trade lifecycle with fixed holding horizon
- report strategy-level performance statistics
- optionally persist simulation run + trades into synth_bt

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions

Purpose:
Turn parking_rotation_recovery_v1 from a policy screen into a simple
research-only strategy simulation with explicit entry/exit horizon.
"""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v1"
DEFAULT_POLICY = "parking_rotation_recovery_v1"

SIM_RUN_TABLE = "bt_strategy_sim_run_v1"
SIM_TRADE_TABLE = "bt_strategy_sim_trade_v1"

WEAK_SYMBOLS = ("HNT", "SOL", "XLM", "LTC", "ETH", "XRP", "CC", "NOT")
WEAK_SYMBOLS_SQL = ",".join(f"'{symbol}'" for symbol in WEAK_SYMBOLS)


@dataclass(frozen=True)
class NamedPolicy:
    policy_name: str
    rank_min: int
    rank_max: int
    btc_prior_min: Decimal
    btc_prior_max: Decimal
    max_selection_score_exclusive: Decimal
    exclude_weak_symbols: bool
    rotation_bucket: str
    classification_code: str
    sleeve_fit_code: str


@dataclass(frozen=True)
class CandidateRow:
    source_row_key: str
    replay_asof_ts_utc: datetime
    symbol: str
    asset_id: int
    selection_state: str
    selection_bias: str | None
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    sleeve_fit_code: str | None
    net_return_4h: Decimal | None
    net_return_24h: Decimal | None
    gross_return_4h: Decimal | None
    gross_return_24h: Decimal | None


@dataclass(frozen=True)
class SimTrade:
    sim_run_id: int | None
    source_row_key: str
    symbol: str
    asset_id: int
    entry_ts_utc: datetime
    exit_ts_utc: datetime
    hold_hours: int
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    net_return: Decimal
    gross_return: Decimal | None


POLICIES: dict[str, NamedPolicy] = {
    "parking_rotation_recovery_v1": NamedPolicy(
        policy_name="parking_rotation_recovery_v1",
        rank_min=4,
        rank_max=10,
        btc_prior_min=Decimal("-0.010"),
        btc_prior_max=Decimal("0.010"),
        max_selection_score_exclusive=Decimal("0.50000000"),
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EXIT",
        classification_code="NO_TRADE",
        sleeve_fit_code="EXPERIMENTAL",
    ),
    "parking_rotation_recovery_v2": NamedPolicy(
        policy_name="parking_rotation_recovery_v2",
        rank_min=6,
        rank_max=15,
        btc_prior_min=Decimal("-0.005"),
        btc_prior_max=Decimal("0.015"),
        max_selection_score_exclusive=Decimal("0.50000000"),
        exclude_weak_symbols=True,
        rotation_bucket="ROTATION_EXIT",
        classification_code="NO_TRADE",
        sleeve_fit_code="EXPERIMENTAL",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run research-only parking rotation strategy simulation."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--hold-hours", type=int, default=24, choices=(4, 24))
    parser.add_argument("--max-trades-per-snapshot", type=int, default=1)
    parser.add_argument("--cooldown-hours-per-symbol", type=int, default=24)
    parser.add_argument("--dedupe-symbol-overlap", action="store_true")
    parser.add_argument("--sim-name", default="parking_rotation_strategy_sim_v1")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--show-trades", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _validate_table_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"Unsafe table name: {value}")
    return value


def _resolve_policy(policy_name: str) -> NamedPolicy:
    if policy_name not in POLICIES:
        allowed = ", ".join(sorted(POLICIES))
        raise ValueError(f"Unsupported policy: {policy_name}. Allowed: {allowed}")
    return POLICIES[policy_name]


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _fmt_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"=== {title} ===")

    if not rows:
        print("(no rows)")
        return

    headers = list(rows[0].keys())
    printable = [[str(row.get(header, "")) for header in headers] for row in rows]

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))

    for row in printable:
        print(fmt(row))


def _policy_where(policy: NamedPolicy) -> str:
    weak_filter_sql = ""
    if policy.exclude_weak_symbols:
        weak_filter_sql = f"AND symbol NOT IN ({WEAK_SYMBOLS_SQL})"

    return f"""
        selection_state = 'WATCHLIST'
        AND priority_rank BETWEEN {policy.rank_min} AND {policy.rank_max}
        AND btc_prior_24h >= {policy.btc_prior_min}
        AND btc_prior_24h <= {policy.btc_prior_max}
        AND selection_score < {policy.max_selection_score_exclusive}
        {weak_filter_sql}
        AND rotation_bucket = '{policy.rotation_bucket}'
        AND classification_code = '{policy.classification_code}'
        AND sleeve_fit_code = '{policy.sleeve_fit_code}'
    """


def _source_row_key(
    *,
    policy_name: str,
    hold_hours: int,
    replay_asof_ts_utc: datetime,
    asset_id: int,
    symbol: str,
) -> str:
    raw = (
        f"{policy_name}|{hold_hours}|"
        f"{replay_asof_ts_utc.isoformat(sep=' ')}|"
        f"{asset_id}|{symbol}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fetch_candidates(
    *,
    eval_table: str,
    policy: NamedPolicy,
    from_ts: str,
    to_ts: str,
    hold_hours: int,
) -> list[CandidateRow]:
    safe_eval_table = _validate_table_name(eval_table)
    where_sql = _policy_where(policy)

    if hold_hours == 4:
        net_col = "net_return_4h"
    elif hold_hours == 24:
        net_col = "net_return_24h"
    else:
        raise ValueError(f"Unsupported hold_hours: {hold_hours}")

    sql = f"""
    SELECT
        replay_asof_ts_utc,
        symbol,
        asset_id,
        selection_state,
        selection_bias,
        selection_score,
        priority_rank,
        btc_prior_24h,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        net_return_4h,
        net_return_24h,
        gross_return_4h,
        gross_return_24h
    FROM {safe_eval_table}
    WHERE {where_sql}
      AND replay_asof_ts_utc >= %s
      AND replay_asof_ts_utc < %s
      AND {net_col} IS NOT NULL
    ORDER BY
        replay_asof_ts_utc ASC,
        selection_score ASC,
        priority_rank ASC,
        symbol ASC
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [from_ts, to_ts])
            rows = cur.fetchall() or []
            if not all(isinstance(row, dict) for row in rows):
                raise TypeError("Expected dict rows from database cursor")
    finally:
        conn.close()

    out: list[CandidateRow] = []
    for row in rows:
        replay_asof_ts_utc = row["replay_asof_ts_utc"]
        asset_id = int(row["asset_id"])
        symbol = str(row["symbol"])

        out.append(
            CandidateRow(
                source_row_key=_source_row_key(
                    policy_name=policy.policy_name,
                    hold_hours=hold_hours,
                    replay_asof_ts_utc=replay_asof_ts_utc,
                    asset_id=asset_id,
                    symbol=symbol,
                ),
                replay_asof_ts_utc=replay_asof_ts_utc,
                symbol=symbol,
                asset_id=asset_id,
                selection_state=str(row["selection_state"]),
                selection_bias=row["selection_bias"],
                selection_score=_to_decimal(row["selection_score"]),
                priority_rank=None if row["priority_rank"] is None else int(row["priority_rank"]),
                btc_prior_24h=_to_decimal(row["btc_prior_24h"]),
                rotation_bucket=row["rotation_bucket"],
                classification_code=row["classification_code"],
                sleeve_fit_code=row["sleeve_fit_code"],
                net_return_4h=_to_decimal(row["net_return_4h"]),
                net_return_24h=_to_decimal(row["net_return_24h"]),
                gross_return_4h=_to_decimal(row["gross_return_4h"]),
                gross_return_24h=_to_decimal(row["gross_return_24h"]),
            )
        )

    return out


def simulate_trades(
    candidates: list[CandidateRow],
    *,
    hold_hours: int,
    max_trades_per_snapshot: int,
    cooldown_hours_per_symbol: int,
    dedupe_symbol_overlap: bool,
) -> list[SimTrade]:
    by_snapshot: dict[datetime, list[CandidateRow]] = defaultdict(list)
    for candidate in candidates:
        by_snapshot[candidate.replay_asof_ts_utc].append(candidate)

    next_allowed_by_symbol: dict[str, datetime] = {}
    open_until_by_symbol: dict[str, datetime] = {}
    trades: list[SimTrade] = []

    for snapshot_ts in sorted(by_snapshot):
        selected_for_snapshot = 0

        ranked_rows = sorted(
            by_snapshot[snapshot_ts],
            key=lambda row: (
                row.selection_score if row.selection_score is not None else Decimal("999"),
                row.priority_rank if row.priority_rank is not None else 999999,
                row.symbol,
            ),
        )

        for candidate in ranked_rows:
            if selected_for_snapshot >= max_trades_per_snapshot:
                continue

            next_allowed = next_allowed_by_symbol.get(candidate.symbol)
            if next_allowed is not None and snapshot_ts < next_allowed:
                continue

            open_until = open_until_by_symbol.get(candidate.symbol)
            if dedupe_symbol_overlap and open_until is not None and snapshot_ts < open_until:
                continue

            if hold_hours == 4:
                net_return = candidate.net_return_4h
                gross_return = candidate.gross_return_4h
            elif hold_hours == 24:
                net_return = candidate.net_return_24h
                gross_return = candidate.gross_return_24h
            else:
                raise ValueError(f"Unsupported hold_hours: {hold_hours}")

            if net_return is None:
                continue

            exit_ts = snapshot_ts + timedelta(hours=hold_hours)
            cooldown_until = snapshot_ts + timedelta(hours=cooldown_hours_per_symbol)

            next_allowed_by_symbol[candidate.symbol] = cooldown_until
            open_until_by_symbol[candidate.symbol] = exit_ts
            selected_for_snapshot += 1

            trades.append(
                SimTrade(
                    sim_run_id=None,
                    source_row_key=candidate.source_row_key,
                    symbol=candidate.symbol,
                    asset_id=candidate.asset_id,
                    entry_ts_utc=snapshot_ts,
                    exit_ts_utc=exit_ts,
                    hold_hours=hold_hours,
                    selection_score=candidate.selection_score,
                    priority_rank=candidate.priority_rank,
                    btc_prior_24h=candidate.btc_prior_24h,
                    net_return=net_return,
                    gross_return=gross_return,
                )
            )

    return trades


def summarize_trades(trades: list[SimTrade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "symbols": 0,
            "days": 0,
            "avg_net_return": None,
            "avg_gross_return": None,
            "winrate": None,
            "worst_net_return": None,
            "best_net_return": None,
            "sum_net_return_equal_weight": Decimal("0"),
            "compound_net_return_trade_sequence": Decimal("0"),
        }

    net_returns = [trade.net_return for trade in trades]
    gross_returns = [trade.gross_return for trade in trades if trade.gross_return is not None]

    sum_net = sum(net_returns, Decimal("0"))
    avg_net = sum_net / Decimal(str(len(net_returns)))

    avg_gross = None
    if gross_returns:
        avg_gross = sum(gross_returns, Decimal("0")) / Decimal(str(len(gross_returns)))

    wins = sum(1 for value in net_returns if value > 0)
    winrate = Decimal(str(wins)) / Decimal(str(len(net_returns)))

    compound = Decimal("1")
    for value in net_returns:
        compound *= Decimal("1") + value
    compound -= Decimal("1")

    return {
        "trades": len(trades),
        "symbols": len({trade.symbol for trade in trades}),
        "days": len({trade.entry_ts_utc.date() for trade in trades}),
        "avg_net_return": avg_net,
        "avg_gross_return": avg_gross,
        "winrate": winrate,
        "worst_net_return": min(net_returns),
        "best_net_return": max(net_returns),
        "sum_net_return_equal_weight": sum_net,
        "compound_net_return_trade_sequence": compound,
    }


def summarize_by_symbol(trades: list[SimTrade]) -> list[dict[str, Any]]:
    grouped: dict[str, list[SimTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol].append(trade)

    rows: list[dict[str, Any]] = []
    for symbol, symbol_trades in sorted(grouped.items()):
        stats = summarize_trades(symbol_trades)
        rows.append(
            {
                "symbol": symbol,
                "trades": stats["trades"],
                "avg_net_raw": stats["avg_net_return"],
                "avg_net": _fmt_decimal(stats["avg_net_return"]),
                "winrate": _fmt_decimal(stats["winrate"], 4),
                "worst": _fmt_decimal(stats["worst_net_return"]),
                "best": _fmt_decimal(stats["best_net_return"]),
            }
        )

    sorted_rows = sorted(
        rows,
        key=lambda row: row["avg_net_raw"] if row["avg_net_raw"] is not None else Decimal("-999"),
        reverse=True,
    )

    for row in sorted_rows:
        row.pop("avg_net_raw", None)

    return sorted_rows


def summarize_by_day(trades: list[SimTrade]) -> list[dict[str, Any]]:
    grouped: dict[str, list[SimTrade]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.entry_ts_utc.date())].append(trade)

    rows: list[dict[str, Any]] = []
    for day, day_trades in sorted(grouped.items()):
        stats = summarize_trades(day_trades)
        rows.append(
            {
                "day": day,
                "trades": stats["trades"],
                "avg_net": _fmt_decimal(stats["avg_net_return"]),
                "winrate": _fmt_decimal(stats["winrate"], 4),
                "worst": _fmt_decimal(stats["worst_net_return"]),
                "best": _fmt_decimal(stats["best_net_return"]),
            }
        )

    return rows


def ensure_sim_tables() -> None:
    sql_statements = [
        f"""
        CREATE TABLE IF NOT EXISTS {SIM_RUN_TABLE} (
            strategy_sim_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            sim_name VARCHAR(128) NOT NULL,
            policy_name VARCHAR(128) NOT NULL,
            eval_table VARCHAR(128) NOT NULL,
            from_ts_utc DATETIME(6) NOT NULL,
            to_ts_utc DATETIME(6) NOT NULL,
            hold_hours INT NOT NULL,
            max_trades_per_snapshot INT NOT NULL,
            cooldown_hours_per_symbol INT NOT NULL,
            dedupe_symbol_overlap TINYINT(1) NOT NULL,
            candidate_rows INT NOT NULL,
            trades_total INT NOT NULL,
            symbol_count INT NOT NULL,
            day_count INT NOT NULL,
            avg_net_return DECIMAL(38,18) DEFAULT NULL,
            avg_gross_return DECIMAL(38,18) DEFAULT NULL,
            winrate DECIMAL(18,8) DEFAULT NULL,
            worst_net_return DECIMAL(38,18) DEFAULT NULL,
            best_net_return DECIMAL(38,18) DEFAULT NULL,
            sum_net_return_equal_weight DECIMAL(38,18) DEFAULT NULL,
            compound_net_return_trade_sequence DECIMAL(38,18) DEFAULT NULL,
            created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            PRIMARY KEY (strategy_sim_run_id),
            KEY ix_strategy_sim_run_name_created (sim_name, created_ts_utc),
            KEY ix_strategy_sim_run_policy_window (policy_name, from_ts_utc, to_ts_utc)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {SIM_TRADE_TABLE} (
            strategy_sim_trade_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            strategy_sim_run_id BIGINT UNSIGNED NOT NULL,
            source_row_key CHAR(64) NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            asset_id INT NOT NULL,
            entry_ts_utc DATETIME(6) NOT NULL,
            exit_ts_utc DATETIME(6) NOT NULL,
            hold_hours INT NOT NULL,
            selection_score DECIMAL(18,8) DEFAULT NULL,
            priority_rank INT DEFAULT NULL,
            btc_prior_24h DECIMAL(18,8) DEFAULT NULL,
            net_return DECIMAL(38,18) NOT NULL,
            gross_return DECIMAL(38,18) DEFAULT NULL,
            created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            PRIMARY KEY (strategy_sim_trade_id),
            UNIQUE KEY uq_strategy_sim_trade_source (
                strategy_sim_run_id,
                source_row_key
            ),
            KEY ix_strategy_sim_trade_run (strategy_sim_run_id),
            KEY ix_strategy_sim_trade_symbol_entry (symbol, entry_ts_utc),
            KEY ix_strategy_sim_trade_entry (entry_ts_utc),
            CONSTRAINT fk_strategy_sim_trade_run_v1
                FOREIGN KEY (strategy_sim_run_id)
                REFERENCES {SIM_RUN_TABLE} (strategy_sim_run_id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ]

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            for sql in sql_statements:
                cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def persist_simulation(
    *,
    sim_name: str,
    policy_name: str,
    eval_table: str,
    from_ts: str,
    to_ts: str,
    hold_hours: int,
    max_trades_per_snapshot: int,
    cooldown_hours_per_symbol: int,
    dedupe_symbol_overlap: bool,
    candidate_rows: int,
    trades: list[SimTrade],
    summary: dict[str, Any],
) -> int:
    ensure_sim_tables()

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SIM_RUN_TABLE} (
                    sim_name,
                    policy_name,
                    eval_table,
                    from_ts_utc,
                    to_ts_utc,
                    hold_hours,
                    max_trades_per_snapshot,
                    cooldown_hours_per_symbol,
                    dedupe_symbol_overlap,
                    candidate_rows,
                    trades_total,
                    symbol_count,
                    day_count,
                    avg_net_return,
                    avg_gross_return,
                    winrate,
                    worst_net_return,
                    best_net_return,
                    sum_net_return_equal_weight,
                    compound_net_return_trade_sequence
                ) VALUES (
                    %(sim_name)s,
                    %(policy_name)s,
                    %(eval_table)s,
                    %(from_ts_utc)s,
                    %(to_ts_utc)s,
                    %(hold_hours)s,
                    %(max_trades_per_snapshot)s,
                    %(cooldown_hours_per_symbol)s,
                    %(dedupe_symbol_overlap)s,
                    %(candidate_rows)s,
                    %(trades_total)s,
                    %(symbol_count)s,
                    %(day_count)s,
                    %(avg_net_return)s,
                    %(avg_gross_return)s,
                    %(winrate)s,
                    %(worst_net_return)s,
                    %(best_net_return)s,
                    %(sum_net_return_equal_weight)s,
                    %(compound_net_return_trade_sequence)s
                )
                """,
                {
                    "sim_name": sim_name,
                    "policy_name": policy_name,
                    "eval_table": eval_table,
                    "from_ts_utc": from_ts,
                    "to_ts_utc": to_ts,
                    "hold_hours": hold_hours,
                    "max_trades_per_snapshot": max_trades_per_snapshot,
                    "cooldown_hours_per_symbol": cooldown_hours_per_symbol,
                    "dedupe_symbol_overlap": int(dedupe_symbol_overlap),
                    "candidate_rows": candidate_rows,
                    "trades_total": summary["trades"],
                    "symbol_count": summary["symbols"],
                    "day_count": summary["days"],
                    "avg_net_return": summary["avg_net_return"],
                    "avg_gross_return": summary["avg_gross_return"],
                    "winrate": summary["winrate"],
                    "worst_net_return": summary["worst_net_return"],
                    "best_net_return": summary["best_net_return"],
                    "sum_net_return_equal_weight": summary["sum_net_return_equal_weight"],
                    "compound_net_return_trade_sequence": summary[
                        "compound_net_return_trade_sequence"
                    ],
                },
            )
            sim_run_id = int(cur.lastrowid)

            trade_rows = [
                {
                    "strategy_sim_run_id": sim_run_id,
                    "source_row_key": trade.source_row_key,
                    "symbol": trade.symbol,
                    "asset_id": trade.asset_id,
                    "entry_ts_utc": trade.entry_ts_utc,
                    "exit_ts_utc": trade.exit_ts_utc,
                    "hold_hours": trade.hold_hours,
                    "selection_score": trade.selection_score,
                    "priority_rank": trade.priority_rank,
                    "btc_prior_24h": trade.btc_prior_24h,
                    "net_return": trade.net_return,
                    "gross_return": trade.gross_return,
                }
                for trade in trades
            ]

            if trade_rows:
                cur.executemany(
                    f"""
                    INSERT INTO {SIM_TRADE_TABLE} (
                        strategy_sim_run_id,
                        source_row_key,
                        symbol,
                        asset_id,
                        entry_ts_utc,
                        exit_ts_utc,
                        hold_hours,
                        selection_score,
                        priority_rank,
                        btc_prior_24h,
                        net_return,
                        gross_return
                    ) VALUES (
                        %(strategy_sim_run_id)s,
                        %(source_row_key)s,
                        %(symbol)s,
                        %(asset_id)s,
                        %(entry_ts_utc)s,
                        %(exit_ts_utc)s,
                        %(hold_hours)s,
                        %(selection_score)s,
                        %(priority_rank)s,
                        %(btc_prior_24h)s,
                        %(net_return)s,
                        %(gross_return)s
                    )
                    """,
                    trade_rows,
                )

        conn.commit()
        return sim_run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def build_summary_row(
    *,
    sim_run_id: int | None,
    sim_name: str,
    policy_name: str,
    from_ts: str,
    to_ts: str,
    hold_hours: int,
    candidate_rows: int,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sim_run_id": "" if sim_run_id is None else sim_run_id,
        "sim_name": sim_name,
        "policy": policy_name,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "hold_hours": hold_hours,
        "candidate_rows": candidate_rows,
        "trades": summary["trades"],
        "symbols": summary["symbols"],
        "days": summary["days"],
        "avg_net": _fmt_decimal(summary["avg_net_return"]),
        "winrate": _fmt_decimal(summary["winrate"], 4),
        "worst": _fmt_decimal(summary["worst_net_return"]),
        "best": _fmt_decimal(summary["best_net_return"]),
        "sum_net_eq": _fmt_decimal(summary["sum_net_return_equal_weight"]),
        "compound_trade_seq": _fmt_decimal(
            summary["compound_net_return_trade_sequence"]
        ),
    }


def main() -> int:
    args = parse_args()

    eval_table = _validate_table_name(str(args.eval_table))
    policy = _resolve_policy(str(args.policy))
    from_ts = str(args.from_ts)
    to_ts = str(args.to_ts)
    hold_hours = int(args.hold_hours)

    candidates = fetch_candidates(
        eval_table=eval_table,
        policy=policy,
        from_ts=from_ts,
        to_ts=to_ts,
        hold_hours=hold_hours,
    )

    trades = simulate_trades(
        candidates,
        hold_hours=hold_hours,
        max_trades_per_snapshot=int(args.max_trades_per_snapshot),
        cooldown_hours_per_symbol=int(args.cooldown_hours_per_symbol),
        dedupe_symbol_overlap=bool(args.dedupe_symbol_overlap),
    )

    summary = summarize_trades(trades)

    sim_run_id: int | None = None
    if args.write_db:
        sim_run_id = persist_simulation(
            sim_name=str(args.sim_name),
            policy_name=policy.policy_name,
            eval_table=eval_table,
            from_ts=from_ts,
            to_ts=to_ts,
            hold_hours=hold_hours,
            max_trades_per_snapshot=int(args.max_trades_per_snapshot),
            cooldown_hours_per_symbol=int(args.cooldown_hours_per_symbol),
            dedupe_symbol_overlap=bool(args.dedupe_symbol_overlap),
            candidate_rows=len(candidates),
            trades=trades,
            summary=summary,
        )

    summary_row = build_summary_row(
        sim_run_id=sim_run_id,
        sim_name=str(args.sim_name),
        policy_name=policy.policy_name,
        from_ts=from_ts,
        to_ts=to_ts,
        hold_hours=hold_hours,
        candidate_rows=len(candidates),
        summary=summary,
    )

    by_day = summarize_by_day(trades)
    by_symbol = summarize_by_symbol(trades)

    trade_rows = [
        {
            "entry_ts_utc": trade.entry_ts_utc,
            "exit_ts_utc": trade.exit_ts_utc,
            "symbol": trade.symbol,
            "rank": trade.priority_rank,
            "score": _fmt_decimal(trade.selection_score),
            "btc_prior_24h": _fmt_decimal(trade.btc_prior_24h),
            "net_return": _fmt_decimal(trade.net_return),
            "gross_return": _fmt_decimal(trade.gross_return),
        }
        for trade in trades
    ]

    payload = {
        "summary": summary_row,
        "by_day": by_day,
        "by_symbol": by_symbol,
        "trades": trade_rows,
    }

    if args.output == "json":
        if not args.show_trades:
            payload = {k: v for k, v in payload.items() if k != "trades"}
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    _print_table("SIM SUMMARY", [summary_row])
    _print_table("BY DAY", by_day)
    _print_table("BY SYMBOL", by_symbol)

    if args.show_trades:
        _print_table("TRADES", trade_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
