# A+ Table 1 + Table 2 Normalized Schema v1

## Status

Research-only normalized join layer for A+ Table 1 and Table 2 snapshots.

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

Combine validated A+ Table 1 canonical Breathline records and A+ Table 2 harmonic phase overlay records into one normalized research representation.

This layer is intended for later validation against market outcomes.

It is not a trading signal.

## Inputs

Table 1 raw snapshot:

    data/aplus_raw/2026-05-14_1315_table1_canonical_breathline.txt

Parsed by:

    src/breathline/parse_aplus_table1_canonical_v1.py

Table 2 raw snapshot:

    data/aplus_raw/2026-05-14_1256_table2_harmonic_phase_overlay.txt

Parsed by:

    src/breathline/parse_aplus_table2_harmonic_overlay_v1.py

## Timestamp rule

Table 1 and Table 2 timestamps are preserved separately.

They are not merged into a single prediction timestamp.

Fields:

- table1_prediction_ts_utc
- table2_prediction_ts_utc

This matters because Table 1 and Table 2 may be separate A+ query runs.

## Join key

The normalized v1 join key is:

    token

The loader requires both tables to contain the same 40-token set.

Missing or duplicate tokens are rejected upstream by the canonical parsers.

## Normalized fields

Top-level fields:

- schema_version
- source_type
- research_only
- token
- table1_schema_version
- table1_prediction_ts_utc
- table1_phase
- table1_coherence
- table1_field
- table1_geometry
- table1_structural_role
- table1_expansion_quality
- table1_anchor_strength
- table1_strategic_bias
- table1_notes
- table1_bucket
- table2_schema_version
- table2_prediction_ts_utc
- table2_harmonic_phase
- table2_phase_state
- table2_offset_band
- table2_drift_direction
- table2_quality
- table2_extension_risk
- table2_notes
- table2_bucket
- combined_read
- loader
- loader_version

## Derived buckets

Table 1 buckets:

- APLUS_T1_CORE
- APLUS_T1_ANCHOR_CONTEXT
- APLUS_T1_CAUTION
- APLUS_T1_AVOID
- APLUS_T1_OTHER

Table 2 buckets:

- APLUS_T2_CLEAN_0618_CONFIRMED
- APLUS_T2_CLEAN_1000
- APLUS_T2_EXTENSION_HIGH_RISK
- APLUS_T2_DIRTY_HIGH_RISK
- APLUS_T2_FORMING
- APLUS_T2_PRE_0618
- APLUS_T2_RESET
- APLUS_T2_OTHER

Combined reads:

- ALIGNED_CORE_CLEAN
- ALIGNED_RISK
- CONFLICT_T1_SUPPORT_T2_RISK
- CONFLICT_T1_RISK_T2_CLEAN
- NEUTRAL_OR_MIXED

These are research labels only.

## Default behavior

The loader defaults to dry-run behavior.

No DB writes are performed.

A future DB loader may be added only after the normalized shape is stable.

## Correct downstream path

    raw A+ output
    raw local file
    raw validator
    parser
    normalized research representation
    validation/reporting
    optional later research feature proposal

## Forbidden downstream use

This layer must not directly affect:

- selection_engine
- decision_gate
- execution_planner
- executor
- broker/API calls
- paper/live order routing
- buy/sell advice
