# PRO Fibo Reference Values — 2026-05-07

Status: research-only
Runtime impact: none
Decision/execution impact: none
Live trading impact: none

## Purpose

This document preserves external PRO Elliott/Fibo reference values from the 2026-05-07 Crypto Masterminds session for research comparison inside Synth.

These values are external references, not verified truth and not direct signals.

## Boundary

Allowed downstream use:

- `data/external/pro_elliott_fibo/`
- research charts
- harvest maps
- fib/exit-profile comparison
- external target annotation
- candidate exit-profile hints

Forbidden downstream use:

- selection override
- decision gate override
- execution planner instruction
- executor/order logic
- live or paper execution trigger

## Asset onboarding note

TAO and NEAR are expected to already exist in the Synth universe/mapping.

TON is expected to be missing and should be added only after the current repo/DB asset and mapping convention is confirmed.

## TON

Structure:

- genesis structure / Telegram distribution bet

Levels:

- continuation close level: 3.68–3.69
- shoulder break: 7.26
- targets:
  - 8.70–9.10
  - 12
  - extended 17

## TAO

Structure:

- high-variance AI coordination / supply compression

Levels:

- buy zone extends to approximately 350
- shoulder line: 700–750
- targets:
  - 1000–1100
  - 1700
  - 2200–2291
  - extended 3500
- watch window: July–August 2026

## NEAR

Structure:

- mature execution platform / linear convexity

Levels:

- current range: 1.20–7.56
- confirmation break: 8.50–8.90
- target:
  - 50–52

## Next safe steps

1. Run the read-only verifier.
2. Confirm TAO and NEAR are present.
3. Confirm TON market availability on Bitvavo.
4. Confirm TON missing locally.
5. Inspect asset/universe/mapping convention before inserting TON.
6. Only then add TON using the existing Synth convention.
