from __future__ import annotations

"""
ENGINE: run_fib_exit_ladder_scoreboard_v1
MODE: research scoreboard / export

PURPOSE:
- Batch-run fib exit ladder backtests across:
  - symbols
  - target families
  - max ladder sell fractions
- Export all results to CSV/JSON.
- Select best candidate exit archetype per asset.

BOUNDARY:
- Read-only.
- Account-agnostic.
- No DB writes.
- No decision writes.
- No execution writes.
- No order/account/position writes.

ARCHITECTURE:
research fib/target maps
-> asset exit profile candidate
-> later decision_gate checks real position and permission
-> later execution_planner creates passive limit sell ladder
-> executor only places/monitors orders
"""

import argparse
import csv
import inspect
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

import pymysql

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt


DEFAULT_SYMBOLS = "LINK,SOL,XRP,HOT,XLM"
DEFAULT_TARGET_FAMILIES = "PRO_3X4X,SUPERCYCLE,EXPLOSIVE_SUPERCYCLE"
DEFAULT_MAX_SELL_FRACTIONS = "0.40,0.50,0.60,0.70,0.80"


class ScoreboardError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch scoreboard for fib exit ladder research.")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--from-ts", default="2020-01-01 00:00:00")
    parser.add_argument("--to-ts", default="2022-01-01 00:00:00")
    parser.add_argument("--target-families", default=DEFAULT_TARGET_FAMILIES)
    parser.add_argument("--max-sell-fractions", default=DEFAULT_MAX_SELL_FRACTIONS)

    parser.add_argument("--pivot-threshold-pct", default="0.25")
    parser.add_argument("--min-wave1-gain-pct", default="1.00")
    parser.add_argument("--min-wave1-days", type=int, default=14)
    parser.add_argument("--min-wave2-days-after-high", type=int, default=3)
    parser.add_argument("--wave2-min-retrace", default="0.236")
    parser.add_argument("--wave2-max-retrace", default="0.886")
    parser.add_argument("--target-zone-low-pct", default="0.04")
    parser.add_argument("--target-zone-high-pct", default="0.04")
    parser.add_argument("--front-run-pct", default="0.08")
    parser.add_argument("--end-pct-of-zone-high", default="0.98")
    parser.add_argument("--rungs-per-target", type=int, default=5)
    parser.add_argument("--distribution", choices=("front_loaded", "equal"), default="front_loaded")

    parser.add_argument(
        "--rank-metric",
        choices=("total_return", "alpha_vs_hold", "top_capture"),
        default="total_return",
    )
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--env-file", default=None)
    return parser.parse_args()


def load_env(env_file: Optional[str]) -> None:
    if load_dotenv is None:
        return

    if env_file:
        load_dotenv(dotenv_path=env_file)
        return

    default_env = Path.cwd() / ".env"
    if default_env.exists():
        load_dotenv(dotenv_path=default_env)


def env_first(names: tuple[str, ...], default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def connect_read_only() -> pymysql.connections.Connection:
    host = env_first(("SYNTH_DB_HOST", "DB_HOST", "MYSQL_HOST", "MARIADB_HOST"), "127.0.0.1")
    port = int(env_first(("SYNTH_DB_PORT", "DB_PORT", "MYSQL_PORT", "MARIADB_PORT"), "3306") or "3306")
    user = env_first(("SYNTH_DB_USER", "DB_USER", "MYSQL_USER", "MARIADB_USER"), "root")
    password = env_first(("SYNTH_DB_PASSWORD", "DB_PASSWORD", "MYSQL_PASSWORD", "MARIADB_PASSWORD"), "")
    database = env_first(("SYNTH_DB_NAME", "DB_NAME", "MYSQL_DATABASE", "MARIADB_DATABASE"), "synth")

    conn = pymysql.connect(
        host=str(host),
        port=port,
        user=str(user),
        password=str(password or ""),
        database=str(database),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )

    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("START TRANSACTION READ ONLY")

    return conn


def parse_csv_list(text: str) -> list[str]:
    values = [part.strip() for part in text.split(",") if part.strip()]
    if not values:
        raise ValueError("CSV list must not be empty.")
    return values


def parse_symbol_list(text: str) -> list[str]:
    return [value.upper() for value in parse_csv_list(text)]


def parse_decimal_list(text: str) -> list[Decimal]:
    return [Decimal(value) for value in parse_csv_list(text)]


def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.strip().replace("T", " ").replace("Z", ""))


