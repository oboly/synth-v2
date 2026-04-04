from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.common.db import get_db_connection


DEFAULT_CONFIG_PATH = "configs/etl_bitvavo_candles.yaml"


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_yaml(path: str) -> dict[str, Any]:
    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML config at {path}: root must be a mapping")

    return data


def get_intervals(config: dict[str, Any]) -> list[str]:
    intervals = config.get("intervals")

    if not isinstance(intervals, list) or not intervals:
        raise ValueError("Config must contain a non-empty 'intervals' list")

    out: list[str] = []

    for interval in intervals:
        if not isinstance(interval, str):
            raise ValueError("All interval entries must be strings")
        out.append(interval.strip())

    return out


def run_step(cmd: list[str], name: str) -> None:
    print(f"[STEP] {name}")
    print(f"       cmd: {' '.join(cmd)}")

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"[ERROR] step failed: {name}")
        sys.exit(result.returncode)

    print(f"[OK] {name}\n")


def run_interval(interval: str) -> None:
    print("--------------------------------------")
    print(f"[INTERVAL] {interval}")
    print("--------------------------------------")

    run_step(
        [
            sys.executable,
            "-m",
            "src.features.run_feat_candle",
            "--interval",
            interval,
        ],
        f"feat_candle[{interval}]",
    )

    run_step(
        [
            sys.executable,
            "-m",
            "src.engine.run_signal_engine",
            "--interval",
            interval,
            "--limit-per-asset",
            "1",
        ],
        f"signal_engine[{interval}]",
    )

    run_step(
        [
            sys.executable,
            "-m",
            "src.advice.run_advice_engine",
            "--interval",
            interval,
        ],
        f"advice_engine[{interval}]",
    )


def run_global_layers() -> None:
    run_step(
        [
            sys.executable,
            "-m",
            "src.selection.run_selection_engine",
        ],
        "selection_engine",
    )

    run_step(
        [
            sys.executable,
            "-m",
            "src.decision.run_decision_engine",
        ],
        "decision_engine",
    )

    run_step(
        [
            sys.executable,
            "-m",
            "src.risk.run_risk_engine",
        ],
        "risk_engine",
    )

    run_step(
        [
            sys.executable,
            "-m",
            "src.portfolio.run_portfolio_state",
        ],
        "portfolio_state",
    )

    run_step(
        [
            sys.executable,
            "-m",
            "src.execution.run_execution_intent",
        ],
        "execution_intent",
    )


def fetch_rows(conn, sql: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def print_portfolio_summary(conn) -> None:
    sql = """
    SELECT
      symbol,
      target_action,
      target_position_size_pct,
      portfolio_slot,
      portfolio_bucket
    FROM v_portfolio_board
    WHERE target_position_size_pct > 0
    ORDER BY
      CASE
        WHEN portfolio_slot IS NULL THEN 999
        ELSE portfolio_slot
      END,
      target_position_size_pct DESC,
      symbol
    """

    rows = fetch_rows(conn, sql)

    print("======================================")
    print("PORTFOLIO SUMMARY")
    print("======================================")

    if not rows:
        print("(no active target positions)\n")
        return

    for row in rows:
        slot = "-" if row["portfolio_slot"] is None else str(row["portfolio_slot"])
        print(
            f'{row["symbol"]:8} | '
            f'slot={slot:>2} | '
            f'action={row["target_action"]:14} | '
            f'size={float(row["target_position_size_pct"]):.4f} | '
            f'bucket={row["portfolio_bucket"]}'
        )

    print("")


def print_execution_summary(conn) -> None:
    sql = """
    SELECT
      symbol,
      previous_position_size_pct,
      target_position_size_pct,
      size_delta_pct,
      intent_action,
      intent_priority
    FROM v_execution_board
    WHERE intent_action <> 'IGNORE'
    ORDER BY intent_priority, symbol
    """

    rows = fetch_rows(conn, sql)

    print("======================================")
    print("EXECUTION SUMMARY")
    print("======================================")

    if not rows:
        print("(no execution changes)\n")
        return

    for row in rows:
        print(
            f'{row["symbol"]:8} | '
            f'intent={row["intent_action"]:6} | '
            f'prev={float(row["previous_position_size_pct"]):.4f} | '
            f'target={float(row["target_position_size_pct"]):.4f} | '
            f'delta={float(row["size_delta_pct"]):+.4f}'
        )

    print("")


def print_data_health_summary(conn) -> None:
    sql = """
    SELECT
      symbol,
      interval_code,
      latest_open_ts_utc,
      hours_since_update,
      health_status
    FROM v_market_data_health
    WHERE health_status = 'STALE'
    ORDER BY hours_since_update DESC, symbol, interval_code
    """

    rows = fetch_rows(conn, sql)

    print("======================================")
    print("DATA HEALTH SUMMARY")
    print("======================================")

    if not rows:
        print("(no stale market data rows)\n")
        return

    for row in rows:
        print(
            f'{row["symbol"]:8} | '
            f'interval={row["interval_code"]:>2} | '
            f'hours={int(row["hours_since_update"]):>4} | '
            f'latest={row["latest_open_ts_utc"]}'
        )

    print("")


def print_end_summary() -> None:
    try:
        conn = get_db_connection()
    except Exception as exc:
        print(f"[WARN] Could not open DB for end summary: {exc}")
        return

    try:
        print_portfolio_summary(conn)
        print_execution_summary(conn)
        print_data_health_summary(conn)
    except Exception as exc:
        print(f"[WARN] Could not print full end summary: {exc}")
    finally:
        conn.close()


def run(config_path: str, etl_only_once: bool) -> None:
    config = load_yaml(config_path)
    intervals = get_intervals(config)

    print("======================================")
    print("SYNTH LIVE CYCLE")
    print(f"UTC: {now_utc_str()}")
    print(f"config: {config_path}")
    print(f"intervals: {', '.join(intervals)}")
    print("======================================\n")

    if etl_only_once:
        run_step(
            [
                sys.executable,
                "-m",
                "src.etl.bitvavo.run_candles_etl",
                "--config",
                config_path,
            ],
            "candles_etl[all_config_intervals]",
        )

        for interval in intervals:
            run_interval(interval)

    else:
        for interval in intervals:
            run_step(
                [
                    sys.executable,
                    "-m",
                    "src.etl.bitvavo.run_candles_etl",
                    "--config",
                    config_path,
                ],
                f"candles_etl[{interval} via config]",
            )

            run_interval(interval)

    run_global_layers()
    print_end_summary()

    print("======================================")
    print("[DONE] FULL CYCLE COMPLETE")
    print("======================================\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full Synth live cycle")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to ETL config YAML (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--etl-only-once",
        action="store_true",
        help="Run candles ETL once using config intervals, then process all intervals",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(config_path=args.config, etl_only_once=args.etl_only_once)
