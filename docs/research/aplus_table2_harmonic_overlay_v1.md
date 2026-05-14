# A+ Table 2 Harmonic Phase Overlay Parser v1

## Status

Research-only canonical parser for A+ Harmonic Phase Overlay TABLE 2 snapshots.

Scope:

- market-only
- account-agnostic
- no selection_engine changes
- no decision_gate changes
- no execution_planner changes
- no executor/order logic
- no broker calls
- no broker writes
- no order submission
- no paper/live distinction

## Purpose

Parse canonical A+ TABLE 2 harmonic phase overlay snapshots into normalized research artifacts.

This lane measures whether A+ harmonic phase fields add explanatory value when compared with existing market/regime/backtest outcomes.

This parser does not produce buy/sell advice.

## Input

Raw A+ TABLE 2 snapshot text.

Required metadata:

    prediction_ts_utc=YYYY-MM-DDTHH:MM:SSZ

Expected schema:

    TOKEN HARMONIC_PHASE PHASE_STATE OFFSET_BAND DRIFT_DIRECTION QUALITY EXTENSION_RISK NOTES

Markdown pipe tables are also accepted when the columns are the same.

## Allowed values

HARMONIC_PHASE:

    pre_0618
    forming_0618
    confirmed_0618
    forming_0786
    confirmed_0786
    forming_1000
    confirmed_1000
    extension_1272
    late_extension
    reset
    unclear

PHASE_STATE:

    early
    forming
    confirmed
    late
    exhausted
    unclear

OFFSET_BAND:

    -10.5
    -9
    -8
    -7
    -5
    -3
    0
    +3
    +5
    +7
    +9
    +10.5
    unknown

DRIFT_DIRECTION:

    converging
    forward_drift
    backward_drift
    flat
    unstable
    unknown

QUALITY:

    clean
    mixed
    dirty
    unknown

EXTENSION_RISK:

    low
    moderate
    high
    unknown

## Output

Generated research artifacts:

    data/research/aplus_table2_harmonic_overlay_v1/*.jsonl
    data/research/aplus_table2_harmonic_overlay_v1/*.csv

Generated outputs are ignored by git.

## Normalized row fields

Each parsed row contains:

- prediction_ts_utc
- source_type
- table_type
- research_only
- token
- harmonic_phase
- phase_state
- offset_band
- drift_direction
- quality
- extension_risk
- notes
- source_path
- parser
- parser_version

## Correct downstream path

    raw A+ Table 2 snapshot
    normalized research artifact
    validation report
    optional later feature-candidate proposal
    only after repeated validation: possible market-only selection/advice integration design

## Validation questions

Primary questions:

- Does HARMONIC_PHASE improve outcome separation?
- Does OFFSET_BAND correlate with 4h / 24h / 72h returns?
- Does QUALITY clean vs dirty matter?
- Does EXTENSION_RISK high correlate with poor forward returns or high MAE?
- Does Table 2 confirm or weaken regime candidate H2:
  GLOBAL_BTC_MILD_DECLINE x CLASS_STRESS 4h bounce?
- Does Table 1 STRATEGIC_BIAS or COHERENCE add value beyond regime/global_class?

## Boundary

This parser is not a strategy.

Forbidden downstream use:

- direct selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- broker/API call
- live or paper execution trigger
- buy/sell advice

First parse. Then normalize. Then validate. Then decide.
