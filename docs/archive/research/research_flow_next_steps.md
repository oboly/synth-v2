# Research Flow - Next Steps

## Current status

The initial reversion-heavy research branch was tested through multiple variants.

Main outcome:
- useful process
- no directly promotable signal yet

This is acceptable and expected.

The main win was establishing a cleaner research workflow.

---

## What is now decided

Research will proceed from known signal families first.

We will not try to rediscover signals from scratch as a primary workflow.

We will use this sequence:

Known Pattern Family
-> State Definition
-> Trigger Definition
-> Forward Return Evaluation
-> Regime Split
-> Keep / Kill / Refine

---

## Immediate next step

Move research code organization toward:

src/research/
    pattern_families/
    trigger_tests/
    evaluation/

This does not require a large refactor immediately, but new research work should begin landing here.

---

## Near-term practical goals

### 1. Minimal backtest pipeline

Get one clean, minimal, end-to-end backtest pipeline working once.

Required characteristics:
- one clear signal family
- one clear forward return definition
- no look-ahead
- recent-window evaluation
- reproducible SQL view + Python runner

### 2. Standardize research views

Use stable columns such as:
- entry_ts_utc
- next_ts_utc
- entry_close_price
- next_close_price
- next_return_4h

### 3. Keep families modular

Do not mix:
- family definition
- trigger logic
- evaluation logic
in one messy script.

---

## Candidate next research families

Pick from these known families:

1. breakout_continuation_4h
2. failed_breakout_4h
3. trend_pullback_continuation_4h
4. failed_breakdown_4h
5. compression_expansion_4h

Prefer families with:
- clear rules
- easy forward evaluation
- limited ambiguity

---

## What not to do

- do not endlessly tweak a family after multiple negative tests
- do not promote a family because top examples look good
- do not hide look-ahead inside confirmation rules
- do not use inconsistent naming across research views
- do not merge research code directly into production logic too early

---

## Claude usage rule

Claude is available and should be used for:
- review
- critique
- bias detection
- code review
- pattern extraction from output

Claude should not be the first driver of strategy generation.

Correct timing:
- after at least one or two internal iterations
- when outputs and hypotheses are already concrete

---

## Success criterion for next phase

The next phase is successful if we can say:

- one family was tested cleanly
- one family was either killed or refined clearly
- one minimal pipeline run is reproducible end-to-end
- architecture is cleaner than before


---

## Research Round Closeout (2026-04)

### Verdicts

#### KILL
- REVERSION_EXTREME_* (alle varianten)
- REVERSION_EXTREME + low participation
- REVERSION_EXTREME + ATR filter
- REVERSION_EXTREME + liquid subset
- REVERSION_EXTREME + T+1/T+2 timing

Reason:
Family bleef negatief na meerdere refinements. Context-only approach werkt niet.

---

#### REFINE / LATER
- TREND_PULLBACK_CONTINUATION_4H_V1

Reason:
Structuur klopt, maar mist trigger. Family is te breed als direct signal.

---

### Key Learnings

- Family ≠ signal  
- Context ≠ entry  
- Trigger layer is essentieel  
- Regime maakt groot verschil  
- Forward returns moeten expliciet en consistent zijn  

---

### Next Pattern Family

- VOLATILITY_COMPRESSION_BREAKOUT_4H_V1

Reason:
- schoon
- duidelijk trigger event
- goed testbaar
- sluit aan op flags / wedges (compression → expansion)

---

### Execution Rule (vanaf nu)

Elke nieuwe test moet expliciet bevatten:

- Family
- State
- Trigger
- Evaluation (next_return_4h)
- Verdict (KEEP / KILL / REFINE)


---

## FUTURE IMPROVEMENT

Move research tracking into database tables:

- research_pattern_run
- research_pattern_observation

Reason:
- querybaar
- vergelijkbaar
- minder afhankelijk van losse docs

Not now:
- eerst stabiele research workflow neerzetten


---

## Failed Breakout Family Update

### KEEP / PRIORITY
- FAILED_BREAKOUT_4H_V1

### Reason
This is the first family in the current research round with clearly usable behavior.

Recent-window result:
- sample count: 389
- avg next_return_4h: -0.020247
- median next_return_4h: -0.018464
- OTHER avg next_return_4h: 0.000170

Interpretation:
- failed upside breakout predicts materially negative next 4h forward return
- this is a bearish post-failure family
- usable first as:
  - avoid-long signal
  - reversal / short-context family
  - risk overlay for breakout-chasing logic

### Current architectural status
family = FAILED_BREAKOUT_4H
state = breakout above recent high
trigger = close back below recent high
evaluation = next_return_4h
verdict = KEEP

### Next actions
- FAILED_BREAKOUT_4H_V2
- test next_return_8h
- split by large-cap vs smaller assets
- test whether this belongs in:
  - avoid-long logic
  - short candidate logic
  - or both

