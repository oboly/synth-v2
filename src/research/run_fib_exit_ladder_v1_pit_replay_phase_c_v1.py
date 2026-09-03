from __future__ import annotations

"""Issue #707 Phase C: real five-asset PIT replay runner.

Research-only. Reads canonical 1d Bitvavo candles through a read-only
transaction, executes the frozen Phase A contract through the merged Phase B
engine, and writes only operator-requested local JSON evidence/checkpoint
files.

No DB writes, account access, broker calls, decision_gate, execution_planner,
executor, runtime activation, or #657 promotion/binding.
"""

import argparse
import hashlib
import json
import os
import signal
import time
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
RUNNER_NAME = "run_fib_exit_ladder_v1_pit_replay_phase_c_v1"
RUN_MODE = "RESEARCH_READ_ONLY"
RUN_SCOPE = "LINK,XLM,SOL,XRP,HOT"
RUN_WORKER = "single"
DEFAULT_SYMBOLS = tuple(contract.REQUIRED_ASSET_UNIVERSE)
WINDOWS = (
    ("SELECTION_WINDOW", contract.SELECTION_WINDOW),
    ("OOS_WINDOW_1", contract.OOS_WINDOW_1),
    ("OOS_WINDOW_2", contract.OOS_WINDOW_2),
)


class RunnerInterrupted(RuntimeError):
    """Raised by bounded signal handlers so the runner can emit one terminal line."""


def _emit(message: str) -> None:
    print(message, flush=True)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _raise_interrupted(signum: int, _frame: Any) -> None:
    raise RunnerInterrupted(signal.Signals(signum).name)


def _install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _raise_interrupted)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen #707 Phase C PIT Fib exit-ladder replay.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--out-json", required=True)
    parser.add_argument(
        "--checkpoint-json",
        default=None,
        help="Checkpoint path; defaults to <out-json>.checkpoint.json.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an existing checkpoint after validating frozen run identity.",
    )
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
            "anchor_low": None,
            "anchor_low_ts": None,
            "wave1_high": None,
            "wave1_high_ts": None,
            "wave2_low": None,
            "wave2_low_ts": None,
            "confirmation_idx": None,
            "confirmation_ts": None,
            "observable_ts": None,
        }
    return {
        "anchor_low": _jsonable(anchor.anchor_low),
        "anchor_low_ts": _jsonable(anchor.anchor_low_ts),
        "wave1_high": _jsonable(anchor.wave1_high),
        "wave1_high_ts": _jsonable(anchor.wave1_high_ts),
        "wave2_low": _jsonable(anchor.wave2_low),
        "wave2_low_ts": _jsonable(anchor.wave2_low_ts),
        "confirmation_idx": anchor.confirmation_idx,
        "confirmation_ts": _jsonable(anchor.confirmation_ts),
        "observable_ts": _jsonable(anchor.entry_ts),
    }


def _outcome_components(
    result: engine.PitSymbolResult,
    window_candles: list[ladder_bt.Candle],
) -> dict[str, Any]:
    filled_fraction = sum((fill.sell_fraction for fill in result.fills), Decimal("0"))
    if filled_fraction > Decimal("1"):
        filled_fraction = Decimal("1")
    remaining_fraction = Decimal("1") - filled_fraction
    avg_exit_price = ladder_bt.weighted_avg_exit_price(list(result.fills))

    realized_return = None
    remaining_return = None
    if result.status == engine.STATUS_OK and result.entry_price is not None and window_candles:
        realized_return = sum(
            (
                fill.sell_fraction * ladder_bt.return_pct(fill.limit_price, result.entry_price)
                for fill in result.fills
            ),
            Decimal("0"),
        )
        remaining_return = remaining_fraction * ladder_bt.return_pct(
            window_candles[-1].close_price,
            result.entry_price,
        )

    return {
        "fill_count": len(result.fills),
        "filled_fraction": _jsonable(filled_fraction),
        "remaining_fraction": _jsonable(remaining_fraction),
        "avg_exit_price": _jsonable(avg_exit_price),
        "realized_return_pct_on_full_position": _jsonable(realized_return),
        "remaining_return_pct_on_full_position": _jsonable(remaining_return),
    }


def _result_row(
    result: engine.PitSymbolResult,
    window_candles: list[ladder_bt.Candle],
) -> dict[str, Any]:
    row = _jsonable(result)
    row["fills"] = [_jsonable(fill) for fill in result.fills]
    row.update(_decision_provenance(window_candles))
    row.update(_outcome_components(result, window_candles))
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


def _checkpoint_path(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "checkpoint_json", None)
    if explicit:
        return Path(explicit)
    return Path(str(args.out_json) + ".checkpoint.json")


