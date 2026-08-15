from __future__ import annotations

"""
Synth v2 - Replay Parameter Study Harness V1.

LAYER:
research (market-only, account-agnostic)

BOUNDARY:
Allowed:
- deterministic point-in-time replay over an explicit, immutable Dataset
- pluggable, caller-supplied decision/evaluation functions
- deterministic Cartesian parameter-grid enumeration
- canonical serialization + content hashing for provenance
- fail-closed missing-data and unsupported-parameter handling

Forbidden:
- account state, balances, positions, orders, execution plans, broker calls
- any strategy-specific logic (no Fibonacci/Breathline/MA/asset-specific code)
- runtime configuration mutation
- automatic promotion of results into production

Purpose:
ONE generic, deterministic, MARKET-ONLY replay harness for bounded
parameter studies (GitHub Issue #205). This module owns dataset/universe/
parameter identity, point-in-time slicing, missing-data and
unsupported-parameter fail-closed policy, and canonical provenance.

It contains NO strategy/candidate logic. The "decision" (what to do, given
only data known as-of the cutoff) and "evaluation" (how to score what
happened, which may use data after the cutoff) behaviors are supplied by
the caller as plain functions. This keeps the harness pluggable across any
strategy family, asset, or feature set, per Issue #205 scope.

Design context:
- docs/research/replay_parameter_study_harness_v1.md (canonical doc)
- docs/todo/replay_parameter_study_harness_v1.md (frozen historical
  design notes; Issue #205 is authoritative on scope where they diverge)

Point-in-time safety model:
- `Dataset` holds ALL records (including future-relative-to-cutoff ones).
- `build_point_in_time_view()` produces a `PointInTimeView` that only ever
  exposes records with `as_of_ts_utc <= cutoff.as_of_ts_utc` (inclusive).
- The caller's `decision_fn` receives ONLY the `PointInTimeView`, never the
  raw `Dataset`. This is a structural leakage guard: no matter what the
  decision function does, it cannot read data from after the cutoff.
- The caller's `evaluation_fn` receives the full `Dataset` explicitly,
  because scoring "what happened" after a decision legitimately requires
  forward data. Future data may be used ONLY by the evaluator, never by
  the decision function.
"""

import hashlib
import itertools
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ReplayHarnessError(Exception):
    """Base class for all harness fail-closed errors."""


class UnsupportedParameterError(ReplayHarnessError):
    """Raised when a parameter name/value is not part of the declared,
    validated grid. Unsupported parameters are rejected, never silently
    ignored."""


class MissingDataError(ReplayHarnessError):
    """Raised when required data is unavailable/unknown and the study's
    missing-data policy is FAIL_CLOSED."""


class NonCanonicalValueError(ReplayHarnessError):
    """Raised when a value cannot be canonically, deterministically
    serialized (e.g. naive datetime, NaN/Infinity, opaque object)."""


class ArtifactConflictError(ReplayHarnessError):
    """Raised when attempting to overwrite an existing immutable result
    artifact (create-new-only)."""


# --------------------------------------------------------------------------
# Canonical serialization + content hashing
# --------------------------------------------------------------------------

ParamValue = bool | int | float | str


def _canonical_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise NonCanonicalValueError(f"naive datetime not allowed: {value!r}")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (frozenset, set)):
        return sorted(value)
    raise NonCanonicalValueError(
        f"cannot canonicalize value of type {type(value)!r}: {value!r} "
        "(use plain bool/int/float/str/None/dict/list/tuple or timezone-aware datetime)"
    )


def _reject_non_finite(obj: Any) -> None:
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise NonCanonicalValueError(f"non-finite float not allowed: {obj!r}")
    elif isinstance(obj, dict):
        for key, val in obj.items():
            if not isinstance(key, str):
                raise NonCanonicalValueError(f"non-string JSON key not allowed: {key!r}")
            _reject_non_finite(val)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _reject_non_finite(item)


