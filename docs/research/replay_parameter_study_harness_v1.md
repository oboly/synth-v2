# Replay Parameter Study Harness V1

> Canonical documentation for GitHub Issue
> [#205 — Implement replay parameter-study harness for market-only validation](https://github.com/oboly/synth-v2/issues/205).
> This is the authoritative design/status document for the harness. The
> earlier `docs/todo/replay_parameter_study_harness_v1.md` is frozen
> historical/design context (a larger, Selection-Engine-v2-specific,
> multi-PR plan); where it conflicts with this document or with Issue
> #205, Issue #205 and this document govern.

## Status

```text
IMPLEMENTED — generic V1 harness + CLI wrapper + tests (Issue #205)
```

## Purpose

Provide ONE generic, deterministic, MARKET-ONLY replay harness for bounded
parameter studies. The harness owns dataset/universe/parameter identity,
point-in-time slicing, missing-data and unsupported-parameter fail-closed
policy, and canonical result provenance.

It intentionally contains **no strategy logic**. It is not specific to any
strategy family, indicator (Fibonacci, Breathline, moving averages, ...),
or asset. The "decision" and "evaluation" behavior for any concrete study
is supplied by the caller as plain Python functions ("plugins"), so the
same harness composes with any future market-only research lane without
modification.

## Non-goals (V1)

Consistent with the frozen `docs/todo/replay_parameter_study_harness_v1.md`
non-goals, V1 does **not** include:

- random/adaptive/optimizer search (Optuna, TPE, Bayesian, CMA-ES, NSGA-II);
- rolling walk-forward orchestration (one explicit cutoff per run call);
- a database experiment registry;
- distributed execution;
- execution/fill/fee/slippage simulation;
- account-aware evaluation;
- dashboards/UI;
- automatic promotion of any result into runtime configuration.

## Module map

```text
src/research/replay_parameter_study_harness_v1.py       core library (pure, no I/O)
src/research/run_replay_parameter_study_harness_v1.py    CLI wrapper + generic demo plugin functions
tests/test_replay_parameter_study_harness_v1.py           determinism / leakage / missing-data / unsupported-parameter tests
tests/fixtures/replay_parameter_study_harness_v1/         small deterministic fixture (dataset/universe/study JSON)
```

The core module has zero DB, broker, or network dependencies. It is pure,
deterministic Python plus a best-effort `git rev-parse HEAD` for
`code_sha`.

## Core contracts

### `Dataset`

Immutable historical input: `dataset_id`, `schema_version`, `source_refs`,
half-open UTC bounds `[start_ts_utc, end_ts_utc)`, and an ordered tuple of
`ReplayRecord`. Every record must fall inside the declared bounds
(construction fails otherwise). `Dataset.identity` and
`Dataset.content_hash` are derived from canonical serialization.

### `ReplayRecord`

One immutable, timestamped, market-only observation: `symbol`,
`as_of_ts_utc` (timezone-aware UTC, required), `quality`
(`AVAILABLE` / `MISSING` / `UNKNOWN`), and a generic `payload` mapping.
The harness never interprets `payload`; only caller-supplied
decision/evaluation functions do.

### `UniverseSpec`

Explicit, immutable instrument universe identity (`universe_id`,
`version`, `symbols`). `UniverseSpec.identity` binds a study to one
specific, versioned symbol set.

### `ReplayCutoff`

One explicit UTC as-of boundary. A record is "known-by-cutoff" when
`record.as_of_ts_utc <= cutoff.as_of_ts_utc` (inclusive). V1 supports one
cutoff per `run_parameter_study()` call; rolling/multi-cutoff studies are
out of scope (call the harness once per cutoff if needed).

### `ParameterGrid` / `ParameterDimension` / `ParameterSet`

A `ParameterGrid` declares one or more named `ParameterDimension`s, each
with an explicit tuple of allowed scalar values (`bool | int | float |
str`). `ParameterGrid.enumerate()` performs a **deterministic Cartesian
expansion** in declared dimension/value order, producing a `ParameterSet`
per combination with a stable `candidate_id` derived from
`P{index:05d}-{content_hash(values)[:10]}`.

Safety/account-shaped parameter names (`account_id`, `api_key`, `balance`,
`leverage`, `live_mode`, `broker`, `order_size`, `decision_gate`,
`execution_planner`, `executor`, ...) are rejected at grid-construction
time via `DEFAULT_FORBIDDEN_PARAMETER_NAMES` (callers may extend this set
via `forbidden_parameter_names`). This is a generic name-based guard, not
a strategy-specific rule.

### `apply_parameter_overlay(base, overlay, *, allowed_parameter_names)`

Applies a validated in-memory parameter overlay onto a frozen base config
dict, returning a new dict. Any overlay key not present in
`allowed_parameter_names` raises `UnsupportedParameterError` — unsupported
parameters are **rejected, never silently ignored**.

### `PointInTimeView` / `build_point_in_time_view()` — the leakage guard

`build_point_in_time_view(dataset, cutoff)` produces a `PointInTimeView`
that only ever exposes records with `as_of_ts_utc <= cutoff.as_of_ts_utc`.
The caller's `decision_fn` receives **only** this view, never the raw
`Dataset`. This is a structural guarantee: regardless of what a
decision function does internally, it cannot read a record from after the
cutoff, because that record is not reachable through the object it was
given.

The caller's `evaluation_fn` receives the **full** `Dataset` (including
future-relative-to-cutoff records) explicitly, because scoring "what
happened after the decision" legitimately requires forward data. Future
data may be used **only** by the evaluator, never by the decision
function — this mirrors the market-only research rule in `AGENTS.md`
("Use point-in-time replay for historical validation").

