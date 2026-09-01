from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.cq_v1_temporal_population_v1 import (
    build_asof_population,
    canonical_json_sha256,
    load_temporal_contract,
    summarize_population,
)
from src.research.cq_v1_temporal_sampling_v1 import derive_asofs
from src.selection.selection_engine_v2 import load_selection_config

RUNNER_NAME = "cq_v1_temporal_population_v1"
DEFAULT_OUTPUT_DIR = "data/research/cq_v1_temporal_population_v1"
DEFAULT_SELECTION_CONFIG = "configs/selection_engine_v2.yaml"
PINNED_SELECTION_CONFIG_SHA256 = "08cec05f70cb8b2ff43b24a90dc4b8fb1f09d3535f9a791f05af3ddf57dff65b"
CHECKPOINT_VERSION = "1.0.0"

OBSERVATION_IDENTITY_FIELDS = (
    "asset_id",
    "venue",
    "asof_ts_utc",
    "evidence_key",
    "cq_model_version",
    "model_family_version",
    "coverage_artifact_sha256",
    "selection_config_sha256",
)


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build frozen 45-date PIT CQ v1 temporal population")
    p.add_argument("--venue", default="bitvavo")
    p.add_argument("--selection-config", default=DEFAULT_SELECTION_CONFIG)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--resume", action="store_true")
    return p.parse_args(argv)


def _safe_output_dir(raw: str) -> Path:
    root = Path("data/research").resolve()
    path = Path(raw).resolve()
    if path != root and root not in path.parents:
        raise ValueError("output path must remain under data/research/")
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_selection_config(raw: str) -> tuple[Path, str]:
    if raw != DEFAULT_SELECTION_CONFIG:
        raise ValueError(f"selection config path must be pinned to {DEFAULT_SELECTION_CONFIG}")
    path = Path(raw)
    digest = _sha256_path(path)
    if digest != PINNED_SELECTION_CONFIG_SHA256:
        raise ValueError(
            "selection config SHA256 mismatch: "
            f"expected={PINNED_SELECTION_CONFIG_SHA256} actual={digest}"
        )
    return path, digest


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True, indent=2, default=_json_default) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(data)
        tmp = Path(handle.name)
    os.replace(tmp, path)


def _row_line(row: dict[str, Any]) -> bytes:
    return (
        json.dumps(row, sort_keys=True, separators=(",", ":"), default=_json_default) + "\n"
    ).encode("utf-8")


def _bind_selection_config_provenance(
    rows: list[dict[str, Any]], selection_config_sha: str
) -> list[dict[str, Any]]:
    for row in rows:
        row["selection_config_sha256"] = selection_config_sha
        identity = {field: row[field] for field in OBSERVATION_IDENTITY_FIELDS}
        row["observation_id"] = canonical_json_sha256(identity)
    return rows


def _load_checkpointed_rows(path: Path, rows_written: int) -> list[dict[str, Any]]:
    if rows_written == 0:
        if path.exists():
            path.write_bytes(b"")
        return []
    if not path.exists():
        raise ValueError("checkpoint rows_written requires population.jsonl")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if len(raw_lines) < rows_written:
        raise ValueError("population.jsonl shorter than checkpoint rows_written")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw_lines[:rows_written], start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed checkpointed population row {index}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"checkpointed population row {index} is not an object")
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        for row in rows:
            handle.write(_row_line(row))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return rows


def _population_sha(path: Path) -> str:
    return _sha256_path(path)


def _identity(*, venue: str, contract_sha: str, selection_config_sha: str) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "checkpoint_version": CHECKPOINT_VERSION,
        "venue": venue,
        "contract_path": "config/research/cq_v1_temporal_sampling_v1.json",
        "contract_sha256": contract_sha,
        "selection_config_path": DEFAULT_SELECTION_CONFIG,
        "selection_config_sha256": selection_config_sha,
        "expected_unique_asof_count": 45,
    }


