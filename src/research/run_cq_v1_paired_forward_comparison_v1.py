from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.research.cq_v1_paired_forward_comparison_v1 import pair_rows, summarize

RUNNER_NAME = "cq_v1_paired_forward_comparison_v1"
OUTPUT_ROWS = "paired_rows.jsonl"
OUTPUT_SUMMARY = "comparison_summary.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: invalid JSONL line {line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}: JSONL line {line_number} must be an object")
            rows.append(row)
    if not rows:
        raise ValueError(f"{path}: empty JSONL")
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pair frozen CQ v1 scores with preregistered forward labels")
    parser.add_argument("--scores-jsonl", required=True)
    parser.add_argument("--outcomes-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    scores_path = Path(args.scores_jsonl)
    outcomes_path = Path(args.outcomes_jsonl)
    output_dir = Path(args.output_dir)
    print(
        f"STARTED runner={RUNNER_NAME} scores_path={scores_path} outcomes_path={outcomes_path} output_dir={output_dir}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 db_reads=0 db_writes=0 frozen_model_changed=0 "
        "production_ranking_changes=0 decision_gate=none execution_planner=none executor=none "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        flush=True,
    )
    try:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError("output directory is not empty; use a new immutable output directory")

        scores_sha256 = _sha256(scores_path)
        outcomes_sha256 = _sha256(outcomes_path)
        scores = _load_jsonl(scores_path)
        outcomes = _load_jsonl(outcomes_path)
        print(
            f"INPUTS_LOADED scores={len(scores)} outcomes={len(outcomes)} "
            f"scores_sha256={scores_sha256} outcomes_sha256={outcomes_sha256}",
            flush=True,
        )

        paired = pair_rows(scores, outcomes)
        payload = summarize(paired)
        payload.update(
            {
                "runner": RUNNER_NAME,
                "terminal_state": "FINISHED",
                "score_input_sha256": scores_sha256,
                "outcome_input_sha256": outcomes_sha256,
                "score_row_count": len(scores),
                "outcome_row_count": len(outcomes),
                "paired_row_count": len(paired),
                "bounded_cross_sectional_only": True,
                "final_phase2_recommendation": "RESEARCH_FURTHER",
                "frozen_model_changed": 0,
                "production_ranking_changed": 0,
            }
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        rows_path = output_dir / OUTPUT_ROWS
        summary_path = output_dir / OUTPUT_SUMMARY
        with rows_path.open("w", encoding="utf-8") as handle:
            for row in paired:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"WRITE event=paired_rows path={rows_path} rows={len(paired)}", flush=True)
        print(f"WRITE event=summary path={summary_path}", flush=True)
        print(
            f"FINISHED runner={RUNNER_NAME} paired_rows={len(paired)} recommendation=RESEARCH_FURTHER "
            "frozen_model_changed=0 production_ranking_changed=0",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} error_type={type(exc).__name__} error={exc}",
            flush=True,
        )
        raise


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
