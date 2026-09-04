"""
Synth v2.6 research runner: RUN_FIB_EXIT_LADDER_V1_PIT_REPLAY_V1 (Issue #707
Phase C).

Layer:
    research only. A read-only DB replay runner wrapped around the frozen
    Phase B PIT replay engine
    (src/research/fib_exit_ladder_v1_pit_replay_engine_v1.py, unmodified)
    and the frozen Phase A contract
    (docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md). This module
    adds only DB I/O (candle fetch, validation, evidence serialization); it
    contains no anchor/selection/disposition logic of its own.

Boundary:
    - source: obs_market_candle (read-only session: SET SESSION TRANSACTION
      READ ONLY, START TRANSACTION READ ONLY, explicit rollback() on close),
      same discipline as run_fib_exit_ladder_scoreboard_v1.connect_read_only.
    - SELECT-only: every query goes through
      run_fib_exit_ladder_backtest_v1.fetch_all, which raises on any
      non-SELECT statement via assert_read_only_sql. No write-capable
      connection is opened, and this module issues no INSERT/UPDATE/DELETE/
      DDL statement anywhere.
    - No account/balance/position/order access.
    - No decision_gate, execution_planner, or executor imports.
    - No automatic_exit_profile_v1 writes, no #657 binding.
    - Frozen universe/windows/grid: this runner exposes no CLI flag that can
      override REQUIRED_ASSET_UNIVERSE, SELECTION_WINDOW/OOS_WINDOW_1/
      OOS_WINDOW_2, CANDIDATE_FAMILIES, or SELL_FRACTION_GRID (all imported
      from the frozen contract module, not redefined here). Only DB
      connection parameters (via env vars / --env-file) and the output
      directory are configurable from the CLI.

Fail-closed:
    - A required asset symbol that does not resolve to an asset_id in the DB
      aborts the entire run (PitReplayRunnerError), never a partial universe.
    - A window query that returns zero candle rows aborts the entire run
      (a completely empty window is treated as a data/config problem, not a
      legitimate INSUFFICIENT_CANDLES business outcome -- that status is
      reserved for a non-empty but too-short series, handled downstream by
      the frozen engine).
    - A duplicate or non-monotonic candle timestamp within one asset/window
      query result aborts the entire run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pymysql

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as pit_contract
from src.research import fib_exit_ladder_v1_pit_replay_engine_v1 as pit_engine
from src.research.run_fib_exit_ladder_backtest_v1 import (
    Candle,
    fetch_all,
    fetch_asset_id as _bt_fetch_asset_id,
)

# Frozen per docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md § 2.
# Not a CLI-configurable value: changing venue/interval changes the
# methodology, which this runner must not silently permit.
VENUE = "bitvavo"
INTERVAL_CODE = "1d"

# Re-exported from the frozen contract module; never redefined here.
REQUIRED_ASSET_UNIVERSE = pit_contract.REQUIRED_ASSET_UNIVERSE
CANDIDATE_FAMILIES = pit_contract.CANDIDATE_FAMILIES
SELL_FRACTION_GRID = pit_contract.SELL_FRACTION_GRID

WINDOWS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("SELECTION_WINDOW", pit_contract.SELECTION_WINDOW),
    ("OOS_WINDOW_1", pit_contract.OOS_WINDOW_1),
    ("OOS_WINDOW_2", pit_contract.OOS_WINDOW_2),
)

METHODOLOGY_VERSION = "fib_exit_ladder_v1_pit_replay_contract_v1@v1"

MIN_CANDLES_REQUIRED = pit_engine.MIN_CANDLES_REQUIRED


class PitReplayRunnerError(RuntimeError):
    """Fail-closed runner error: missing asset, missing window data, or
    non-monotonic/duplicate candle data. This runner never silently
    degrades to a partial or synthesized result on any of these."""


# ---------------------------------------------------------------------------
# DB access (read-only).
# ---------------------------------------------------------------------------


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


def fetch_asset_id(conn: pymysql.connections.Connection, symbol: str) -> int:
    asset_id = _bt_fetch_asset_id(conn, symbol)
    if asset_id is None:
        raise PitReplayRunnerError(f"Required asset not found in DB: {symbol!r}.")
    return asset_id


def _assert_monotonic_no_duplicates(candles: list[Candle], *, symbol: str, window_label: str) -> None:
    for prev, cur in zip(candles, candles[1:]):
        if cur.open_ts_utc == prev.open_ts_utc:
            raise PitReplayRunnerError(
                f"Duplicate candle timestamp for {symbol} {window_label}: {cur.open_ts_utc}."
            )
        if cur.open_ts_utc < prev.open_ts_utc:
            raise PitReplayRunnerError(
                f"Non-monotonic candle ordering for {symbol} {window_label} at {cur.open_ts_utc} "
                f"(preceded by {prev.open_ts_utc})."
            )


def fetch_window_candles(
    conn: pymysql.connections.Connection,
    *,
    asset_id: int,
    symbol: str,
    window_label: str,
    window: tuple[str, str],
) -> list[Candle]:
    """SELECT-only fetch of one asset's candles for one exact window,
    deterministically ordered by open_ts_utc ASC. Fails closed (raises) on
    zero rows, a duplicate timestamp, or non-monotonic ordering."""
    from_ts = pit_engine.parse_datetime(window[0])
    to_ts = pit_engine.parse_datetime(window[1])

    rows = fetch_all(
        conn,
        """
        SELECT
            open_ts_utc,
            open_price,
            high_price,
            low_price,
            close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND open_ts_utc >= %s
          AND open_ts_utc < %s
        ORDER BY open_ts_utc ASC
        """,
        (asset_id, VENUE, INTERVAL_CODE, from_ts, to_ts),
    )

    if not rows:
        raise PitReplayRunnerError(
            f"No candles returned for {symbol} {window_label} "
            f"[{from_ts} -> {to_ts}); failing closed rather than proceeding "
            "with a missing window."
        )

    candles = [
        Candle(
            open_ts_utc=row["open_ts_utc"],
            open_price=Decimal(str(row["open_price"])),
            high_price=Decimal(str(row["high_price"])),
            low_price=Decimal(str(row["low_price"])),
            close_price=Decimal(str(row["close_price"])),
        )
        for row in rows
    ]
    _assert_monotonic_no_duplicates(candles, symbol=symbol, window_label=window_label)
    return candles


# ---------------------------------------------------------------------------
# Orchestration: fetch + frozen-engine replay for the complete universe.
# ---------------------------------------------------------------------------


def run_replay_for_universe(
    conn: pymysql.connections.Connection,
    symbols: tuple[str, ...] = REQUIRED_ASSET_UNIVERSE,
) -> tuple[dict[str, pit_engine.PitSymbolReplayResult], dict[str, dict[str, int]]]:
    """Fetches candles for every required asset/window and runs the frozen
    Phase B engine's `run_pit_replay_for_symbol` unchanged. Returns the
    per-symbol replay results plus per-(asset, window) candle row counts for
    the evidence/provenance record. Raises PitReplayRunnerError (fail-closed)
    if any required asset or window cannot be fetched."""
    results: dict[str, pit_engine.PitSymbolReplayResult] = {}
    row_counts: dict[str, dict[str, int]] = {}

    for symbol in symbols:
        asset_id = fetch_asset_id(conn, symbol)
        window_candles: dict[str, list[Candle]] = {}
        row_counts[symbol] = {}
        for window_label, window in WINDOWS:
            candles = fetch_window_candles(
                conn,
                asset_id=asset_id,
                symbol=symbol,
                window_label=window_label,
                window=window,
            )
            window_candles[window_label] = candles
            row_counts[symbol][window_label] = len(candles)

        results[symbol] = pit_engine.run_pit_replay_for_symbol(
            symbol=symbol,
            selection_window_candles=window_candles["SELECTION_WINDOW"],
            oos_window_1_candles=window_candles["OOS_WINDOW_1"],
            oos_window_2_candles=window_candles["OOS_WINDOW_2"],
        )

    return results, row_counts


# ---------------------------------------------------------------------------
# Evidence serialization (§ 11 of the frozen contract).
# ---------------------------------------------------------------------------


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


def _symbol_result_row(result: pit_engine.PitSymbolResult) -> dict[str, Any]:
    return json_safe(asdict(result))


def build_selection_grid_rows(
    results: dict[str, pit_engine.PitSymbolReplayResult],
) -> list[dict[str, Any]]:
    """Selection-grid evidence only (§ 7): every (asset, family, fraction)
    row evaluated on SELECTION_WINDOW. This is structurally separate from
    `build_oos_rows` below -- neither function reads from the other's input,
    so there is no code path here that could rank OOS alternatives."""
    rows: list[dict[str, Any]] = []
    for symbol, replay in results.items():
        for (family, fraction), grid_result in replay.selection_grid_results.items():
            row = _symbol_result_row(grid_result)
            row["family"] = family
            row["max_ladder_sell_fraction"] = json_safe(fraction)
            rows.append(row)
    return rows


def build_selected_policy_rows(
    results: dict[str, pit_engine.PitSymbolReplayResult],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, replay in results.items():
        if replay.selected_policy is None:
            rows.append(
                {
                    "symbol": symbol,
                    "status": "INSUFFICIENT_DATA",
                    "target_family": None,
                    "max_ladder_sell_fraction": None,
                    "selection_metric_value": None,
                    "selection_sample_count": 0,
                }
            )
            continue
        selected = replay.selected_policy
        rows.append(
            {
                "symbol": symbol,
                "status": "OK",
                "target_family": selected.target_family,
                "max_ladder_sell_fraction": json_safe(selected.max_ladder_sell_fraction),
                "selection_metric_value": json_safe(selected.selection_metric_value),
                "selection_sample_count": selected.selection_sample_count,
            }
        )
    return rows


def build_oos_rows(results: dict[str, pit_engine.PitSymbolReplayResult]) -> list[dict[str, Any]]:
    """OOS evidence only (§ 8): each already-selected policy's OOS_WINDOW_1
    and OOS_WINDOW_2 outcome. This function never reads `selection_grid_results`
    for any symbol, so it structurally cannot rank OOS alternatives -- it
    only ever sees the single frozen `selected_policy` per symbol."""
    rows: list[dict[str, Any]] = []
    for symbol, replay in results.items():
        for oos_result in (replay.oos_window_1_result, replay.oos_window_2_result):
            if oos_result is None:
                continue
            rows.append(_symbol_result_row(oos_result))
    return rows


def build_input_window_metadata(
    row_counts: dict[str, dict[str, int]],
) -> dict[str, Any]:
    return {
        "venue": VENUE,
        "interval_code": INTERVAL_CODE,
        "symbol_universe": list(REQUIRED_ASSET_UNIVERSE),
        "windows": {
            label: {"from_ts": bounds[0], "to_ts": bounds[1]}
            for label, bounds in WINDOWS
        },
        "candle_row_counts": row_counts,
    }


def git_commit_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2])
            .decode("utf-8")
            .strip()
        )
    except Exception:  # pragma: no cover - defensive, evidence still written
        return "UNKNOWN"


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_evidence(
    output_dir: Path,
    results: dict[str, pit_engine.PitSymbolReplayResult],
    row_counts: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Writes the raw immutable evidence files (§ 11) and a machine-readable
    manifest recording sha256/size/row-count/provenance for each, so the
    verifier (§ 12) can validate them without re-running the replay."""
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()

    input_window_metadata = build_input_window_metadata(row_counts)
    selection_grid_rows = build_selection_grid_rows(results)
    selected_policy_rows = build_selected_policy_rows(results)
    oos_rows = build_oos_rows(results)

    files = {
        "input_window_metadata_v1.json": input_window_metadata,
        "selection_grid_results_v1.json": {
            "rows_total": len(selection_grid_rows),
            "rows": selection_grid_rows,
        },
        "selected_policies_v1.json": {
            "rows_total": len(selected_policy_rows),
            "rows": selected_policy_rows,
        },
        "oos_evaluation_results_v1.json": {
            "rows_total": len(oos_rows),
            "rows": oos_rows,
        },
    }

    manifest_files: dict[str, Any] = {}
    for filename, payload in files.items():
        file_path = raw_dir / filename
        file_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_files[filename] = {
            "sha256": sha256_of_file(file_path),
            "byte_size": file_path.stat().st_size,
        }

    manifest = {
        "methodology_version": METHODOLOGY_VERSION,
        "code_commit_sha": git_commit_sha(),
        "generated_at_utc": generated_at,
        "venue": VENUE,
        "interval_code": INTERVAL_CODE,
        "symbol_universe": list(REQUIRED_ASSET_UNIVERSE),
        "candidate_families": list(CANDIDATE_FAMILIES),
        "sell_fraction_grid": [str(fraction) for fraction in SELL_FRACTION_GRID],
        "windows": {label: {"from_ts": bounds[0], "to_ts": bounds[1]} for label, bounds in WINDOWS},
        "files": manifest_files,
    }
    manifest_path = raw_dir / "manifest_v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return manifest


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Issue #707 Phase C: run the real, read-only, frozen-universe "
            "PIT Fib exit-ladder replay against obs_market_candle and write "
            "immutable raw evidence. No CLI flag can override the frozen "
            "universe, windows, or candidate grid."
        )
    )
    parser.add_argument("--env-file", default=None, help="Optional .env file with SYNTH_DB_*/DB_* credentials.")
    parser.add_argument(
        "--output-dir",
        default="docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1",
        help="Directory to write raw/ evidence files under.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    load_env(args.env_file)

    conn = connect_read_only()
    try:
        print(
            f"STARTED run_fib_exit_ladder_v1_pit_replay_v1 "
            f"universe={REQUIRED_ASSET_UNIVERSE} venue={VENUE} interval={INTERVAL_CODE}",
            flush=True,
        )
        results, row_counts = run_replay_for_universe(conn)
        print("FINISHED replay for all required assets/windows.", flush=True)
    finally:
        conn.rollback()
        conn.close()

    output_dir = Path(args.output_dir)
    manifest = write_evidence(output_dir, results, row_counts)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