def _validate_resume_checkpoint(checkpoint: dict[str, Any], identity: dict[str, Any]) -> None:
    for key, expected in identity.items():
        actual = checkpoint.get(key)
        if actual != expected:
            raise ValueError(
                f"resume identity mismatch for {key}: checkpoint={actual!r} expected={expected!r}"
            )


def _write_interrupted_state(
    *,
    checkpoint_path: Path,
    summary_path: Path,
    population_path: Path,
    identity: dict[str, Any],
    signum: int,
) -> None:
    checkpoint: dict[str, Any] = {}
    if checkpoint_path.exists():
        raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            checkpoint = raw
    asofs_completed = int(checkpoint.get("asofs_completed", 0))
    rows_written = int(checkpoint.get("rows_written", 0))
    last_asof = checkpoint.get("last_asof_ts_utc")
    interrupted = {
        **identity,
        "terminal_state": "INTERRUPTED",
        "signal": signum,
        "resumable": 1,
        "asofs_completed": asofs_completed,
        "rows_written": rows_written,
        "last_asof_ts_utc": last_asof,
        "forward_outcomes_read": 0,
        "db_writes": 0,
    }
    _atomic_json(checkpoint_path, interrupted)
    _atomic_json(summary_path, interrupted)


def run(args: argparse.Namespace) -> int:
    print(f"STARTED runner={RUNNER_NAME} venue={args.venue}", flush=True)
    print(
        "SAFETY research_only=1 market_only=1 account_awareness=0 outcomes_read=0 db_writes=0 "
        "model_retuning=0 production_ranking_changes=0 decision_gate=none execution_planner=none "
        "executor=none broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 runtime_activation=0",
        flush=True,
    )
    out_dir = _safe_output_dir(args.output_dir)
    population_path = out_dir / "population.jsonl"
    summary_path = out_dir / "summary.json"
    manifest_path = out_dir / "manifest.json"
    checkpoint_path = out_dir / "checkpoint.json"

    contract = load_temporal_contract()
    asofs = derive_asofs(contract)
    if len(asofs) != 45:
        raise RuntimeError("frozen temporal contract did not derive exactly 45 as-ofs")
    contract_sha = canonical_json_sha256(contract)
    config_path, config_sha = _validate_selection_config(args.selection_config)
    config = load_selection_config(str(config_path))
    identity = _identity(
        venue=args.venue, contract_sha=contract_sha, selection_config_sha=config_sha
    )

    conn = None
    previous_handlers: dict[int, Any] = {}

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_signal)

        out_dir.mkdir(parents=True, exist_ok=True)
        if args.resume:
            if not checkpoint_path.exists():
                raise ValueError("--resume requires checkpoint.json")
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if not isinstance(checkpoint, dict):
                raise ValueError("checkpoint must be a JSON object")
            _validate_resume_checkpoint(checkpoint, identity)
            if checkpoint.get("terminal_state") == "FINISHED":
                if not population_path.exists() or not summary_path.exists() or not manifest_path.exists():
                    raise ValueError("FINISHED checkpoint missing immutable artifacts")
                if checkpoint.get("population_sha256") != _population_sha(population_path):
                    raise ValueError("FINISHED population SHA256 mismatch")
                print(
                    f"FINISHED runner={RUNNER_NAME} resume_noop=1 rows={checkpoint.get('rows_written', 0)} "
                    f"population_sha256={checkpoint.get('population_sha256')} outcomes_read=0",
                    flush=True,
                )
                return 0
            completed = int(checkpoint.get("asofs_completed", 0))
            rows_written = int(checkpoint.get("rows_written", 0))
            if completed < 0 or completed > len(asofs) or rows_written < 0:
                raise ValueError("invalid checkpoint counts")
            rows = _load_checkpointed_rows(population_path, rows_written)
            start_index = completed
            print(f"RESUME asofs_completed={completed} rows_written={rows_written}", flush=True)
        else:
            if any(
                path.exists()
                for path in (population_path, summary_path, manifest_path, checkpoint_path)
            ):
                raise ValueError(
                    "output directory already contains temporal population artifacts; use --resume"
                )
            rows = []
            start_index = 0
            _atomic_json(
                checkpoint_path,
                {
                    **identity,
                    "terminal_state": "RUNNING",
                    "asofs_completed": 0,
                    "rows_written": 0,
                    "last_asof_ts_utc": None,
                },
            )

        conn = get_db_connection()
        with population_path.open("ab") as population:
            for zero_index in range(start_index, len(asofs)):
                asof = asofs[zero_index]
                asof_rows = build_asof_population(
                    conn,
                    contract=contract,
                    asof_ts_utc=asof,
                    venue=args.venue,
                    selection_config=config,
                )
                _bind_selection_config_provenance(asof_rows, config_sha)
                for row in asof_rows:
                    population.write(_row_line(row))
                population.flush()
                os.fsync(population.fileno())
                rows.extend(asof_rows)
                _atomic_json(
                    checkpoint_path,
                    {
                        **identity,
                        "terminal_state": "RUNNING",
                        "asofs_completed": zero_index + 1,
                        "rows_written": len(rows),
                        "last_asof_ts_utc": asof.isoformat(),
                    },
                )
                print(
                    f"ASOF index={zero_index + 1}/45 ts={asof.isoformat()} rows={len(asof_rows)} total_rows={len(rows)}",
                    flush=True,
                )

        unique_asofs = {row["asof_ts_utc"] for row in rows}
        if unique_asofs != {asof.isoformat() for asof in asofs}:
            raise RuntimeError("population does not contain exactly the frozen 45 as-of timestamps")
        observation_ids = [str(row["observation_id"]) for row in rows]
        if len(observation_ids) != len(set(observation_ids)):
            raise RuntimeError("duplicate temporal observation identity")

        population_sha = _population_sha(population_path)
        summary = summarize_population(rows)
        summary.update(
            {
                "runner": RUNNER_NAME,
                "terminal_state": "FINISHED",
                "venue": args.venue,
                "contract_sha256": contract_sha,
                "selection_config_path": DEFAULT_SELECTION_CONFIG,
                "selection_config_sha256": config_sha,
                "population_sha256": population_sha,
                "expected_unique_asof_count": 45,
                "forward_outcomes_read": 0,
                "db_writes": 0,
            }
        )
        _atomic_json(summary_path, summary)
        manifest = {
            "runner": RUNNER_NAME,
            "issue": 651,
            "parent_issue": 568,
            "contract_path": "config/research/cq_v1_temporal_sampling_v1.json",
            "contract_sha256": contract_sha,
            "selection_config_path": DEFAULT_SELECTION_CONFIG,
            "selection_config_sha256": config_sha,
            "population_file": population_path.name,
            "population_sha256": population_sha,
            "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "outcomes_read": 0,
            "database_writes": 0,
        }
        _atomic_json(manifest_path, manifest)
        _atomic_json(
            checkpoint_path,
            {
                **identity,
                "terminal_state": "FINISHED",
                "asofs_completed": 45,
                "rows_written": len(rows),
                "last_asof_ts_utc": asofs[-1].isoformat(),
                "population_sha256": population_sha,
            },
        )
        print(
            f"FINISHED runner={RUNNER_NAME} rows={summary['row_count']} unique_assets={summary['unique_asset_count']} "
            f"unique_asofs={summary['unique_asof_count']} population_sha256={population_sha}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        _write_interrupted_state(
            checkpoint_path=checkpoint_path,
            summary_path=summary_path,
            population_path=population_path,
            identity=identity,
            signum=exc.signum,
        )
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} resumable=1 outcomes_read=0",
            flush=True,
        )
        return 130
    except Exception as exc:
        print(f"FAILED runner={RUNNER_NAME} error={type(exc).__name__}:{exc}", flush=True)
        raise
    finally:
        if conn is not None:
            conn.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