def as_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def dec_text(value: Any, places: str = "0.000000") -> str:
    decimal_value = as_decimal(value)
    if decimal_value is None:
        return ""
    return format(decimal_value.quantize(Decimal(places)), "f")


def dt_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def call_with_known_kwargs(fn: Callable[..., Any], values: dict[str, Any]) -> Any:
    signature = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    missing: list[str] = []

    for name, parameter in signature.parameters.items():
        if name in values:
            kwargs[name] = values[name]
            continue

        if parameter.default is inspect.Parameter.empty:
            missing.append(name)

    if missing:
        raise ScoreboardError(
            f"Cannot call {fn.__name__}; missing required args: {missing}; "
            f"signature={signature}"
        )

    return fn(**kwargs)


def fetch_asset_id(conn: pymysql.connections.Connection, symbol: str) -> Optional[int]:
    return call_with_known_kwargs(
        ladder_bt.fetch_asset_id,
        {
            "conn": conn,
            "symbol": symbol,
        },
    )


def fetch_candles(
    conn: pymysql.connections.Connection,
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[Any]:
    return call_with_known_kwargs(
        ladder_bt.fetch_candles,
        {
            "conn": conn,
            "asset_id": asset_id,
            "symbol": symbol,
            "venue": venue,
            "interval": interval_code,
            "interval_code": interval_code,
            "from_ts": from_ts,
            "to_ts": to_ts,
        },
    )


def evaluate_symbol(
    *,
    symbol: str,
    asset_id: int,
    candles: list[Any],
    target_family: str,
    max_ladder_sell_fraction: Decimal,
    args: argparse.Namespace,
) -> Any:
    values = {
        "symbol": symbol,
        "asset_id": asset_id,
        "candles": candles,
        "target_family": target_family,
        "max_ladder_sell_fraction": max_ladder_sell_fraction,
        "pivot_threshold_pct": Decimal(str(args.pivot_threshold_pct)),
        "min_wave1_gain_pct": Decimal(str(args.min_wave1_gain_pct)),
        "min_wave1_days": int(args.min_wave1_days),
        "min_wave2_days_after_high": int(args.min_wave2_days_after_high),
        "wave2_min_retrace": Decimal(str(args.wave2_min_retrace)),
        "wave2_max_retrace": Decimal(str(args.wave2_max_retrace)),
        "target_zone_low_pct": Decimal(str(args.target_zone_low_pct)),
        "target_zone_high_pct": Decimal(str(args.target_zone_high_pct)),
        "front_run_pct": Decimal(str(args.front_run_pct)),
        "end_pct_of_zone_high": Decimal(str(args.end_pct_of_zone_high)),
        "rungs_per_target": int(args.rungs_per_target),
        "distribution": args.distribution,
    }

    return call_with_known_kwargs(ladder_bt.evaluate_symbol, values)


def sum_fill_fraction(result: Any) -> Optional[Decimal]:
    fills = getattr(result, "fills", None)
    if fills is None:
        return None

    total = Decimal("0")
    for fill in fills:
        fraction = getattr(fill, "sell_fraction", None)
        if fraction is not None:
            total += as_decimal(fraction) or Decimal("0")
    return total


def result_to_row(
    *,
    result: Any,
    target_family: str,
    max_ladder_sell_fraction: Decimal,
    rank_metric: str,
) -> dict[str, Any]:
    total_return = as_decimal(getattr(result, "total_return_pct_with_remaining", None))
    hold_return = as_decimal(getattr(result, "hold_return_pct", None))
    peak_return = as_decimal(getattr(result, "peak_oracle_return_pct", None))

    alpha_vs_hold = None
    if total_return is not None and hold_return is not None:
        alpha_vs_hold = total_return - hold_return

    top_capture = None
    if total_return is not None and peak_return not in (None, Decimal("0")):
        top_capture = total_return / peak_return

    sold_fraction = as_decimal(getattr(result, "sold_fraction", None))
    if sold_fraction is None:
        sold_fraction = sum_fill_fraction(result)

    remaining_fraction = as_decimal(getattr(result, "remaining_fraction", None))
    if remaining_fraction is None and sold_fraction is not None:
        remaining_fraction = Decimal("1") - sold_fraction

    if rank_metric == "alpha_vs_hold":
        rank_value = alpha_vs_hold
    elif rank_metric == "top_capture":
        rank_value = top_capture
    else:
        rank_value = total_return

    fills = getattr(result, "fills", None) or []

    row = {
        "symbol": getattr(result, "symbol", ""),
        "status": getattr(result, "status", ""),
        "target_family": target_family,
        "exit_archetype": exit_archetype_for_family(target_family),
        "max_ladder_sell_fraction": max_ladder_sell_fraction,
        "sold_fraction": sold_fraction,
        "remaining_fraction": remaining_fraction,
        "filled_rung_count": len(fills),
        "rank_metric": rank_metric,
        "rank_value": rank_value,
        "alpha_vs_hold_pct": alpha_vs_hold,
        "top_capture_ratio": top_capture,
        "anchor_low_ts": getattr(result, "anchor_low_ts", None),
        "anchor_low_price": getattr(result, "anchor_low_price", None),
        "wave1_high_ts": getattr(result, "wave1_high_ts", None),
        "wave1_high_price": getattr(result, "wave1_high_price", None),
        "wave2_low_ts": getattr(result, "wave2_low_ts", None),
        "wave2_low_price": getattr(result, "wave2_low_price", None),
        "entry_ts": getattr(result, "entry_ts", None),
        "entry_price": getattr(result, "entry_price", None),
        "realized_return_pct_on_full_position": getattr(result, "realized_return_pct_on_full_position", None),
        "remaining_return_pct_on_full_position": getattr(result, "remaining_return_pct_on_full_position", None),
        "total_return_pct_with_remaining": total_return,
        "hold_return_pct": hold_return,
        "peak_oracle_return_pct": peak_return,
    }
    return row


def exit_archetype_for_family(target_family: str) -> str:
    mapping = {
        "PRO_3X4X": "EXIT_PROFILE_CONTROLLED_3X4X",
        "SUPERCYCLE": "EXIT_PROFILE_SUPERCYCLE_BALANCED",
        "EXPLOSIVE_SUPERCYCLE": "EXIT_PROFILE_EXPLOSIVE_MOONBAG",
        "FIB_STANDARD": "EXIT_PROFILE_STANDARD_FIB",
    }
    return mapping.get(target_family, "EXIT_PROFILE_UNKNOWN")


def row_is_valid(row: dict[str, Any]) -> bool:
    return str(row.get("status")) == "OK" and row.get("rank_value") is not None


def select_best_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)

    best_rows: list[dict[str, Any]] = []
    for symbol, symbol_rows in sorted(by_symbol.items(), key=lambda item: item[0]):
        valid = [row for row in symbol_rows if row_is_valid(row)]
        if valid:
            best = max(valid, key=lambda row: as_decimal(row["rank_value"]) or Decimal("-999999999"))
        else:
            best = symbol_rows[0]
        best_row = dict(best)
        best_row["is_best_for_symbol"] = True
        best_rows.append(best_row)

    return best_rows


