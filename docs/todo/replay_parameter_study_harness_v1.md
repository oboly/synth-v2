# Replay & Parameter Study Harness v1

## Status

```text
PLANNING — Lane D / strategy-candidate validation sublane
```

## Purpose

Consolidate the smallest reusable, market-only research foundation required for deterministic replay and one bounded parameter study.

This is not a generic optimization platform. It does not own promotion, runtime configuration, live shadowing, execution research, or broker interaction.

The first concrete consumer is a Selection Engine v2 score-weight study. Existing canonical runtime algorithms must be invoked through point-in-time research adapters rather than reimplemented.

## Canonical ownership

| Concern | Owner |
|---|---|
| Market data and features | canonical market-data and feature repositories |
| Replay contracts and provenance | `src/research/replay/` |
| Selection ranking | `src/selection/selection_engine_v2.py` |
| Historical selection input assembly | research-owned point-in-time adapter |
| Outcome semantics | versioned lane-specific evaluator |
| Candidate validation | `docs/todo/strategy_candidates.md` and explicit human review |
| Promotion | outside this harness; never automatic |
| Reporting | immutable research artifacts, read-only |

The existing `src/backtest/` package is not a new foundation. It contains mutable overrides and wall-clock/latest-window behavior that do not satisfy this contract.

## Architectural boundaries

```text
algorithm invocation
!= replay provenance

replay provenance
!= evaluator

evaluator
!= parameter enumeration

parameter enumeration
!= validation

validation
!= promotion

promotion
!= runtime
```

Mandatory rules:

- market-only and account-agnostic;
- no live trading;
- no broker, order, decision-gate, execution-planner, executor, or reporting writes;
- no runtime behavior changes;
- no runtime config mutation;
- no mutable result UPSERT or `DROP/CREATE` result store;
- no optimizer-selected production profile;
- all timestamps are explicit UTC values;
- point-in-time and known-by-T semantics fail closed;
- identical code, dataset, study, evaluator, and parameter identity produce identical result identity.

## V1 scope

V1 contains only:

1. frozen replay and study contracts;
2. immutable run identity and artifact provenance;
3. one point-in-time Selection Engine v2 adapter;
4. one versioned forward-return evaluator;
5. one deterministic Cartesian score-weight grid study;
6. one fixed chronological temporal split;
7. baseline-versus-candidate comparison.

## Explicit non-goals

Do not implement in V1:

- random search;
- optimizer adapters or plugin discovery;
- Optuna, TPE, Bayesian optimization, CMA-ES, NSGA-II, or genetic search;
- rolling walk-forward orchestration;
- runtime event collection or outbox infrastructure;
- online learning, automatic retraining, shadow mode, or drift monitoring;
- automatic promotion or a promotion controller;
- database experiment registry;
- distributed execution;
- execution, fill, fee, slippage, or queue-position optimization;
- account-aware evaluation;
- dashboards or UI.

A future capability requires a separate evidence-based architecture review. V1 interfaces may remain small and explicit; they must not become speculative optimizer frameworks.

## Reuse requirements

Directly reuse canonical pure functions where applicable:

- `src.features.etl_candle_feat.load_candles`
- `src.features.etl_candle_feat.compute_features`
- `src.signal_engine.signal_engine.evaluate_signal_engine`
- `src.selection.selection_engine_v2.rank_candidates`
- `src.selection.selection_engine_v2.load_selection_config`

Research adapters must preserve runtime semantics without importing runtime scheduling, current-time lookup, mutable backfill, or operational persistence.

The current selection replay path must not be treated as canonical until its hardcoded `TRUSTED` quality semantics are replaced by historical truth or fail-closed unavailability.

## Contracts

### `ReplayDataset`

Describes an immutable historical input:

- dataset type and schema version;
- source references and source versions;
- UTC half-open bounds `[start, end)`;
- stable canonical serialization;
- content hash;
- ordered records or immutable artifact reference;
- point-in-time quality markers.

It owns no SQL, feature logic, strategy interpretation, or output persistence.

### `ReplayPoint`

Represents one explicit UTC `as_of_ts` and its known-by-T boundary.