def canonical_json(obj: Any) -> str:
    """Deterministic, canonically-equivalent JSON serialization.

    Guarantees for identical logical input:
    - dict keys sorted, no insignificant whitespace (byte-stable output)
    - UTC-normalized ISO8601 datetimes; naive datetimes are rejected
    - NaN/Infinity are rejected
    - sets/frozensets are serialized as sorted lists
    """
    _reject_non_finite(obj)
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_canonical_default,
    )


def content_hash(obj: Any) -> str:
    """SHA-256 hex digest of the canonical JSON serialization of obj."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def resolve_code_sha(repo_root: Path | None = None) -> str:
    """Best-effort current git commit SHA. Returns 'unavailable' rather than
    raising, since code_sha is provenance metadata, not a hard dependency."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(repo_root) if repo_root is not None else None,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"
    sha = result.stdout.strip()
    return sha if sha else "unavailable"


# --------------------------------------------------------------------------
# Dataset (immutable, market-only, point-in-time input)
# --------------------------------------------------------------------------

QUALITY_AVAILABLE = "AVAILABLE"
QUALITY_MISSING = "MISSING"
QUALITY_UNKNOWN = "UNKNOWN"
_VALID_QUALITY = frozenset({QUALITY_AVAILABLE, QUALITY_MISSING, QUALITY_UNKNOWN})


@dataclass(frozen=True)
class ReplayRecord:
    """One immutable, timestamped, market-only observation.

    `payload` is a plain mapping of feature values using only JSON-plain
    types (bool/int/float/str/None/dict/list) or explicit UTC datetimes.
    The harness never interprets `payload`; only the caller-supplied
    decision/evaluation functions interpret it. This keeps the harness
    generic across any strategy family or feature set.
    """

    symbol: str
    as_of_ts_utc: datetime
    quality: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol or not isinstance(self.symbol, str):
            raise ReplayHarnessError("ReplayRecord.symbol must be a non-empty str")
        if self.as_of_ts_utc.tzinfo is None:
            raise ReplayHarnessError("ReplayRecord.as_of_ts_utc must be timezone-aware UTC")
        if self.quality not in _VALID_QUALITY:
            raise ReplayHarnessError(f"unknown record quality: {self.quality!r}")

    def canonical(self) -> dict:
        return {
            "symbol": self.symbol,
            "as_of_ts_utc": self.as_of_ts_utc,
            "quality": self.quality,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class Dataset:
    """Immutable historical input. Half-open UTC bounds [start, end)."""

    dataset_id: str
    schema_version: str
    source_refs: tuple[str, ...]
    start_ts_utc: datetime
    end_ts_utc: datetime
    records: tuple[ReplayRecord, ...]

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.schema_version:
            raise ReplayHarnessError("Dataset.dataset_id and schema_version are required")
        if self.start_ts_utc.tzinfo is None or self.end_ts_utc.tzinfo is None:
            raise ReplayHarnessError("Dataset bounds must be timezone-aware UTC")
        if self.end_ts_utc <= self.start_ts_utc:
            raise ReplayHarnessError("Dataset.end_ts_utc must be after start_ts_utc")
        for rec in self.records:
            if not (self.start_ts_utc <= rec.as_of_ts_utc < self.end_ts_utc):
                raise ReplayHarnessError(
                    f"record {rec.symbol}@{rec.as_of_ts_utc.isoformat()} outside dataset "
                    f"bounds [{self.start_ts_utc.isoformat()}, {self.end_ts_utc.isoformat()})"
                )

    def canonical(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "schema_version": self.schema_version,
            "source_refs": list(self.source_refs),
            "start_ts_utc": self.start_ts_utc,
            "end_ts_utc": self.end_ts_utc,
            "records": [rec.canonical() for rec in self.records],
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.canonical())

    @property
    def identity(self) -> str:
        return f"{self.dataset_id}@{self.schema_version}:{self.content_hash}"


@dataclass(frozen=True)
class UniverseSpec:
    """Explicit, immutable instrument universe identity."""

    universe_id: str
    version: str
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.universe_id or not self.version:
            raise ReplayHarnessError("UniverseSpec.universe_id and version are required")
        if not self.symbols:
            raise ReplayHarnessError("UniverseSpec.symbols must be non-empty")
        if len(set(self.symbols)) != len(self.symbols):
            raise ReplayHarnessError("UniverseSpec.symbols must not contain duplicates")

    def canonical(self) -> dict:
        return {
            "universe_id": self.universe_id,
            "version": self.version,
            "symbols": sorted(self.symbols),
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.canonical())

    @property
    def identity(self) -> str:
        return f"{self.universe_id}@{self.version}:{self.content_hash}"


@dataclass(frozen=True)
class ReplayCutoff:
    """One explicit UTC as-of boundary. Records with
    `as_of_ts_utc <= as_of_ts_utc` are known-by-cutoff (inclusive)."""

    as_of_ts_utc: datetime
    label: str = "as_of"

    def __post_init__(self) -> None:
        if self.as_of_ts_utc.tzinfo is None:
            raise ReplayHarnessError("ReplayCutoff.as_of_ts_utc must be timezone-aware UTC")


# --------------------------------------------------------------------------
# Point-in-time view (structural leakage guard)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PointInTimeView:
    """A leakage-safe view of a Dataset: only records with
    `as_of_ts_utc <= cutoff.as_of_ts_utc` are reachable through this object.
    Decision functions receive ONLY this view, never the raw Dataset."""

    cutoff: ReplayCutoff
    by_symbol: Mapping[str, tuple[ReplayRecord, ...]]

    def latest(self, symbol: str) -> ReplayRecord | None:
        records = self.by_symbol.get(symbol, ())
        return records[-1] if records else None

    def history(self, symbol: str) -> tuple[ReplayRecord, ...]:
        return self.by_symbol.get(symbol, ())

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.by_symbol.keys()))


