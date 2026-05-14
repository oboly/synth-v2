# A+ Table 1 / Table 2 Intake v1

Status: research-only parser/intake layer.

## Purpose

This intake layer normalizes the new A+ outputs:

- Table 1: canonical Breathline snapshot
- Table 2: harmonic phase overlay

These are separate from the legacy simplified 6-vector lane.

## Inputs

Raw files are stored locally under:

- data/aplus_raw/

Raw files are not committed by default.

## Table 1

Parser:

- src/breathline/parse_aplus_table1_canonical_v1.py

Schema version:

- aplus_table1_canonical_v1

Fields:

- prediction_ts_utc
- token
- phase
- coherence
- field
- geometry
- structural_role
- expansion_quality
- anchor_strength
- strategic_bias
- notes

## Table 2

Parser:

- src/breathline/parse_aplus_table2_harmonic_overlay_v1.py

Schema version:

- aplus_table2_harmonic_overlay_v1

Fields:

- prediction_ts_utc
- token
- harmonic_phase
- phase_state
- offset_band
- drift_direction
- quality
- extension_risk
- notes

## Architecture boundary

This is research-only.

It must not affect:

- selection_engine
- decision_gate
- execution_planner
- executor
- live/paper order logic

## Next step

After parser smoke is stable, add a DB-backed normalized research table or JSONL export path.

Do not mix these tables into the legacy 6-vector Breathline lane.
