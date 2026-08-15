from __future__ import annotations

"""
Synth v2 - Run Replay Parameter Study Harness V1.

LAYER:
research (market-only, account-agnostic)

BOUNDARY:
Allowed:
- read a bounded dataset/universe/study JSON file from disk
- dynamically load caller-supplied decision/evaluation functions by dotted
  "module:function" path
- run one deterministic market-only replay parameter study
- write an immutable, create-new-only JSON result artifact

Forbidden:
- account state, balances, positions, orders, execution plans, broker calls
- any strategy-specific logic beyond the two illustrative demo functions
  below, which are generic threshold plumbing, not a strategy
- runtime configuration mutation
- automatic promotion of results into production

Purpose:
Thin CLI entrypoint over
`src.research.replay_parameter_study_harness_v1.run_parameter_study`.
Dataset, universe, and study identity are supplied as JSON files; the
decision/evaluation behavior is supplied as a dotted callable path so this
runner never hardcodes a strategy family. Two small, generic demo
functions are included so the CLI is directly testable end to end without
importing any strategy-specific module.

safety markers:
  broker_writes=0
  order_submissions=0
  production_database_mutation=0
  service_timer_changes=0
"""

import argparse
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.research.replay_parameter_study_harness_v1 import (
    DEFAULT_FORBIDDEN_PARAMETER_NAMES,
    MISSING_DATA_POLICY_FAIL_CLOSED,
    Dataset,
    EvaluationResult,
    ParameterDimension,
    ParameterGrid,
    ParameterSet,
    ParameterStudyDefinition,
    PointInTimeView,
    ReplayCutoff,
    ReplayHarnessError,
    ReplayRecord,
    UniverseSpec,
    run_parameter_study,
    write_result_artifact,
)


RUNNER_NAME = "run_replay_parameter_study_harness_v1"
VERSION = "1.0"


# --------------------------------------------------------------------------
# Generic demo decision/evaluation functions (illustrative plumbing only,
# not a strategy). Selected via --decision-fn/--evaluation-fn by default so
# the CLI is testable without any strategy-specific import.
# --------------------------------------------------------------------------


def demo_field_threshold_decision(
    parameter_set: ParameterSet,
    view: PointInTimeView,
    cutoff: ReplayCutoff,
    missing_report: Any,
) -> dict[str, Any]:
    """Generic demo decision function: select symbols whose latest
    known-by-cutoff `payload[field_name]` is >= `threshold`. `field_name`
    and `threshold` come entirely from the parameter grid, so this is not
    tied to any specific feature, asset, or strategy family."""
    field_name = str(parameter_set.values["field_name"])
    threshold = float(parameter_set.values["threshold"])

    selected: list[str] = []
    for symbol in view.symbols():
        latest = view.latest(symbol)
        if latest is None:
            continue
        raw_value = latest.payload.get(field_name)
        if raw_value is None:
            continue
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if numeric_value >= threshold:
            selected.append(symbol)

    return {"selected_symbols": tuple(sorted(selected))}


def demo_field_threshold_evaluation(
    parameter_set: ParameterSet,
    decision_output: dict[str, Any],
    dataset: Dataset,
    cutoff: ReplayCutoff,
) -> EvaluationResult:
    """Generic demo evaluator: counts how many selected symbols have any
    record after the cutoff. Future data is used only here, never in the
    decision function. Purely illustrative plumbing metric, not a
    strategy-outcome definition."""
    selected = tuple(decision_output.get("selected_symbols", ()))

    symbols_with_future_record: set[str] = set()
    for rec in dataset.records:
        if rec.as_of_ts_utc > cutoff.as_of_ts_utc:
            symbols_with_future_record.add(rec.symbol)

    observed_forward_count = sum(1 for symbol in selected if symbol in symbols_with_future_record)

    return EvaluationResult(
        candidate_id=parameter_set.candidate_id,
        parameter_values=parameter_set.values,
        sample_count=len(selected),
        metrics={
            "selected_count": len(selected),
            "observed_forward_count": observed_forward_count,
        },
        warnings=(),
    )


# --------------------------------------------------------------------------
# Loaders (JSON -> harness contracts)
# --------------------------------------------------------------------------