V1 does not introduce a generic clock framework. Each lane supplies an ordered set of replay points and documents inclusivity and warm-up semantics.

### `ParameterStudyDefinition`

Contains:

- study ID and version;
- invocation ID and version;
- baseline parameter identity;
- typed scalar or enum grid dimensions used by the reference study;
- dataset reference and hash;
- evaluator ID and version;
- temporal split;
- invariant and forbidden-parameter declarations.

Safety, freshness, permissions, account, risk, and fail-safe parameters are never tunable.

### `TemporalSplit`

Contains one explicit chronological split:

- train bounds;
- validation bounds;
- test bounds;
- optional documented embargo;
- ordering and non-overlap validation.

Random splitting is prohibited. Rolling walk-forward generation is future work.

### `EvaluationResult`

Contains:

- evaluator ID and version;
- candidate ID;
- split identity;
- sample count;
- versioned metric payload;
- baseline deltas;
- warnings;
- artifact references.

The evaluator does not rank candidates, choose parameters, validate promotion, or mutate runtime state.

### `ReplayRunManifest`

Contains:

- deterministic run identity;
- repository SHA;
- dataset, study, evaluator, and parameter hashes;
- explicit UTC bounds;
- producer versions;
- artifact paths and content hashes;
- safety markers confirming zero broker/account/order/runtime writes.

Timestamps are metadata, not part of content identity.

## Immutable artifact rules

V1 is artifact-first under the canonical research artifact location.

- create-new-only output;
- atomic manifest publication;
- no overwrite of an existing run identity;
- every artifact has a content hash;
- incomplete artifact sets fail closed;
- no V1 DDL;
- existing mutable replay/evaluation tables are inputs or migration sources only, not the canonical V1 result store.

At least one existing modern research producer must migrate to the shared manifest and artifact writer before a second new consumer is added.

## Reference study

### Selection Engine v2 score weights

The only V1 study tunes a small approved set of market-only score weights on a frozen historical `SelectionCandidate` dataset.

The study must:

- invoke `rank_candidates` exactly;
- use a frozen copy of the canonical baseline selection config;
- apply validated in-memory parameter overlays without changing the runtime YAML;
- generate deterministic Cartesian candidates and stable candidate IDs;
- preserve eligibility, quality, missing-data, and symbol tie-break semantics;
- fail closed where historical quality truth is unavailable;
- use one fixed chronological split;
- produce immutable baseline and candidate artifacts.

RSI thresholds, target-room thresholds, momentum confirmation, execution buffers, fill models, and account-aware parameters are not part of this reference study.

## Evaluation semantics

The first evaluator is versioned and selection-oriented. It may include only metrics with explicit horizon and baseline definitions, such as:

- sample count;
- forward return at fixed horizons;
- expectancy;
- win rate;
- adverse excursion or drawdown proxy where supported by the dataset;
- profit factor where mathematically defined;
- buy-and-hold or universe-baseline delta;
- per-split metric deltas and warnings.

Trade count, holding time, fill probability, fees, slippage, and execution metrics are prohibited without a separate simulation contract.

Future outcomes may be used only by the evaluator. They may never leak into candidate construction or algorithm invocation.

## Implementation sequence

### PR 1 — Canonical replay and study contracts

Scope:

- add frozen `ReplayDataset`, `ReplayPoint`, `ParameterStudyDefinition`, `TemporalSplit`, and `EvaluationResult` contracts;
- add canonical serialization and hash tests;
- add architecture documentation;
- register this sublane in `docs/todo/README.md`.

Non-goals:

- loaders;
- strategy invocation;
- evaluation logic;
- manifests and artifact writes;
- database changes;
- parameter enumeration;
- promotion.

Exit criteria:

- strict UTC and bound validation;
- stable serialization and hashes;
- unknown fields rejected;
- no imports from account, decision, execution, broker, runtime, or reporting layers;
- one named Selection Engine v2 reference study.

### PR 2 — Immutable replay provenance

Scope:

- add `ReplayRunManifest`;
- add deterministic run identity;
- add create-new-only artifact writer and manifest validation;
- migrate one existing modern research manifest producer without algorithm changes.

