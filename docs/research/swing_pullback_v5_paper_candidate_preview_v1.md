# Swing Pullback V5 Paper Candidate Preview V1

## Layer

Research / paper-candidate preview.

This runner is not part of production trading.

## Purpose

This preview runner wraps the promoted research candidate:

- policy = swing_pullback_recovery_v5
- sleeve context = SWING_STRUCTURAL
- rotation context = ROTATION_EARLY
- classification = PULLBACK_WATCH
- holding horizon = 24h

It creates deterministic preview candidates from historical replay/eval rows.

## Canonical policy

The preview uses the same market-only rule family as the promoted V5 candidate:

- selection_state = WATCHLIST
- priority_rank between 1 and 10
- btc_prior_24h between -0.030 and 0.000
- rotation_bucket = ROTATION_EARLY
- classification_code = PULLBACK_WATCH
- sleeve_fit_code = SWING_STRUCTURAL
- no hardcoded symbol blocker
- exclude selection_score band 0.50000000 <= score < 0.52000000 only when priority_rank is between 4 and 6

## Preview throttling

The preview adds deterministic market-only throttling:

- max_per_snapshot default = 2
- cooldown_hours default = 24
- hold_hours default = 24
- duplicate symbol in one snapshot is rejected
- symbol cooldown is simulated using replay timestamps

This is still not account-aware.

## Boundary

Allowed:

- read synth_bt replay/eval rows
- apply market-only policy rules
- simulate deterministic candidate throttling
- print candidate previews
- print rejected candidate reasons

Forbidden:

- reading balances
- reading live positions
- reading open orders
- reading execution plans
- writing decision_state
- writing execution_intent
- writing execution_plan
- placing or managing orders

## Architecture status

This file is a research wrapper.

It may later inform a decision_gate-compatible paper-candidate design, but it must not be wired directly into:

- decision_gate
- execution_planner
- executor
- live trading
- account-aware portfolio logic

## Default smoke command

python -m src.research.run_swing_pullback_v5_paper_candidate_preview_v1 --from-ts "2026-03-20 00:00:00" --to-ts "2026-04-28 00:00:00" --top 40

## Current status

RESEARCH_PAPER_CANDIDATE_PREVIEW_ONLY.
