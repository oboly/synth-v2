# Signal Matrix Single Asset Replay V1

## Purpose

`signal_matrix_single_asset_replay_v1` defines a research-only single-asset
replay study that should be completed before coding
`signal_matrix_static_dashboard_v1`.

The goal is to inspect one token across multiple timeframes and discover which
primitive signals were actually useful around hindsight buy/sell/rebuy zones.

This is not:

- strategy promotion
- runtime logic
- advice logic
- execution logic

It is a research microscope for understanding:

- which primitive signals mattered
- which timeframes agreed or disagreed
- which conflicts were informative
- which signals should later be visible in the signal matrix

Core rule:

```text
Elke timeframe mag zijn eigen waarheid hebben; het dashboard toont conflicten, het lost ze niet verborgen op.
```

## First Preferred Asset

Preferred first asset:

```text
XLM
```

Reason:

- `XLM` had a `DTCC/Stellar` catalyst dirty squeeze inside broader macro
  caution
- it is a strong candidate for studying:
  - asset-specific catalyst override
  - dirty squeeze detection
  - HTF/LTF conflict display
  - no-MTF vs MTF legacy prior
  - retest-after-spike behavior

Legacy prior:

- Synth v1 leaned `XLM` toward no-MTF / trend behavior

This legacy prior is allowed only as:

- research prior
- replay interpretation aid
- validation prioritization input

It is not allowed as:

- runtime behavior
- hidden dashboard logic
- selection policy
- strategy routing

## Scope

This study is:

- research-only
- market-only
- account-agnostic
- replay-oriented

This study is not:

- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`
- broker integration
- paper/live trading

## Hard Boundaries

```text
No selection_engine changes
No decision_gate changes
No execution_planner changes
No executor changes
No broker calls
No broker writes
No orders
No account-aware logic
No code yet
```

## Required Timeframes

The study must inspect at least:

- `15m`
- `1h`
- `4h`
- `1d`

Interpretation rule:

- each timeframe must be allowed to keep its own truth
- HTF caution must be shown separately
- HTF caution must not silently block LTF bullish signals in the study write-up
- LTF bullish signals must not silently override HTF caution

## Study Method

### 1. Define hindsight/oracle zones

For the chosen replay window, define research-only oracle zones:

- `ideal_buy_zone`
- `ideal_sell_zone`
- `ideal_rebuy_zone`
- `invalidation_zone`
- `catalyst_spike_zone`
- `dirty_squeeze_zone`
- `retest_zone`

These zones are hindsight labels only.

They are used to ask:

```text
what did the primitive signals look like around the zone?
```

Not:

```text
what strategy should have been traded automatically?
```

### 2. Treat oracle zones as research-only

Oracle zones are allowed only inside this research study.

They must not leak into:

- runtime tables
- dashboard runtime logic
- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`

### 3. Inspect primitive signals around each zone

For each oracle zone and each timeframe:

- inspect the primitive signal state before the zone
- inspect it inside the zone
- inspect it after the zone
- record where timeframes agreed
- record where timeframes conflicted
- record whether the conflict itself was useful

### 4. Do not create strategy rules yet

This replay is diagnostic only.

The study must not conclude:

- “therefore buy here”
- “therefore this is the final strategy”
- “therefore HTF should veto LTF”

### 5. Produce a signal usefulness inventory

The replay should end with a primitive signal inventory:

- helpful around `ideal_buy_zone`
- helpful around `ideal_sell_zone`
- helpful around `ideal_rebuy_zone`
- helpful only during dirty squeeze / catalyst windows
- misleading / noisy / late
- timeframe-dependent

## Oracle Labels And Future-Leakage Boundary

Oracle labels are explicitly future-aware.

That means:

- they may be used to mark hindsight zones in this replay
- they may not be used as training labels for runtime logic without an explicit
  replay-safe research design
- they may not be written into operational latest-state tables
- they may not be mixed into market-only runtime signals

Correct use:

```text
oracle zone
-> inspect primitive signals around that zone
-> produce research usefulness inventory
```

Forbidden use:

```text
oracle zone
-> direct strategy rule
-> runtime dashboard hidden veto
-> live action logic
```

## Primitive Signals To Inspect

The study must inspect at least these primitive signals:

- `fibo_position`
- `support_touch`
- `support_hold`
- `resistance_touch`
- `target_touch`
- `bullflag_candidate`
- `impulse_candidate`
- `compression_candidate`
- `failed_breakout`
- `volume_expansion`
- `relative_strength_vs_btc`
- `relative_strength_vs_theme`
- `macro_regime_context`
- `catalyst_active`
- `dirty_squeeze_active`
- `distance_to_target`
- `distance_to_invalidation`

These must stay primitive fields.
Do not collapse them into one hidden verdict in the study.

## Suggested Replay Window

Initial scope:

```text
XLM over 2026 YTD
```

This should include:

- pre-catalyst build
- catalyst squeeze
- dirty squeeze continuation if present
- retest after spike
- rebuy / reaction windows
- later macro caution or cooldown

