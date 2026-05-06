# Fib Exit Ladder V1 Findings

Status: research finding
Scope: Synth v2.5 / v2.6 bull-run exit research
Layer: research only
Live trading permission: not granted

## Purpose

This research lane tests whether long-term bull-run fib/round target ladders can improve profit-taking discipline versus holding through a full cycle.

The external pro Elliott/Fibonacci charts are treated primarily as:

- bull-run scenario maps
- target box maps
- partial sell ladder inputs
- not direct buy signals

## Core interpretation

Pro target zones should not be treated as exact sell prices.

They should be treated as harvest zones:

- start selling before the target box
- distribute sell orders through the box
- use front-loaded limit ladders
- keep a moonbag reserve for blow-off extensions

## Implemented research runners

### `src/research/run_pro_target_ladder_preview_v1.py`

Converts manually extracted pro target boxes into theoretical front-run sell ladders.

Boundary:

- read-only
- account-agnostic
- no order creation
- no decision or execution writes

### `src/research/run_fib_exit_ladder_backtest_v1.py`

Backtests deterministic fib/round exit ladders on historical daily candles.

Boundary:

- read-only
- account-agnostic
- no order creation
- no decision or execution writes

## Tested period

Initial historical test window:

- interval: 1d
- from: 2020-01-01
- to: 2022-01-01
- venue: bitvavo

Assets with usable 2021 data:

- LINK
- SOL
- XRP
- HOT
- XLM

Assets excluded from this first run due insufficient historical candles:

- HBAR
- SUI

## Target families

### PRO_3X4X

Multipliers:

- 2.000
- 2.618
- 3.000
- 4.000
- 4.236

Interpretation:

- controlled bull-run harvest profile
- better for assets that do not require extreme supercycle targets

### SUPERCYCLE

Multipliers:

- 2.618
- 4.236
- 6.854
- 11.090

Interpretation:

- higher-beta bull-run profile
- better for assets that overshoot standard 3x/4x targets

### EXPLOSIVE_SUPERCYCLE

Multipliers:

- 4.236
- 6.854
- 11.090
- 17.944

Interpretation:

- explosive / blow-off profile
- requires large moonbag reserve
- not appropriate for controlled movers

## Key sensitivity result

Best observed configs in this initial 2021 research run:

| Symbol | Best profile | Max ladder sell fraction | Total return with remaining | Hold-to-end return | Notes |
|---|---:|---:|---:|---:|---|
| LINK | PRO_3X4X | 0.80 | 93.6754% | 21.5124% | controlled mover |
| SOL | SUPERCYCLE | 0.80 | 178.3058% | 165.8023% | higher-beta mover |
| XRP | SUPERCYCLE | 0.80 | 207.5549% | 145.9933% | higher-beta mover |
| HOT | EXPLOSIVE_SUPERCYCLE | 0.40 | 563.1368% | 591.5183% | explosive mover; large moonbag needed |
| XLM | PRO_3X4X | 0.80 | 128.7534% | 22.8163% | controlled mover |

## Main finding

There is no single best exit ladder.

The system needs asset-profile-aware exit ladders:

### EXIT_PROFILE_CONTROLLED_3X4X

Candidate assets from first test:

- LINK
- XLM

Suggested behavior:

- use PRO_3X4X target family
- allow larger ladder sell fraction, around 0.80
- smaller moonbag reserve, around 0.20

### EXIT_PROFILE_SUPERCYCLE_BALANCED

Candidate assets from first test:

- SOL
- XRP

Suggested behavior:

- use SUPERCYCLE target family
- allow ladder sell fraction around 0.80
- keep moonbag reserve around 0.20

### EXIT_PROFILE_EXPLOSIVE_MOONBAG

Candidate assets from first test:

- HOT

Suggested behavior:

- use EXPLOSIVE_SUPERCYCLE target family
- sell only a smaller fraction through the ladder, around 0.40
- keep large moonbag reserve, around 0.60

## Important limitation

The current anchor detector is deterministic but still a research approximation.

It was improved by requiring:

- minimum wave1 gain
- minimum wave1 duration
- minimum delay between wave1 high and wave2 low

This reduced micro-wave selection and improved top-capture meaningfully, but it is still not a final Elliott wave engine.

## Design implication

This research supports adding an exit-profile layer later, not hardcoding sell behavior into the executor.

Correct future architecture:

```text
research fib/target maps
↓
asset exit profile
↓
decision_gate checks actual position and permission
↓
execution_planner creates passive limit sell ladder
↓
executor places and monitors orders
No live execution logic should be added from this research directly.