def _parse_utc_ts(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include an explicit UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def load_dataset(path: Path) -> Dataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = tuple(
        ReplayRecord(
            symbol=str(rec["symbol"]),
            as_of_ts_utc=_parse_utc_ts(rec["as_of_ts_utc"]),
            quality=str(rec["quality"]),
            payload=dict(rec.get("payload") or {}),
        )
        for rec in raw["records"]
    )
    return Dataset(
        dataset_id=str(raw["dataset_id"]),
        schema_version=str(raw["schema_version"]),
        source_refs=tuple(str(s) for s in raw.get("source_refs", [])),
        start_ts_utc=_parse_utc_ts(raw["start_ts_utc"]),
        end_ts_utc=_parse_utc_ts(raw["end_ts_utc"]),
        records=records,
    )


def load_universe(path: Path) -> UniverseSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return UniverseSpec(
        universe_id=str(raw["universe_id"]),
        version=str(raw["version"]),
        symbols=tuple(str(s) for s in raw["symbols"]),
    )


def load_study(path: Path) -> ParameterStudyDefinition:
    raw = json.loads(path.read_text(encoding="utf-8"))
    grid_raw = raw["parameter_grid"]
    dimensions = tuple(
        ParameterDimension(name=str(dim["name"]), values=tuple(dim["values"]))
        for dim in grid_raw["dimensions"]
    )
    if "forbidden_parameter_names" in grid_raw:
        forbidden = frozenset(str(x) for x in grid_raw["forbidden_parameter_names"])
    else:
        forbidden = DEFAULT_FORBIDDEN_PARAMETER_NAMES

    grid = ParameterGrid(dimensions=dimensions, forbidden_parameter_names=forbidden)

    return ParameterStudyDefinition(
        study_id=str(raw["study_id"]),
        study_version=str(raw["study_version"]),
        feature_versions={str(k): str(v) for k, v in raw["feature_versions"].items()},
        parameter_grid=grid,
        missing_data_policy=str(raw.get("missing_data_policy", MISSING_DATA_POLICY_FAIL_CLOSED)),
        decision_fn_id=str(raw.get("decision_fn_id", "unspecified")),
        evaluation_fn_id=str(raw.get("evaluation_fn_id", "unspecified")),
    )


def _load_callable(dotted_path: str) -> Callable:
    if ":" not in dotted_path:
        raise ValueError(f"expected 'module.path:function_name', got {dotted_path!r}")
    module_name, _, func_name = dotted_path.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, func_name)
    except AttributeError as exc:
        raise ValueError(f"{func_name!r} not found in module {module_name!r}") from exc


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one generic, deterministic, market-only replay parameter "
            "study (Issue #205). Dataset/universe/study identity comes from "
            "explicit JSON files; decision/evaluation behavior is supplied "
            "as a 'module:function' dotted path so this runner never "
            "hardcodes a strategy family."
        )
    )
    parser.add_argument("--dataset-file", required=True, help="Path to dataset JSON.")
    parser.add_argument("--universe-file", required=True, help="Path to universe JSON.")
    parser.add_argument("--study-file", required=True, help="Path to parameter-study definition JSON.")
    parser.add_argument(
        "--cutoff",
        required=True,
        help="UTC ISO8601 as-of cutoff, e.g. 2026-01-15T00:00:00+00:00",
    )
    parser.add_argument(
        "--decision-fn",
        default=f"{__name__}:demo_field_threshold_decision",
        help="Dotted 'module:function' path for the point-in-time decision function.",
    )
    parser.add_argument(
        "--evaluation-fn",
        default=f"{__name__}:demo_field_threshold_evaluation",
        help="Dotted 'module:function' path for the evaluation function.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for the immutable JSON result artifact. If omitted, no artifact is written.",
    )
    parser.add_argument(
        "--code-sha",
        default=None,
        help="Override the resolved git commit SHA (mainly for deterministic tests).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print(f"STARTED {RUNNER_NAME} version={VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("broker_writes=0 order_submissions=0 production_database_mutation=0 service_timer_changes=0")

    try:
        dataset = load_dataset(Path(args.dataset_file))
        universe = load_universe(Path(args.universe_file))
        study = load_study(Path(args.study_file))
        cutoff = ReplayCutoff(as_of_ts_utc=_parse_utc_ts(args.cutoff))

        decision_fn = _load_callable(args.decision_fn)
        evaluation_fn = _load_callable(args.evaluation_fn)

        result = run_parameter_study(
            study=study,
            dataset=dataset,
            universe=universe,
            cutoff=cutoff,
            decision_fn=decision_fn,
            evaluation_fn=evaluation_fn,
            code_sha=args.code_sha,
        )

        artifact_path: Path | None = None
        if args.output_dir:
            artifact_path = write_result_artifact(result, Path(args.output_dir))
    except ReplayHarnessError as exc:
        print(f"missing_data_or_unsupported_parameter_error={exc}")
        print(f"FAILED {RUNNER_NAME}")
        return 1
    except KeyboardInterrupt:
        print(f"INTERRUPTED {RUNNER_NAME}")
        return 130

    print(f"dataset_identity={result.dataset_identity}")
    print(f"cutoff={result.cutoff_ts_utc.isoformat()}")
    print(f"universe_identity={result.universe_identity}")
    print(f"feature_versions={json.dumps(dict(result.feature_versions), sort_keys=True)}")
    print(f"parameter_grid_digest={result.parameter_grid_digest}")
    print(f"code_sha={result.code_sha}")
    print(f"result_content_hash={result.result_content_hash}")
    print(f"parameter_sets_evaluated={len(result.results)}")
    print(f"missing_symbols={list(result.missing_data_report.missing_symbols)}")
    print(f"unknown_symbols={list(result.missing_data_report.unknown_symbols)}")
    print(f"result_artifact={artifact_path if artifact_path is not None else '(not written; pass --output-dir)'}")
    print("runtime_changes=0")
    print(f"FINISHED {RUNNER_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