def build_point_in_time_view(dataset: Dataset, cutoff: ReplayCutoff) -> PointInTimeView:
    visible = [rec for rec in dataset.records if rec.as_of_ts_utc <= cutoff.as_of_ts_utc]
    by_symbol: dict[str, list[ReplayRecord]] = {}
    for rec in sorted(visible, key=lambda r: (r.symbol, r.as_of_ts_utc)):
        by_symbol.setdefault(rec.symbol, []).append(rec)
    return PointInTimeView(
        cutoff=cutoff,
        by_symbol={symbol: tuple(recs) for symbol, recs in by_symbol.items()},
    )


# --------------------------------------------------------------------------
# Missing-data classification (explicit, never a silent skip)
# --------------------------------------------------------------------------

MISSING_DATA_POLICY_FAIL_CLOSED = "FAIL_CLOSED"
MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE = "CLASSIFY_AND_CONTINUE"
_VALID_MISSING_DATA_POLICIES = frozenset(
    {MISSING_DATA_POLICY_FAIL_CLOSED, MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE}
)


@dataclass(frozen=True)
class MissingDataReport:
    """Explicit per-symbol data-quality classification as of the cutoff.
    Always produced, regardless of policy, so missing data is never a
    silent skip."""

    policy: str
    missing_symbols: tuple[str, ...]
    unknown_symbols: tuple[str, ...]
    available_symbols: tuple[str, ...]

    def canonical(self) -> dict:
        return {
            "policy": self.policy,
            "missing_symbols": list(self.missing_symbols),
            "unknown_symbols": list(self.unknown_symbols),
            "available_symbols": list(self.available_symbols),
        }


def classify_missing_data(view: PointInTimeView, universe: UniverseSpec, *, policy: str) -> MissingDataReport:
    if policy not in _VALID_MISSING_DATA_POLICIES:
        raise ReplayHarnessError(f"unknown missing_data_policy: {policy!r}")

    missing: list[str] = []
    unknown: list[str] = []
    available: list[str] = []

    for symbol in universe.symbols:
        latest = view.latest(symbol)
        if latest is None or latest.quality == QUALITY_MISSING:
            missing.append(symbol)
        elif latest.quality == QUALITY_UNKNOWN:
            unknown.append(symbol)
        else:
            available.append(symbol)

    return MissingDataReport(
        policy=policy,
        missing_symbols=tuple(sorted(missing)),
        unknown_symbols=tuple(sorted(unknown)),
        available_symbols=tuple(sorted(available)),
    )


