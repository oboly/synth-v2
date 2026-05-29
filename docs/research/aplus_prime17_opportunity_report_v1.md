# A+ Prime-17 Opportunity Report V1

## Purpose

`run_aplus_prime17_opportunity_report_v1.py` is a read-only research report for
the A+ Prime-17 focus set.

It combines:

- A+ Table 1 posture
- A+ Table 2 harmonic phase / risk
- latest Synth selection context when available
- latest fib / zone context when available
- recent volume / return context when available

It is not:

- execution
- paper trading
- order logic
- selection_engine logic
- decision_gate logic
- execution_planner logic
- executor logic

## Inputs

Required raw files:

- `data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt`
- `data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt`

Existing canonical vocab reused from:

- `src/breathline/parse_aplus_table1_canonical_v1.py`
- `src/breathline/parse_aplus_table2_harmonic_overlay_v1.py`

Prime-17 report tokens:

- `TAO`
- `INJ`
- `RENDER`
- `QNT`
- `BTC`
- `AAVE`
- `LTC`
- `LINK`
- `ETH`
- `NEAR`
- `FET`
- `DOT`
- `XLM`
- `MOG`
- `HYPE`
- `PEPE`
- `SUI`

Optional read-only DB context:

- latest `selection_state`
- latest `execution_zone_context` if the table exists and has usable columns
- recent `obs_market_candle` return / volume context

If DB access or a table is unavailable, the runner does not fail. It renders:

- `selection_state=unavailable`
- `selection_bias=unavailable`
- `selection_score=unavailable`
- `zone_context_summary=unavailable`
- `volume_context_summary=unavailable`

## Output Columns

- `token`
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
- `selection_bias`
- `selection_score`
- `zone_context_summary`
- `volume_context_summary`
- `opportunity_bucket`
- `reason`

## Opportunity Buckets

- `A_PLUS_CORE_CONTINUATION`
- `WATCH_ONLY_NEEDS_SYNTH_CONFIRMATION`
- `FIB_EXPLOSION_CANDIDATE`
- `CAUTION_DETERIORATION`
- `NO_SETUP`

Initial deterministic rules:

`A_PLUS_CORE_CONTINUATION`

- Table 1 constructive:
  - `phase in {forming, confirmed}`
  - `coherence in {high, moderate}`
  - `strategic_bias in {accumulation, continuation}`
- Table 2 not degraded:
  - `quality in {clean, mixed}`
  - `extension_risk in {low, moderate}`
  - not `late_extension`
  - not `reset`
  - not `late`
  - not `exhausted`
- and at least one Synth-side confirmation exists:
  - constructive latest selection context with `selection_state != AVOID`
  - or `zone_valid=yes`
  - or `volume_confirmed=yes`

`zone_valid=no` when:

- `zone_context_summary=unavailable`
- `zone_context_summary` starts with `invalid=`
- `zone_context_summary` contains `invalid=`
- `zone_context_summary` contains `fail=`

`WATCH_ONLY_NEEDS_SYNTH_CONFIRMATION`

- A+ constructive
- harmonic state acceptable
- but Synth confirmation is missing:
  - `selection=no`
  - `zone_valid=no`
  - `volume_confirmed=no`

`FIB_EXPLOSION_CANDIDATE`

- token is in the explicit anomaly set:
  - `MOG`
  - `HYPE`
  - `PEPE`
  - `SUI`
  - `RENDER`
- and A+ / harmonic context is unstable, speculative, or high-risk
- and at least one watch support exists:
  - `zone_valid=yes`
  - or `volume_confirmed=yes`

`CAUTION_DETERIORATION`

- late / exhaustion / reset posture
- or `strategic_bias in {caution, avoid}`
- or harmonic `late_extension`
- or harmonic `reset`
- or `phase_state in {late, exhausted}`
- or `quality=dirty`
- or `extension_risk=high`

`NO_SETUP`

- insufficient alignment or insufficient usable information

These rules are explicit research heuristics only. They are not strategy
promotion rules.

## Context Summaries

Selection context:

- latest available `selection_state`
- latest available `selection_bias`
- latest available `selection_score`
- `selection_state=AVOID` is never counted as constructive confirmation

Zone context summary:

- renders latest available entry / tp / invalidation / reclaim / retest fields
- values starting with `invalid=` are explicitly treated as `zone_valid=no`
- if the `execution_zone_context` table or columns are missing, renders
  `unavailable`

Volume context summary:

- recent `1d` default close-to-close return
- latest candle volume ratio versus recent history when available
- latest candle timestamp
- positive return or elevated volume can count as `volume_confirmed=yes`

## Safety

Hard boundaries:

- research-only
- no DB writes
- no broker calls
- no broker writes
- no order logic
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes

The runner performs only defensive reads. Optional context failure degrades to
`unavailable`.

## CLI

Compile:

```bash
python -m py_compile src/research/run_aplus_prime17_opportunity_report_v1.py
```

Help:

```bash
python -m src.research.run_aplus_prime17_opportunity_report_v1 --help
```

Smoke:

```bash
python -m src.research.run_aplus_prime17_opportunity_report_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --output table
```