### Missing-data policy — explicit, never a silent skip

`classify_missing_data()` always classifies every universe symbol as
`available` / `missing` / `unknown` as of the cutoff and records this in a
`MissingDataReport`, regardless of policy.

- `MISSING_DATA_POLICY_FAIL_CLOSED` (default): if any universe symbol is
  missing/unknown as of the cutoff, `run_parameter_study()` raises
  `MissingDataError` before invoking any decision/evaluation function.
- `MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE`: the run proceeds, but the
  `MissingDataReport` (which symbols were missing/unknown/available) is
  attached to the result unconditionally, so downstream review always sees
  the classification explicitly.

There is no third option that silently drops a symbol without recording
it.

### `ParameterStudyDefinition`

Binds a `ParameterGrid` to `study_id`/`study_version`, explicit
`feature_versions` (non-empty, required), a `missing_data_policy`, and
`decision_fn_id`/`evaluation_fn_id` labels used purely for
provenance/logging (the actual functions are passed separately to
`run_parameter_study()`, since Python callables are not JSON-serializable
and the study definition itself must stay canonically hashable).

### `EvaluationResult` / `ParameterStudyResult`

`EvaluationResult` is versioned, market-only evidence for one parameter
set: `candidate_id`, `parameter_values`, `sample_count`, `metrics`,
`warnings`. It never ranks, promotes, or mutates runtime state.

`ParameterStudyResult` is the top-level, immutable output of one run. It
binds every field required by the Issue #205 evidence contract:
`dataset_identity`, `cutoff_ts_utc`, `universe_identity`,
`feature_versions`, `parameter_grid_digest`, `code_sha`, plus the
`missing_data_report` and the tuple of `EvaluationResult`. `generated_at_utc`
is attached but explicitly **excluded** from `result_content_hash` —
timestamps are metadata, not content identity, per the frozen contract
note ("Timestamps are metadata, not part of content identity").
`ParameterStudyResult.run_id` is simply `result_content_hash`: a
deterministic identity derived only from content, never wall-clock time.

### `canonical_json()` / `content_hash()`

Deterministic, canonically-equivalent JSON serialization: sorted dict
keys, no insignificant whitespace, UTC-normalized ISO8601 datetimes (naive
datetimes rejected), NaN/Infinity rejected. `content_hash()` is the
SHA-256 hex digest of the canonical JSON. Every identity field in this
harness (`dataset_identity`, `universe_identity`, `parameter_grid_digest`,
`result_content_hash`) is derived through this path, so identical logical
input always produces byte-identical canonical output and therefore an
identical hash.

### `write_result_artifact()`

