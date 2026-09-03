from __future__ import annotations

"""Issue #707 Phase C: real five-asset PIT replay runner.

Research-only. Reads canonical 1d Bitvavo candles through a read-only
transaction, executes the frozen Phase A contract through the merged Phase B
engine, and writes only operator-requested local JSON evidence files.

No DB writes, account access, broker calls, decision_gate, execution_planner,
executor, runtime activation, or #657 promotion/binding.
"""

import argparse
import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as contract
from src.research import fib_exit_ladder_v1_pit_replay_engine_v1 as engine
from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt
from src.research import run_fib_exit_ladder_scoreboard_v1 as scoreboard

METHODOLOGY_VERSION = "FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1"
DEFAULT_SYMBOLS = tuple(contract.REQUIRED_ASSET_UNIVERSE)
WINDOWS = (
    ("SELECTION_WINDOW", contract.SELECTION_WINDOW),
    ("OOS_WINDOW_1", contract.OOS_WINDOW_1),
    ("OOS_WINDOW_2", contract.OOS_WINDOW_2),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen #707 Phase C PIT Fib exit-ladder replay.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--out-json", required=True)
    parser.add_argument(
        "--code-commit-sha",
        default=os.getenv("SYNTH_RESEARCH_CODE_COMMIT_SHA"),
        help="Exact reviewed commit SHA backing this run; may also be supplied via SYNTH_RESEARCH_CODE_COMMIT_SHA.",
    )
    return parser.parse_args()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _decision_provenance(window_candles: list[ladder_bt.Candle]) -> dict[str, Any]:
    anchor = engine.find_pit_anchor(window_candles)
    if anchor is None:
        return {
            "confirmation_idx": None,
            "confirmation_ts": None,
            "observable_ts": None,
        }
    return {
        "confirmation_idx": anchor.confirmation_idx,
        "confirmation_ts": _jsonable(anchor.confirmation_ts),
        # Under frozen contract §5.2, observable_ts is the next candle open and
        # equals the engine's tradeable entry_ts.
        "observable_ts": _jsonable(anchor.entry_ts),
    }


def _result_row(
    result: engine.PitSymbolResult,
    window_candles: list[ladder_bt.Candle],
) -> dict[str, Any]:
    row = _jsonable(result)
    row["fills"] = [_jsonable(fill) for fill in result.fills]
    row.update(_decision_provenance(window_candles))
    return row


def _grid_rows(
    replay: engine.PitSymbolReplayResult,
    selection_window_candles: list[ladder_bt.Candle],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family in engine.CANDIDATE_FAMILIES:
        for fraction in engine.SELL_FRACTION_GRID:
            rows.append(
                _result_row(
                    replay.selection_grid_results[(family, fraction)],
                    selection_window_candles,
                )
            )
    return rows


def _parse_symbols(text: str) -> list[str]:
    symbols = [part.strip().upper() for part in text.split(",") if part.strip()]
    if tuple(symbols) != DEFAULT_SYMBOLS:
        raise ValueError(
            "Phase C frozen universe mismatch; expected exactly " + ",".join(DEFAULT_SYMBOLS)
        )
    return symbols


def _require_code_commit_sha(value: str | None) -> str:
    sha = (value or "").strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("code_commit_sha must be an exact 40-character hexadecimal commit SHA")
    return sha


def _fetch_window_candles(
    conn: Any,
    columns: dict[str, str],
    asset_id: int,
    venue: str,
    interval: str,
    window: tuple[str, str],
) -> list[ladder_bt.Candle]:
    return ladder_bt.fetch_candles(
        conn,
        columns,
        asset_id,
        venue,
        interval,
        ladder_bt.parse_datetime(window[0]),
        ladder_bt.parse_datetime(window[1]),
    )


def _asset_evidence_row(
    *,
    symbol: str,
    asset_id: int,
    row_counts: dict[str, int],
    candles_by_window: dict[str, list[ladder_bt.Candle]],
    replay: engine.PitSymbolReplayResult,
) -> dict[str, Any]:
    if replay.selected_policy is None:
        return {
            "symbol": symbol,
            "asset_id": asset_id,
            "status": engine.STATUS_INSUFFICIENT_DATA,
            "candle_row_counts": row_counts,
            "selected_policy": None,
            "selection_grid_rows": _grid_rows(
                replay,
                candles_by_window["SELECTION_WINDOW"],
            ),
            "oos_window_1": None,
            "oos_window_2": None,
        }

    assert replay.oos_window_1_result is not None
    assert replay.oos_window_2_result is not None
    return {
        "symbol": symbol,
        "asset_id": asset_id,
        "status": "OK",
        "candle_row_counts": row_counts,
        "selected_policy": _jsonable(replay.selected_policy),
        "selection_grid_rows": _grid_rows(
            replay,
            candles_by_window["SELECTION_WINDOW"],
        ),
        "oos_window_1": _result_row(
            replay.oos_window_1_result,
            candles_by_window["OOS_WINDOW_1"],
        ),
        "oos_window_2": _result_row(
            replay.oos_window_2_result,
            candles_by_window["OOS_WINDOW_2"],
        ),
    }


def build_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if args.venue != "bitvavo" or args.interval != "1d":
        raise ValueError("Frozen #707 contract requires venue=bitvavo and interval=1d")

    symbols = _parse_symbols(args.symbols)
    code_commit_sha = _require_code_commit_sha(args.code_commit_sha)
    scoreboard.load_env(args.env_file)
    conn = scoreboard.connect_read_only()
    try:
        columns = ladder_bt.detect_candle_columns(conn)
        asset_rows: list[dict[str, Any]] = []

        for index, symbol in enumerate(symbols, start=1):
            print(f"PROGRESS phase=REPLAY asset={symbol} index={index}/{len(symbols)}")
            asset_id = ladder_bt.fetch_asset_id(conn, symbol)
            if asset_id is None:
                asset_rows.append({"symbol": symbol, "status": "ASSET_NOT_FOUND"})
                continue

            candles_by_window: dict[str, list[ladder_bt.Candle]] = {}
            row_counts: dict[str, int] = {}
            for label, window in WINDOWS:
                candles = _fetch_window_candles(
                    conn,
                    columns,
                    asset_id,
                    args.venue,
                    args.interval,
                    window,
                )
                candles_by_window[label] = candles
                row_counts[label] = len(candles)

            replay = engine.run_pit_replay_for_symbol(
                symbol=symbol,
                selection_window_candles=candles_by_window["SELECTION_WINDOW"],
                oos_window_1_candles=candles_by_window["OOS_WINDOW_1"],
                oos_window_2_candles=candles_by_window["OOS_WINDOW_2"],
            )
            asset_rows.append(
                _asset_evidence_row(
                    symbol=symbol,
                    asset_id=asset_id,
                    row_counts=row_counts,
                    candles_by_window=candles_by_window,
                    replay=replay,
                )
            )

        return {
            "schema_version": 1,
            "methodology_version": METHODOLOGY_VERSION,
            "methodology_promotion_grade": 0,
            "promotion_eligible": False,
            "code_commit_sha": code_commit_sha,
            "venue": args.venue,
            "interval": args.interval,
            "symbols": symbols,
            "windows": {
                label: {"from_ts": window[0], "to_ts": window[1]}
                for label, window in WINDOWS
            },
            "candidate_families": list(engine.CANDIDATE_FAMILIES),
            "sell_fraction_grid": [format(value, "f") for value in engine.SELL_FRACTION_GRID],
            "assets": asset_rows,
        }
    finally:
        conn.rollback()
        conn.close()


def write_evidence(path: Path, evidence: dict[str, Any]) -> str:
    payload = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    print("STARTED phase=#707_PHASE_C_PIT_REPLAY")
    try:
        args = parse_args()
        evidence = build_evidence(args)
        print("PROGRESS phase=WRITE_EVIDENCE")
        out_path = Path(args.out_json)
        digest = write_evidence(out_path, evidence)
        print(f"PIT_EVIDENCE_JSON={out_path}")
        print(f"PIT_EVIDENCE_SHA256={digest}")
        print("methodology_promotion_grade=0 pending committed raw evidence + verifier + all §10 gates")
        print("FINISHED phase=#707_PHASE_C_PIT_REPLAY status=SUCCESS")
        return 0
    except Exception as exc:
        print(f"FAILED phase=#707_PHASE_C_PIT_REPLAY error={type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