# --------------------------------------------------------------------------
# Parameter grid (generic, pluggable, fail-closed on unsupported names)
# --------------------------------------------------------------------------

# Safety/account/permission-shaped parameter names are never tunable via a
# research parameter study, regardless of study author intent. This is a
# generic name-based guard, not a strategy-specific rule.
DEFAULT_FORBIDDEN_PARAMETER_NAMES = frozenset(
    {
        "account_id",
        "api_key",
        "api_secret",
        "balance",
        "leverage",
        "live_mode",
        "broker",
        "order_size",
        "position_size",
        "risk_limit",
        "withdrawal",
        "credential",
        "decision_gate",
        "execution_planner",
        "executor",
    }
)


@dataclass(frozen=True)
class ParameterDimension:
    name: str
    values: tuple[ParamValue, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise UnsupportedParameterError("parameter dimension name must be non-empty")
        if not self.values:
            raise UnsupportedParameterError(f"parameter dimension {self.name!r} has no values")
        for value in self.values:
            if isinstance(value, bool):
                continue
            if not isinstance(value, (int, float, str)):
                raise UnsupportedParameterError(
                    f"parameter {self.name!r} has unsupported value type {type(value)!r}"
                )
            if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
                raise UnsupportedParameterError(f"parameter {self.name!r} has a non-finite float value")
        if len(set(self.values)) != len(self.values):
            raise UnsupportedParameterError(f"parameter {self.name!r} has duplicate values")


@dataclass(frozen=True)
class ParameterSet:
    candidate_id: str
    values: Mapping[str, ParamValue]

    def canonical(self) -> dict:
        return {"candidate_id": self.candidate_id, "values": dict(self.values)}


def _candidate_id(index: int, values: Mapping[str, ParamValue]) -> str:
    digest = content_hash(dict(values))[:10]
    return f"P{index:05d}-{digest}"


@dataclass(frozen=True)
class ParameterGrid:
    """Declares the full set of tunable parameter dimensions for a study.
    Any parameter name not declared here is unsupported and must be
    rejected (see `apply_parameter_overlay`)."""

    dimensions: tuple[ParameterDimension, ...]
    forbidden_parameter_names: frozenset[str] = DEFAULT_FORBIDDEN_PARAMETER_NAMES

    def __post_init__(self) -> None:
        if not self.dimensions:
            raise UnsupportedParameterError("ParameterGrid must declare at least one dimension")
        names = [dim.name for dim in self.dimensions]
        if len(set(names)) != len(names):
            raise UnsupportedParameterError("ParameterGrid has duplicate dimension names")
        for name in names:
            if name in self.forbidden_parameter_names:
                raise UnsupportedParameterError(
                    f"parameter {name!r} is a forbidden/never-tunable safety parameter"
                )

    @property
    def allowed_parameter_names(self) -> frozenset[str]:
        return frozenset(dim.name for dim in self.dimensions)

    def canonical(self) -> dict:
        return {
            "dimensions": [{"name": dim.name, "values": list(dim.values)} for dim in self.dimensions],
        }

    @property
    def digest(self) -> str:
        return content_hash(self.canonical())

    def enumerate(self) -> tuple[ParameterSet, ...]:
        """Deterministic Cartesian expansion in declared dimension/value
        order. Identical grid input always produces identical parameter
        sets in identical order with identical candidate_id values."""
        names = [dim.name for dim in self.dimensions]
        value_lists = [dim.values for dim in self.dimensions]
        combos = list(itertools.product(*value_lists))
        out = []
        for index, combo in enumerate(combos):
            values = dict(zip(names, combo))
            out.append(ParameterSet(candidate_id=_candidate_id(index, values), values=values))
        return tuple(out)


def apply_parameter_overlay(
    base: Mapping[str, Any],
    overlay: Mapping[str, ParamValue],
    *,
    allowed_parameter_names: frozenset[str],
) -> dict[str, Any]:
    """Apply a validated in-memory parameter overlay onto a frozen base
    config, returning a new dict. `base` is never mutated.

    Fails closed: any overlay key not present in `allowed_parameter_names`
    is rejected (never silently ignored, never merged).
    """
    unsupported = set(overlay.keys()) - set(allowed_parameter_names)
    if unsupported:
        raise UnsupportedParameterError(
            f"unsupported parameter override(s) rejected: {sorted(unsupported)}"
        )
    merged = dict(base)
    merged.update(overlay)
    return merged


# --------------------------------------------------------------------------
# Study definition, evaluation result, study result
# --------------------------------------------------------------------------

DecisionFn = Callable[[ParameterSet, PointInTimeView, ReplayCutoff, MissingDataReport], Any]
EvaluationFn = Callable[[ParameterSet, Any, Dataset, ReplayCutoff], "EvaluationResult"]


@dataclass(frozen=True)
class ParameterStudyDefinition:
    """Binds a pluggable parameter grid to explicit feature-version and
    missing-data-policy identity. Contains no strategy logic itself; the
    decision/evaluation behavior is supplied separately as functions."""

    study_id: str
    study_version: str
    feature_versions: Mapping[str, str]
    parameter_grid: ParameterGrid
    missing_data_policy: str = MISSING_DATA_POLICY_FAIL_CLOSED
    decision_fn_id: str = "unspecified"
    evaluation_fn_id: str = "unspecified"

    def __post_init__(self) -> None:
        if not self.study_id or not self.study_version:
            raise ReplayHarnessError("study_id and study_version are required")
        if self.missing_data_policy not in _VALID_MISSING_DATA_POLICIES:
            raise ReplayHarnessError(f"unknown missing_data_policy: {self.missing_data_policy!r}")
        if not self.feature_versions:
            raise ReplayHarnessError("feature_versions must be explicit and non-empty")

    def canonical(self) -> dict:
        return {
            "study_id": self.study_id,
            "study_version": self.study_version,
            "feature_versions": dict(self.feature_versions),
            "parameter_grid": self.parameter_grid.canonical(),
            "missing_data_policy": self.missing_data_policy,
            "decision_fn_id": self.decision_fn_id,
            "evaluation_fn_id": self.evaluation_fn_id,
        }


@dataclass(frozen=True)
class EvaluationResult:
    """Versioned, market-only evaluation output for one parameter set.
    Never ranks, promotes, or mutates runtime state; it is evidence only."""

    candidate_id: str
    parameter_values: Mapping[str, ParamValue]
    sample_count: int
    metrics: Mapping[str, float | int]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sample_count < 0:
            raise ReplayHarnessError("sample_count must be >= 0")

    def canonical(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "parameter_values": dict(self.parameter_values),
            "sample_count": self.sample_count,
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ParameterStudyResult:
    """Immutable, provenance-bound top-level study result. Every field
    required by the Issue #205 evidence contract is present except
    `code_sha`/`generated_at_utc`, which are attached here directly."""

    dataset_identity: str
    cutoff_ts_utc: datetime
    universe_identity: str
    feature_versions: Mapping[str, str]
    parameter_grid_digest: str
    code_sha: str
    missing_data_report: MissingDataReport
    results: tuple[EvaluationResult, ...]
    generated_at_utc: datetime

    def canonical_content(self) -> dict:
        """Canonical payload used for `result_content_hash`. Excludes
        `generated_at_utc`: timestamps are metadata, not content identity."""
        return {
            "dataset_identity": self.dataset_identity,
            "cutoff_ts_utc": self.cutoff_ts_utc,
            "universe_identity": self.universe_identity,
            "feature_versions": dict(self.feature_versions),
            "parameter_grid_digest": self.parameter_grid_digest,
            "code_sha": self.code_sha,
            "missing_data_report": self.missing_data_report.canonical(),
            "results": [r.canonical() for r in self.results],
        }

    @property
    def result_content_hash(self) -> str:
        return content_hash(self.canonical_content())

    @property
    def run_id(self) -> str:
        """Deterministic run identity derived only from content, never
        wall-clock time."""
        return self.result_content_hash

    def to_json(self) -> str:
        payload = self.canonical_content()
        payload["generated_at_utc"] = self.generated_at_utc
        payload["result_content_hash"] = self.result_content_hash
        return canonical_json(payload)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_parameter_study(
    *,
    study: ParameterStudyDefinition,
    dataset: Dataset,
    universe: UniverseSpec,
    cutoff: ReplayCutoff,
    decision_fn: DecisionFn,
    evaluation_fn: EvaluationFn,
    code_sha: str | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> ParameterStudyResult:
    """Run one deterministic, market-only, point-in-time-safe parameter
    study.

    - `decision_fn` receives only a `PointInTimeView` sliced to `cutoff`;
      it structurally cannot see records after the cutoff.
    - `evaluation_fn` receives the full `dataset` (including records after
      the cutoff); future data may be used only here.
    - Missing/unknown required universe data is always explicitly
      classified in the result's `missing_data_report`. Under
      `MISSING_DATA_POLICY_FAIL_CLOSED` the run raises `MissingDataError`
      instead of silently proceeding.
    - Identical inputs (dataset, universe, study, cutoff, and pure
      decision/evaluation functions) always produce an identical
      `result_content_hash` and identical `to_json()` output.
    """
    resolved_code_sha = code_sha if code_sha is not None else resolve_code_sha()

    view = build_point_in_time_view(dataset, cutoff)
    missing_report = classify_missing_data(view, universe, policy=study.missing_data_policy)

    blocking = missing_report.missing_symbols or missing_report.unknown_symbols
    if study.missing_data_policy == MISSING_DATA_POLICY_FAIL_CLOSED and blocking:
        raise MissingDataError(
            "missing/unknown required data under FAIL_CLOSED policy: "
            f"missing={list(missing_report.missing_symbols)} "
            f"unknown={list(missing_report.unknown_symbols)}"
        )

    parameter_sets = study.parameter_grid.enumerate()

    results: list[EvaluationResult] = []
    for parameter_set in parameter_sets:
        decision_output = decision_fn(parameter_set, view, cutoff, missing_report)
        eval_result = evaluation_fn(parameter_set, decision_output, dataset, cutoff)
        if not isinstance(eval_result, EvaluationResult):
            raise ReplayHarnessError(
                f"evaluation_fn must return EvaluationResult, got {type(eval_result)!r}"
            )
        if eval_result.candidate_id != parameter_set.candidate_id:
            raise ReplayHarnessError(
                "evaluation_fn returned mismatched candidate_id: "
                f"expected {parameter_set.candidate_id!r}, got {eval_result.candidate_id!r}"
            )
        results.append(eval_result)

    return ParameterStudyResult(
        dataset_identity=dataset.identity,
        cutoff_ts_utc=cutoff.as_of_ts_utc,
        universe_identity=universe.identity,
        feature_versions=dict(study.feature_versions),
        parameter_grid_digest=study.parameter_grid.digest,
        code_sha=resolved_code_sha,
        missing_data_report=missing_report,
        results=tuple(results),
        generated_at_utc=now_fn(),
    )


# --------------------------------------------------------------------------
# Immutable artifact writer (create-new-only, atomic)
# --------------------------------------------------------------------------


def write_result_artifact(result: ParameterStudyResult, output_dir: Path) -> Path:
    """Atomically write an immutable JSON result artifact keyed by
    `result.run_id`. Never overwrites an existing artifact for the same
    run identity (create-new-only)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"{result.run_id}.json"
    if final_path.exists():
        raise ArtifactConflictError(f"artifact already exists (immutable): {final_path}")

    tmp_path = output_dir / f".{result.run_id}.json.tmp-{os.getpid()}"
    tmp_path.write_text(result.to_json(), encoding="utf-8")
    try:
        tmp_path.replace(final_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return final_path