Writes `result.to_json()` to `{output_dir}/{result.run_id}.json`
atomically (write to a temp file, then `Path.replace()`). If an artifact
for that `run_id` already exists, raises `ArtifactConflictError` —
**create-new-only**, no silent overwrite of an existing immutable result.

## CLI wrapper

`src/research/run_replay_parameter_study_harness_v1.py` is a thin,
generic CLI over the library:

```bash
python -m src.research.run_replay_parameter_study_harness_v1 \
  --dataset-file <dataset.json> \
  --universe-file <universe.json> \
  --study-file <study.json> \
  --cutoff 2026-01-15T00:00:00+00:00 \
  --decision-fn "some.module:some_decision_fn" \
  --evaluation-fn "some.module:some_evaluation_fn" \
  --output-dir data/research/replay_parameter_study/<study_id>/
```

`--decision-fn`/`--evaluation-fn` default to two small, generic
"threshold on a named payload field" demo functions defined in the same
module (`demo_field_threshold_decision`,
`demo_field_threshold_evaluation`). These exist purely so the CLI is
testable end to end without importing any strategy-specific module; they
are illustrative plumbing, not a strategy. Real studies pass their own
dotted `module:function` path.

If `--output-dir` is omitted, no artifact is written (dry run); the run
still prints the full evidence line set to stdout, including
`result_content_hash`.

## Required evidence line set (printed by the CLI)

```text
dataset_identity=<dataset_id>@<schema_version>:<sha256>
cutoff=<ISO8601 UTC>
universe_identity=<universe_id>@<version>:<sha256>
feature_versions=<JSON object, sorted keys>
parameter_grid_digest=<sha256>
code_sha=<git commit sha, or 'unavailable'>
result_content_hash=<sha256>
parameter_sets_evaluated=<int>
missing_symbols=<list>
unknown_symbols=<list>
result_artifact=<path, or "(not written; pass --output-dir)">
runtime_changes=0
```

## Safety

```text
broker_writes=0
order_submissions=0
production_database_mutation=0
service_timer_changes=0
```

The harness performs no DB access, no broker calls, no order submission,
and no runtime configuration mutation. Promotion of any study result into
production configuration is out of scope and must remain a separate,
explicitly reviewed human decision (per `AGENTS.md` Research Rules and
Strategy Candidate Rules).

## Relationship to the frozen `docs/todo/` design

The earlier frozen TODO describes a larger, five-PR plan scoped tightly to
a Selection-Engine-v2 score-weight study (`ReplayDataset`, `ReplayPoint`,
`ParameterStudyDefinition`, `TemporalSplit`, `EvaluationResult`,
`ReplayRunManifest`, plus a point-in-time Selection v2 adapter and a
versioned forward-return evaluator). Issue #205 narrowed the accepted
scope to one generic, pluggable harness with no strategy-specific
adapter, so `TemporalSplit` and the Selection-v2-specific adapter/evaluator
described there are **not** part of this V1 delivery. A future consumer
(e.g. a Selection Engine v2 weight study) can supply its own
`decision_fn`/`evaluation_fn` pair and its own dataset loader on top of
this harness without any change to `replay_parameter_study_harness_v1.py`.

## Test coverage

`tests/test_replay_parameter_study_harness_v1.py` covers, directly against
the Issue #205 acceptance criteria:

- **determinism**: identical `Dataset`/`UniverseSpec`/`ParameterStudyDefinition`/
  cutoff/decision/evaluation functions produce an identical
  `result_content_hash` and identical canonical JSON across repeated runs;
- **leakage**: a future record that would change the decision output if
  leaked does not change it, because `PointInTimeView` excludes it; a
  contrasting test shows the evaluator legitimately using the same future
  record;
- **missing data**: `FAIL_CLOSED` raises `MissingDataError` rather than
  silently proceeding; `CLASSIFY_AND_CONTINUE` proceeds but explicitly
  records the missing symbols in the result;
- **unsupported parameters**: forbidden safety-parameter names are
  rejected at grid construction; `apply_parameter_overlay()` rejects any
  overlay key outside the declared grid;
- **artifact immutability**: a second write for the same `run_id` raises
  `ArtifactConflictError`.