## Signal Usefulness Questions

For each oracle zone, ask:

### Buy zone questions

- did `support_touch` appear on multiple timeframes?
- did `support_hold` confirm only on LTF or also on HTF?
- did `compression_candidate` appear before the move?
- did `impulse_candidate` appear too late or early?
- did `distance_to_invalidation` stay favorable?

### Sell zone questions

- did `target_touch` appear clearly?
- did `resistance_touch` matter?
- did `distance_to_target` compress meaningfully before local exhaustion?
- did HTF remain constructive while LTF became overextended?

### Rebuy zone questions

- was the retest visible as `support_hold` or reclaim?
- did `failed_breakout` help identify a bad chase?
- did `compression_candidate` or `bullflag_candidate` reappear?
- did LTF recover while HTF stayed cautious?

### Dirty squeeze / catalyst questions

- did `catalyst_active` align with `dirty_squeeze_active`?
- did the squeeze override otherwise weak macro context?
- which signals stayed useful and which became noisy?
- did no-MTF/trend behavior dominate over MTF interpretation here?

## Output Tables

The replay design should produce explicit research tables later.

### Table 1 — Oracle Zone Registry

Columns:

- `symbol`
- `zone_name`
- `zone_start_ts_utc`
- `zone_end_ts_utc`
- `zone_type`
- `notes`

### Table 2 — Primitive Signal Snapshot Inventory

One row per:

```text
symbol x oracle_zone x timeframe x observation_window
```

Columns:

- `symbol`
- `zone_name`
- `timeframe`
- `observation_window`
  - `pre_zone`
  - `inside_zone`
  - `post_zone`
- all primitive signal fields
- source timestamps
- missing flags

### Table 3 — Signal Usefulness Inventory

One row per primitive signal:

- `symbol`
- `timeframe`
- `signal_name`
- `zone_type`
- `usefulness_label`
  - `HELPFUL`
  - `HELPFUL_BUT_LATE`
  - `CONFLICT_INFORMATIVE`
  - `NOISY`
  - `IRRELEVANT`
  - `DIRTY_SQUEEZE_ONLY`
- `notes`

### Table 4 — Conflict Inventory

One row per conflict pattern:

- `symbol`
- `zone_name`
- `htf_state`
- `ltf_state`
- `conflict_type`
- `did_conflict_help`
- `notes`

### Table 5 — Replay Summary

Summary per symbol:

- strongest helpful primitive signals
- most useful timeframes
- most informative conflicts
- catalyst-specific overrides
- dirty squeeze markers
- no-MTF / MTF prior observations
- non-promotable unresolved questions

## HTF/LTF Conflict Rules

The replay must preserve conflict structure.

Allowed:

- “1d caution, 4h transition, 1h reclaim, 15m impulse”
- “HTF weak, LTF strong”
- “HTF constructive, LTF failed breakout”

Forbidden:

- hidden “HTF vetoed LTF”
- hidden “LTF overruled HTF”
- single final advice label

The replay should ask:

```text
Was the conflict itself useful?
```

Not:

```text
Which timeframe secretly wins by default?
```

## How This Feeds Signal Matrix Static Dashboard V1

This replay is an upstream design input for:

```text
docs/research/signal_matrix_static_dashboard_v1.md
```

Expected contribution:

- identify which primitive signals deserve matrix rows
- identify which timeframe conflicts deserve explicit conflict labels
- identify which catalyst / dirty squeeze fields must be visible separately
- identify which signals need freshness/source display
- identify which signals are too noisy for primary display
- identify which signals require validation-readiness warnings before any later
  promotion

Correct flow:

```text
single-asset replay
-> primitive signal usefulness inventory
-> matrix row/field selection
-> later multi-asset validation
-> later dashboard implementation
```

## Validation-Before-Promotion Rule

Even if the XLM replay shows useful patterns:

- do not promote them directly into runtime
- do not treat one asset as universal truth
- do not convert hindsight usefulness into strategy logic

The replay is:

```text
asset-specific exploratory evidence
```

Promotion requires later:

- multi-asset replay
- regime segmentation
- timeframe consistency review
- catalyst-specific false-positive review
- sample size review

## Recommended Next Sequence

1. Run the first manual replay design on `XLM` 2026 YTD.
2. Mark oracle zones explicitly.
3. Inventory primitive signals per timeframe around each zone.
4. Record which conflicts were useful.
5. Extract a signal usefulness inventory.
6. Feed the result into `signal_matrix_static_dashboard_v1` field design.
7. Only after that, consider implementation of the static matrix renderer.

## Summary

`signal_matrix_single_asset_replay_v1` is the research microscope that should
precede coding the signal matrix.

It uses `XLM` as the first preferred asset because it concentrates:

- catalyst override behavior
- dirty squeeze behavior
- HTF/LTF conflict behavior
- retest-after-spike behavior
- no-MTF vs MTF legacy prior tension

It must remain:

- research-only
- oracle-aware but leak-contained
- explicit about conflicts
- explicit about primitive signals
- explicit about non-promotion