def printable_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "symbol": str(row.get("symbol", "")),
        "status": str(row.get("status", "")),
        "target_family": str(row.get("target_family", "")),
        "exit_archetype": str(row.get("exit_archetype", "")),
        "max_ladder_sell_fraction": dec_text(row.get("max_ladder_sell_fraction"), "0.0000"),
        "sold_fraction": dec_text(row.get("sold_fraction"), "0.0000"),
        "remaining_fraction": dec_text(row.get("remaining_fraction"), "0.0000"),
        "filled_rung_count": str(row.get("filled_rung_count", "")),
        "rank_metric": str(row.get("rank_metric", "")),
        "rank_value": dec_text(row.get("rank_value"), "0.000000"),
        "alpha_vs_hold_pct": dec_text(row.get("alpha_vs_hold_pct"), "0.000000"),
        "top_capture_ratio": dec_text(row.get("top_capture_ratio"), "0.000000"),
        "anchor_low_ts": dt_text(row.get("anchor_low_ts")),
        "anchor_low_price": dec_text(row.get("anchor_low_price"), "0.00000000"),
        "wave1_high_ts": dt_text(row.get("wave1_high_ts")),
        "wave1_high_price": dec_text(row.get("wave1_high_price"), "0.00000000"),
        "wave2_low_ts": dt_text(row.get("wave2_low_ts")),
        "wave2_low_price": dec_text(row.get("wave2_low_price"), "0.00000000"),
        "entry_ts": dt_text(row.get("entry_ts")),
        "entry_price": dec_text(row.get("entry_price"), "0.00000000"),
        "realized_return_pct_on_full_position": dec_text(row.get("realized_return_pct_on_full_position"), "0.000000"),
        "remaining_return_pct_on_full_position": dec_text(row.get("remaining_return_pct_on_full_position"), "0.000000"),
        "total_return_pct_with_remaining": dec_text(row.get("total_return_pct_with_remaining"), "0.000000"),
        "hold_return_pct": dec_text(row.get("hold_return_pct"), "0.000000"),
        "peak_oracle_return_pct": dec_text(row.get("peak_oracle_return_pct"), "0.000000"),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    printable = [printable_row(row) for row in rows]

    fieldnames = list(printable[0].keys()) if printable else list(printable_row({}).keys())

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in printable:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True), encoding="utf-8")


