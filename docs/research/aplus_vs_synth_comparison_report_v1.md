# A+ vs Synth Comparison Report V1

## Purpose

`run_aplus_vs_synth_comparison_report_v1.py` is a research-only comparison
report for the Prime-17 A+ focus set.

It compares:

- Prime-17 A+ posture from Table 1
- Prime-17 harmonic phase/risk from Table 2
- existing Synth market-only context when available

The goal is diagnostic:

- where A+ and Synth agree
- where A+ is constructive but Synth is not confirming
- where Synth is constructive but A+ is cautionary
- where both sides are cautionary

It is not:

- execution
- paper trading
- order logic
- `selection_engine` logic
- `decision_gate` logic
- `execution_planner` logic
- `executor` logic

## Inputs

Required raw files:

- `data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt`
- `data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt`

Reused existing pieces:

- `src/research/run_aplus_prime17_opportunity_report_v1.py`
- `src/breathline/parse_aplus_table1_canonical_v1.py`
- `src/breathline/parse_aplus_table2_harmonic_overlay_v1.py`

Optional read-only Synth context:

- latest `selection_state`
- latest `trade_setup_filter_observation`
- latest `execution_zone_context`
- latest `paper_advice_observation`
- latest reload selected-event file when present:
  - `data/research/reload_reaction_scalp_parameter_sweep_v1/reload_reaction_scalp_selected_events_v1.jsonl`
- recent `obs_market_candle` volume/return context

If any optional source is unavailable, the runner does not fail.
It renders `unavailable` for that context.

## Output Columns

- `token`
- `aplus_bucket`
- `aplus_phase`
- `aplus_coherence`
- `aplus_field`
- `aplus_role`
- `aplus_bias`
- `harmonic_phase`
- `phase_state`
- `offset_band`
- `drift_direction`
- `quality`
- `extension_risk`
- `selection_state`
- `selection_score`
- `setup_state`
- `setup_reason`
- `zone_context_summary`
- `reload_context_summary`
- `reload_context_role`
- `reload_context_promotable`
- `volume_context_summary`
- `synth_confirmation_strength`
- `synth_bucket`
- `comparison_bucket`
- `reason`

## A+ Side

`aplus_bucket` is reused from the existing Prime-17 opportunity report.

That keeps the comparison report aligned with the existing A+ report surface
instead of inventing a second A+ bucket vocabulary.

For the actual comparison decision, the runner also derives a simpler A+ side
state from Table 1 + Table 2 only:

- constructive
- caution/deterioration

This avoids hiding the A+ side entirely inside Synth confirmation logic.

## Synth Side

The runner builds one explicit `synth_bucket` from available Synth context.

Current deterministic Synth buckets:

- `SYNTH_CONFIRMED_UP`
- `SYNTH_REVIEW_UP`
- `SYNTH_RAW_EDGE_CONTEXT`
- `SYNTH_AVOID_OR_FAIL`
- `SYNTH_UNAVAILABLE`
- `SYNTH_MIXED_WAIT`

Current confirmation-strength states:

- `HARD_CONFIRM`
- `SOFT_CONTEXT`
- `RAW_EDGE_ONLY`
- `NO_CONFIRM`

Current inputs that can support hard Synth confirmation:

- constructive latest `selection_state`
- `trade_setup_filter_observation.setup_filter_state == PASS`
- valid `execution_zone_context` combined with promotable reload context

Current inputs that may support soft Synth context only:

- valid `execution_zone_context`
- recent positive/elevated volume context

Reload-specific rule:

- `RAW_EDGE` reload context is diagnostic only
- non-promotable reload roles must not produce `SYNTH_CONFIRMED_UP` by
  themselves
- current Reload Reaction Scalp V1 verdict is `RESEARCH_ONLY / NOT_PROMOTABLE`
- therefore `RAW_EDGE`, `LOW_MAE`, `APLUS`, and `WICK_TOUCH` reload roles are
  treated as weaker context, not hard confirmation
- `reload_context_promotable=true` is reserved for promotable reload context,
  currently only `ROBUST`

Current inputs that can support Synth-side caution:

- `selection_state == AVOID`
- specific bearish `setup_filter_reason` values such as:
  - `MARKET_DAMAGE_RISK`
  - `MARKET_DAMAGE_CAUTION`
  - `SELECTION_STATE_NOT_ELIGIBLE`
  - `BTC_PRIOR_OVERHEAT_ZONE`
- latest paper advice in `AVOID` / `INVALIDATED` state

These are explicit report heuristics only.
They are not runtime trading rules.

Important guard:

- volume context is supporting context only
- volume alone must not create `HARD_CONFIRM`
- if `selection_state=AVOID`, `setup_state=FAIL`, and zone context is invalid
  or absent, reload raw-edge context may stay visible only as:
  - `SYNTH_REVIEW_UP`
  - or `SYNTH_RAW_EDGE_CONTEXT`
- it must not become `SYNTH_CONFIRMED_UP`

## Comparison Buckets

- `BOTH_AGREE_UP`
- `APLUS_CONSTRUCTIVE_SYNTH_SOFT_CONTEXT`
- `A_PLUS_ONLY_WAIT`
- `APLUS_CONSTRUCTIVE_SYNTH_RAW_CONTEXT`
- `APLUS_CONSTRUCTIVE_SYNTH_BLOCKED`
- `SYNTH_ONLY_REVIEW`
- `BOTH_CAUTION`
- `CONFLICT_SYNTH_BULL_A_PLUS_BEAR`
- `SYNTH_RAW_CONTEXT_A_PLUS_CAUTION`
- `INSUFFICIENT_CONTEXT`

Rules:

`BOTH_AGREE_UP`

- A+ constructive
- `synth_confirmation_strength == HARD_CONFIRM`

`APLUS_CONSTRUCTIVE_SYNTH_SOFT_CONTEXT`

- A+ constructive
- Synth has only `SOFT_CONTEXT`
- this is weaker than hard agreement and must not be grouped into
  `BOTH_AGREE_UP`

`APLUS_CONSTRUCTIVE_SYNTH_RAW_CONTEXT`

- A+ constructive
- Synth only has reload raw-edge context or similarly weak confirmation

`APLUS_CONSTRUCTIVE_SYNTH_BLOCKED`

- A+ constructive
- Synth side is explicitly blocked / avoid / fail

`A_PLUS_ONLY_WAIT`

- A+ constructive
- Synth confirmation missing
- no explicit Synth bear rejection

`SYNTH_ONLY_REVIEW`

- Synth constructive/reviewable
- A+ is not constructive
- A+ is also not in the clear caution/deterioration bucket

`BOTH_CAUTION`

- A+ caution/deterioration
- Synth weak, unavailable, or explicitly cautionary

`CONFLICT_SYNTH_BULL_A_PLUS_BEAR`

- Synth strongly constructive
- A+ is caution/deterioration

`SYNTH_RAW_CONTEXT_A_PLUS_CAUTION`

- Synth has only raw-edge / weak context
- A+ is caution/deterioration

`INSUFFICIENT_CONTEXT`

- not enough aligned context to classify the comparison safely

## Safety

Hard boundaries:

- research-only
- read-only
- no DB writes
- no broker calls
- no broker writes
- no order submission
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes

The runner performs only defensive reads.
Optional DB or file context failures degrade to `unavailable`.

## CLI

Compile:

```bash
python -m py_compile src/research/run_aplus_vs_synth_comparison_report_v1.py
```

Help:

```bash
python -m src.research.run_aplus_vs_synth_comparison_report_v1 --help
```

Smoke:

```bash
python -m src.research.run_aplus_vs_synth_comparison_report_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --output table
```