Preferred first migration:

- native SHORT map outcome baseline, subject to parity tests.

Exit criteria:

- identical content gives identical identity;
- source or content changes alter the relevant hash;
- existing output is never overwritten;
- incomplete manifests fail closed;
- one existing consumer uses the shared provenance layer.

### PR 3 — Point-in-time Selection v2 replay adapter

Scope:

- build immutable historical `SelectionCandidate` datasets;
- call `rank_candidates` exactly;
- apply frozen validated config overlays;
- replace hardcoded quality trust with historical truth or fail-closed unavailability.

Non-goals:

- new selection logic;
- runtime changes;
- operational backfill;
- evaluator or parameter choice;
- database result persistence.

Exit criteria:

- runtime fixture parity;
- deterministic ordering;
- future-row exclusion;
- missing-quality rejection;
- config-overlay immutability;
- zero broker/account/order/runtime writes.

### PR 4 — Versioned market-outcome evaluator

Scope:

- extract explicit point-in-time forward-return semantics;
- produce `EvaluationResult` artifacts;
- compare against the fixed baseline.

Non-goals:

- parameter enumeration;
- trade or fill simulation;
- candidate promotion;
- dashboards;
- database tables.

Exit criteria:

- fixed horizon bounds;
- known expected metrics on fixtures;
- future data used only after invocation;
- evaluator cannot choose or promote a candidate.

### PR 5 — Deterministic Selection weight grid study

Scope:

- add stable Cartesian grid enumeration and candidate IDs;
- run the one approved selection-weight study;
- evaluate fixed train, validation, and test periods;
- produce baseline comparison and immutable evidence;
- reconcile this TODO, `strategy_candidates.md`, and `README.md`.

Non-goals:

- random or adaptive search;
- generic optimizer interfaces;
- additional parameter families;
- rolling walk-forward;
- runtime profile changes;
- promotion.

Exit criteria:

- repeat runs produce identical identities, artifacts, and metrics;
- split ordering remains valid;
- immutable output conflicts fail;
- reviewed evidence shows whether the harness adds practical value;
- completion creates no production candidate automatically.

## Acceptance criteria

This TODO is complete only when:

- the contracts are canonical and tested;
- immutable provenance has at least one migrated existing consumer;
- Selection Engine v2 replay matches canonical ranking semantics;
- historical quality handling is truthful or fail-closed;
- one versioned evaluator exists;
- one bounded grid study completes on a fixed chronological split;
- artifacts are immutable and fully lineage-traceable;
- no DB schema or operational result-store dependency was introduced;
- no runtime behavior changed;
- no account, broker, order, decision, planning, execution, or promotion authority was introduced;
- `docs/todo/README.md` and `docs/todo/strategy_candidates.md` are reconciled with the resulting evidence.

## Blockers before implementation

- canonical immutable dataset/version identity must be accepted;
- historical Selection v2 quality status must be available or explicitly fail closed;
- the reference study must freeze the exact score-weight family, evaluator version, horizons, and temporal bounds;
- existing mutable selection replay/evaluation output cannot serve as the V1 result store.

## Future reconsideration triggers

Reconsider a capability only when evidence justifies it:

| Capability | Required trigger |
|---|---|
| Random search | approved Cartesian grid is no longer bounded enough for single-host execution |
| Rolling walk-forward | at least two studies require identical rolling-window and embargo semantics |
| Optimizer adapter | at least two approved optimizer implementations need the same proven protocol |
| TPE/Bayesian/CMA-ES/NSGA-II | deterministic baselines exist and a concrete study demonstrates a measurable compute or quality limitation |
| Experiment database | several canonical studies require shared discovery, retention, and concurrency management |
| Distributed execution | bounded single-host studies exceed an explicit runtime target |
| Shadow/drift/online learning | separately approved runtime-observability architecture with no decision or execution authority |
| Execution parameter research | realistic point-in-time fill, fee, spread, and slippage data plus a separately approved execution-research contract |

Automatic promotion is not a future default. Any production adoption remains a separate reviewed human decision.