def print_best_rows(best_rows: list[dict[str, Any]]) -> None:
    columns = [
        "symbol",
        "status",
        "target_family",
        "exit_archetype",
        "max_ladder_sell_fraction",
        "total_return_pct_with_remaining",
        "hold_return_pct",
        "alpha_vs_hold_pct",
        "peak_oracle_return_pct",
        "top_capture_ratio",
        "filled_rung_count",
    ]

    print("\t".join(columns))
    for row in best_rows:
        printable = printable_row(row)
        print("\t".join(printable[column] for column in columns))


def main() -> int:
    args = parse_args()
    load_env(args.env_file)

    symbols = parse_symbol_list(args.symbols)
    target_families = parse_csv_list(args.target_families)
    max_sell_fractions = parse_decimal_list(args.max_sell_fractions)
    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)

    unknown_families = [family for family in target_families if family not in ladder_bt.TARGET_FAMILIES]
    if unknown_families:
        raise ValueError(
            f"Unknown target families: {unknown_families}. "
            f"Available: {sorted(ladder_bt.TARGET_FAMILIES)}"
        )

    all_rows: list[dict[str, Any]] = []

    conn = connect_read_only()
    try:
        asset_id_by_symbol: dict[str, Optional[int]] = {}
        candles_by_symbol: dict[str, list[Any]] = {}

        for symbol in symbols:
            asset_id = fetch_asset_id(conn, symbol)
            asset_id_by_symbol[symbol] = asset_id
            if asset_id is None:
                for target_family in target_families:
                    for max_sell_fraction in max_sell_fractions:
                        empty = ladder_bt.empty_result(symbol, "ASSET_NOT_FOUND")
                        all_rows.append(
                            result_to_row(
                                result=empty,
                                target_family=target_family,
                                max_ladder_sell_fraction=max_sell_fraction,
                                rank_metric=args.rank_metric,
                            )
                        )
                continue

            candles_by_symbol[symbol] = fetch_candles(
                conn,
                asset_id=asset_id,
                symbol=symbol,
                venue=args.venue,
                interval_code=args.interval,
                from_ts=from_ts,
                to_ts=to_ts,
            )

        for symbol in symbols:
            asset_id = asset_id_by_symbol.get(symbol)
            candles = candles_by_symbol.get(symbol, [])
            if asset_id is None:
                continue

            for target_family in target_families:
                for max_sell_fraction in max_sell_fractions:
                    result = evaluate_symbol(
                        symbol=symbol,
                        asset_id=asset_id,
                        candles=candles,
                        target_family=target_family,
                        max_ladder_sell_fraction=max_sell_fraction,
                        args=args,
                    )
                    all_rows.append(
                        result_to_row(
                            result=result,
                            target_family=target_family,
                            max_ladder_sell_fraction=max_sell_fraction,
                            rank_metric=args.rank_metric,
                        )
                    )

        conn.rollback()
    finally:
        conn.close()

    best_rows = select_best_rows(all_rows)

    payload = {
        "runner": "run_fib_exit_ladder_scoreboard_v1",
        "mode": "read_only_research",
        "symbols": symbols,
        "venue": args.venue,
        "interval": args.interval,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "target_families": target_families,
        "max_sell_fractions": max_sell_fractions,
        "rank_metric": args.rank_metric,
        "rows_total": len(all_rows),
        "best_rows": best_rows,
        "all_rows": all_rows,
    }

    if args.out_csv:
        write_csv(Path(args.out_csv), all_rows)
    if args.out_json:
        write_json(Path(args.out_json), payload)

    print("[BEST_BY_SYMBOL]")
    print_best_rows(best_rows)

    print("")
    print(
        f"done rows_total={len(all_rows)} symbols={len(symbols)} "
        f"target_families={len(target_families)} max_sell_fractions={len(max_sell_fractions)}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
