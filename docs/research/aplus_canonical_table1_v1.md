# A+ Canonical Breathline TABLE 1 Parser v1

## Status

Research-only parser for A+ canonical Breathline TABLE 1 snapshots.

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

## Input

Raw A+ TABLE 1 snapshot text.

Current input:

    data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt

Expected schema:

    TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

The parser reads the first nine fixed fields and stores the remaining text as NOTES.

## Output

Generated research artifacts:

    data/research/aplus_canonical_table1_v1/*.jsonl
    data/research/aplus_canonical_table1_v1/*.csv

Generated outputs are ignored by git.

## Semantics

This is external symbolic A+ data.

It is not market-derived.

It is not a trade signal.

It is not order logic.

The correct downstream path is:

    raw A+ snapshot
    normalized research artifact
    validation against existing research rows
    optional later proposal for market-only selection modifier after repeated validation

## Current use

This parser supports canonical A+ TABLE 1 intake.

TABLE 2 harmonic phase overlay remains a separate future parser/research lane.

TABLE 3 old six-vector format remains legacy compatibility only.
