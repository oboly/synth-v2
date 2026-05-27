# A+ Breathline Analysis Handoff — 2026-05-27

Status: research-only handoff for Hoofdpiet / Synth research.

## Repository State

Branch used:

- `wip/aplus-breathline-integration`

Latest pushed before this handoff:

- `42d8445 Add A+ Table 1 and Table 2 raw parsers`

Latest known A+ intake stack:

- Table 1 prompt + validator + parser
- Table 2 prompt + validator + parser
- Legacy 6-vector lane remains separate

## Important Current Data Issue

Current Synth token collection has 45 tokens:

- AAVE
- ADA
- ALGO
- APT
- BTC
- CC
- CRV
- DEEP
- DOT
- ETH
- FET
- FIL
- FLOKI
- HBAR
- HNT
- HOT
- HYPE
- ICP
- INJ
- IOST
- KITE
- LDO
- LINK
- LTC
- MOG
- NEAR
- NOT
- ONDO
- PEPE
- POL
- QNT
- RED
- RENDER
- RLC
- SOL
- SUI
- SXT
- TAO
- TON
- VET
- WAL
- WLD
- XLM
- XPL
- XRP

The latest A+ 2026-05-27 full Table 1/Table 2 attempts returned only 41 of 45 tokens.

Missing in both latest Table 1 and Table 2:

- APT
- KITE
- SXT
- TON

Therefore the 2026-05-27 outputs must be treated as partial raw research notes, not as complete parser input.

## Raw Files Saved Locally

Raw notes saved under `data/aplus_raw/`:

- `2026-05-27_1413_table1_partial_41_of_45_note.txt`
- `2026-05-27_1413_table2_partial_41_of_45_note.txt`
- `2026-05-27_2149_june_reflection_subset_8_note.txt`

These raw files are local-only by default and not committed unless explicitly decided.

## Breathline Strategy Verdict

Current evidence suggests the Breathline forecaster is the best current research strategy candidate, but not yet a trading system.

Working verdict:

- signal quality: promising
- strategy research priority: high
- live/paper trading readiness: no

Breathline currently works best as:

- phase-context detector
- cluster persistence detector
- rotation / deterioration warning
- shortlist generator

Breathline must not yet be used as:

- standalone buy/sell signal
- exact timing engine
- execution trigger

## Strong Agreement Names

These repeatedly show up as strong across earlier cluster scoreboard and latest A+ posture:

- TAO
- INJ
- RENDER
- QNT
- BTC
- AAVE
- LTC
- LINK

Interpretation:

These are current A+ core continuation research names.

## Secondary / Confirmation Names

These are constructive but require more confirmation:

- ETH
- DEEP
- NEAR
- DOT
- XLM
- FET
- FIL
- HBAR

Interpretation:

These may act as confirmers or support structure rather than primary explosive leaders.

## Unstable / Fib-Explosion-Only Names

These are not clean A+ continuation names, but may still matter if Synth fib/zone/volume confirms:

- MOG
- HYPE
- PEPE
- FLOKI
- CRV
- RLC
- SUI
- RED
- WLD

Interpretation:

These belong in a separate `FIB_EXPLOSION_CANDIDATE` lane, not in `A_PLUS_CORE_CONTINUATION`.

## Weak / Avoid Unless Synth Strongly Disagrees

Latest A+ outputs repeatedly mark the following as weak/reset/exhaustion/avoid:

- ADA
- HOT
- ALGO
- HNT
- ICP
- IOST
- XPL
- CC
- ONDO
- NOT

Important special case:

- NOT was strong in earlier A+ scoreboard but now appears reset / low / avoid.
- Treat NOT as a phase-shift / deterioration candidate, not clean continuation.

## MOG Interpretation

MOG is not supported by latest A+ Breathline.

Latest A+ labels:

- Table 1: reset / low / neutral / distorted / unknown / avoid
- Table 2: reset / unclear / unknown / unstable / unknown

Conclusion:

- MOG is not `A_PLUS_CORE_CONTINUATION`
- MOG can only be considered under `FIB_EXPLOSION_CANDIDATE`
- It requires Synth fib/zone/volume confirmation before serious attention

## RENDER Interpretation