def _base_evidence(
    *,
    symbols: list[str],
    venue: str,
    interval: str,
    code_commit_sha: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "methodology_version": METHODOLOGY_VERSION,
        "methodology_promotion_grade": 0,
        "promotion_eligible": False,
        "code_commit_sha": code_commit_sha,
        "venue": venue,
        "interval": interval,
        "symbols": symbols,
        "windows": {
            label: {"from_ts": window[0], "to_ts": window[1]}
            for label, window in WINDOWS
        },
        "candidate_families": list(engine.CANDIDATE_FAMILIES),
        "sell_fraction_grid": [format(value, "f") for value in engine.SELL_FRACTION_GRID],
        "assets": [],
    }


def _json_payload(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _atomic_write_json(path: Path, value: dict[str, Any]) -> str:
    payload = _json_payload(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_resume_checkpoint(path: Path, expected: dict[str, Any]) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"resume requested but checkpoint does not exist: {path}")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "schema_version",
        "methodology_version",
        "code_commit_sha",
        "venue",
        "interval",
        "symbols",
        "windows",
        "candidate_families",
        "sell_fraction_grid",
    ):
        if checkpoint.get(key) != expected.get(key):
            raise ValueError(f"checkpoint identity mismatch for {key}")
    asset_rows = checkpoint.get("assets")
    if not isinstance(asset_rows, list):
        raise ValueError("checkpoint assets must be a list")
    completed_symbols = [row.get("symbol") for row in asset_rows]
    if completed_symbols != expected["symbols"][: len(completed_symbols)]:
        raise ValueError("checkpoint assets must be an ordered frozen-universe prefix")
    return asset_rows


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
        selection_statuses = {
            result.status
            for result in getattr(replay, "selection_grid_results", {}).values()
        }
        status = (
            engine.STATUS_INSUFFICIENT_CANDLES
            if selection_statuses == {engine.STATUS_INSUFFICIENT_CANDLES}
            else engine.STATUS_INSUFFICIENT_DATA
        )
        return {
            "symbol": symbol,
            "asset_id": asset_id,
            "status": status,
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


def _asset_not_found_evidence_row(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "asset_id": None,
        "status": "ASSET_NOT_FOUND",
        "candle_row_counts": {label: 0 for label, _ in WINDOWS},
        "selected_policy": None,
        "selection_grid_rows": [],
        "oos_window_1": None,
        "oos_window_2": None,
    }


def build_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if args.venue != "bitvavo" or args.interval != "1d":
        raise ValueError("Frozen #707 contract requires venue=bitvavo and interval=1d")

    symbols = _parse_symbols(args.symbols)
    code_commit_sha = _require_code_commit_sha(args.code_commit_sha)
    evidence = _base_evidence(
        symbols=symbols,
        venue=args.venue,
        interval=args.interval,
        code_commit_sha=code_commit_sha,
    )
    checkpoint_path = _checkpoint_path(args)
    if getattr(args, "resume", False):
        evidence["assets"] = _load_resume_checkpoint(checkpoint_path, evidence)
        _emit(
            f"RESUMED runner={RUNNER_NAME} checkpoint={checkpoint_path} "
            f"completed_assets={len(evidence['assets'])}"
        )
    elif checkpoint_path.exists():
        raise ValueError(
            f"checkpoint already exists: {checkpoint_path}; pass --resume or choose a new checkpoint path"
        )

    scoreboard.load_env(args.env_file)
    conn_started = time.monotonic()
    conn = scoreboard.connect_read_only()
    _emit(
        f"PHASE runner={RUNNER_NAME} phase=CONNECT_READ_ONLY elapsed_ms={_elapsed_ms(conn_started)}"
    )
    try:
        columns_started = time.monotonic()
        columns = ladder_bt.detect_candle_columns(conn)
        _emit(
            f"QUERY runner={RUNNER_NAME} phase=DETECT_CANDLE_COLUMNS row_count={len(columns)} "
            f"elapsed_ms={_elapsed_ms(columns_started)}"
        )

        completed = len(evidence["assets"])
        for index, symbol in enumerate(symbols[completed:], start=completed + 1):
            asset_started = time.monotonic()
            _emit(
                f"PROGRESS runner={RUNNER_NAME} phase=REPLAY asset={symbol} "
                f"index={index}/{len(symbols)}"
            )
            asset_id_started = time.monotonic()
            asset_id = ladder_bt.fetch_asset_id(conn, symbol)
            _emit(
                f"QUERY runner={RUNNER_NAME} phase=FETCH_ASSET_ID asset={symbol} "
                f"row_count={0 if asset_id is None else 1} elapsed_ms={_elapsed_ms(asset_id_started)}"
            )
            if asset_id is None:
                evidence["assets"].append(_asset_not_found_evidence_row(symbol))
            else:
                candles_by_window: dict[str, list[ladder_bt.Candle]] = {}
                row_counts: dict[str, int] = {}
                for label, window in WINDOWS:
                    query_started = time.monotonic()
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
                    _emit(
                        f"QUERY runner={RUNNER_NAME} phase=FETCH_CANDLES asset={symbol} "
                        f"window={label} row_count={len(candles)} elapsed_ms={_elapsed_ms(query_started)}"
                    )

                replay_started = time.monotonic()
                replay = engine.run_pit_replay_for_symbol(
                    symbol=symbol,
                    selection_window_candles=candles_by_window["SELECTION_WINDOW"],
                    oos_window_1_candles=candles_by_window["OOS_WINDOW_1"],
                    oos_window_2_candles=candles_by_window["OOS_WINDOW_2"],
                )
                evidence["assets"].append(
                    _asset_evidence_row(
                        symbol=symbol,
                        asset_id=asset_id,
                        row_counts=row_counts,
                        candles_by_window=candles_by_window,
                        replay=replay,
                    )
                )
                _emit(
                    f"PHASE runner={RUNNER_NAME} phase=ENGINE_REPLAY asset={symbol} "
                    f"row_count={sum(row_counts.values())} elapsed_ms={_elapsed_ms(replay_started)}"
                )

            checkpoint_started = time.monotonic()
            digest = _atomic_write_json(checkpoint_path, evidence)
            _emit(
                f"CHECKPOINT runner={RUNNER_NAME} asset={symbol} completed_assets={len(evidence['assets'])} "
                f"sha256={digest} elapsed_ms={_elapsed_ms(checkpoint_started)} path={checkpoint_path}"
            )
            _emit(
                f"PROGRESS runner={RUNNER_NAME} phase=ASSET_COMPLETE asset={symbol} "
                f"index={index}/{len(symbols)} elapsed_ms={_elapsed_ms(asset_started)}"
            )

        return evidence
    finally:
        conn.rollback()
        conn.close()


def write_evidence(path: Path, evidence: dict[str, Any]) -> str:
    return _atomic_write_json(path, evidence)


def main() -> int:
    run_started = time.monotonic()
    _emit(
        "STARTED "
        f"runner={RUNNER_NAME} mode={RUN_MODE} scope={RUN_SCOPE} worker={RUN_WORKER} "
        "phase=#707_PHASE_C_PIT_REPLAY"
    )
    previous_handlers = _install_signal_handlers()
    try:
        try:
            args = parse_args()
        except SystemExit as exc:
            exit_code = int(exc.code) if isinstance(exc.code, int) else 1
            if exit_code == 0:
                _emit(
                    f"FINISHED runner={RUNNER_NAME} phase=#707_PHASE_C_PIT_REPLAY "
                    f"status=HELP elapsed_ms={_elapsed_ms(run_started)}"
                )
                return 0
            _emit(
                f"FAILED runner={RUNNER_NAME} phase=#707_PHASE_C_PIT_REPLAY "
                f"status=ARGPARSE exit_code={exit_code} elapsed_ms={_elapsed_ms(run_started)}"
            )
            return exit_code

        evidence = build_evidence(args)
        write_started = time.monotonic()
        _emit(f"PROGRESS runner={RUNNER_NAME} phase=WRITE_EVIDENCE")
        out_path = Path(args.out_json)
        digest = write_evidence(out_path, evidence)
        _emit(
            f"PHASE runner={RUNNER_NAME} phase=WRITE_EVIDENCE row_count={len(evidence['assets'])} "
            f"elapsed_ms={_elapsed_ms(write_started)}"
        )
        _emit(f"PIT_EVIDENCE_JSON={out_path}")
        _emit(f"PIT_EVIDENCE_SHA256={digest}")
        _emit("methodology_promotion_grade=0 pending committed raw evidence + verifier + all §10 gates")
        _emit(
            f"FINISHED runner={RUNNER_NAME} phase=#707_PHASE_C_PIT_REPLAY status=SUCCESS "
            f"elapsed_ms={_elapsed_ms(run_started)}"
        )
        return 0
    except (RunnerInterrupted, KeyboardInterrupt) as exc:
        reason = str(exc) or type(exc).__name__
        _emit(
            f"INTERRUPTED runner={RUNNER_NAME} phase=#707_PHASE_C_PIT_REPLAY "
            f"reason={reason} elapsed_ms={_elapsed_ms(run_started)}"
        )
        return 130
    except Exception as exc:
        _emit(
            f"FAILED runner={RUNNER_NAME} phase=#707_PHASE_C_PIT_REPLAY "
            f"error={type(exc).__name__}:{exc} elapsed_ms={_elapsed_ms(run_started)}"
        )
        return 1
    finally:
        _restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