RENDER is one of the strongest aligned names.

Evidence:

- Earlier scoreboard: strong 72h candidate
- Latest Table 1: confirmed / high / expansion / leader / continuation
- June subset: forming/high/expansion/speculative leader/accumulation
- Table 2: confirmed_1000 / clean / low risk

Conclusion:

- RENDER is high-priority research candidate
- Needs Synth fib/zone/volume confirmation for timing

## QNT Interpretation

QNT is strong as a structural name.

Evidence:

- Latest Table 1: confirmed/high/expansion/leader/continuation
- June subset: primary harmonic anchor
- Table 2: confirmed_1000 / clean / low risk
- Earlier scoreboard: persistent, but 72h performance was weaker than TAO/INJ/RENDER

Conclusion:

- QNT is a strong structural candidate
- Do not assume explosive performance without price/volume confirmation

## XRP Conflict

A+ is inconsistent on XRP.

Latest 2026-05-27 partial Table 1:

- XRP = confirmed/high/expansion/leader/continuation

June subset:

- XRP = late/moderate/compression/caution

Conclusion:

- XRP is conflicted
- Do not rank high until Synth structure confirms

## Suggested Research Buckets

### A_PLUS_CORE_CONTINUATION

Candidate if:

- A+ Table 1 strong posture
- A+ Table 2 clean/low risk
- Synth selection/fib/zone agrees

Current names:

- TAO
- INJ
- RENDER
- QNT
- BTC
- AAVE
- LTC
- LINK

### FIB_EXPLOSION_CANDIDATE

Candidate if:

- A+ weak/mixed/unstable
- but Synth fib/zone compression/reclaim/breakout + volume ignition agrees

Current names:

- MOG
- HYPE
- PEPE
- FLOKI
- SUI
- RED
- CRV
- RLC
- WLD

### WATCH_ONLY

Candidate if:

- A+ constructive
- Synth not confirming yet

Current names:

- ETH
- DEEP
- NEAR
- DOT
- XLM
- FET
- FIL
- HBAR

### AVOID_REVIEW

Candidate if:

- A+ weak
- Synth also weak

Current names:

- ADA
- HOT
- ALGO
- HNT
- ICP
- IOST
- XPL
- CC
- ONDO
- NOT

## Match With Synth Architecture

Correct strategy stack:

A+ Breathline shortlist
+ Synth fib/zone geometry
+ volume ignition
+ regime filter
+ later outcome validation

A+ must not directly affect:

- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`
- live/paper order logic

## Recommended Next Build

Build a read-only opportunity report:

- `src/research/run_aplus_fib_opportunity_report_v1.py`

Inputs:

- A+ Table 1 raw/normalized posture
- A+ Table 2 raw/normalized phase/risk
- existing Synth selection state
- fib/zone context
- volume expansion / ignition
- forward return validation

Output buckets:

- `A_PLUS_CORE_CONTINUATION`
- `FIB_EXPLOSION_CANDIDATE`
- `WATCH_ONLY`
- `AVOID_REVIEW`

## Next Data Intake Fix

A+ struggles with 45 tokens and multi-table output.

Recommended new intake workflow:

- split token requests into 3 batches
- ask Table 1 only or Table 2 only
- never ask 3 tables at once

Suggested batches:

Batch A:
AAVE, ADA, ALGO, APT, BTC, CC, CRV, DEEP, DOT, ETH, FET, FIL, FLOKI, HBAR, HNT

Batch B:
HOT, HYPE, ICP, INJ, IOST, KITE, LDO, LINK, LTC, MOG, NEAR, NOT, ONDO, PEPE, POL

Batch C:
QNT, RED, RENDER, RLC, SOL, SUI, SXT, TAO, TON, VET, WAL, WLD, XLM, XPL, XRP

## Handoff Conclusion

Breathline appears to be the strongest current research strategy candidate.

But the correct framing is:

- Breathline = compass / phase context
- Synth fib/zone/volume = structure and timing
- decision/execution remains separate and disabled

The promising edge is not A+ alone.

The promising edge is:

A+ phase shortlist
+ Synth structural confirmation
+ volume ignition
+ regime filter
+ forward-return validation
