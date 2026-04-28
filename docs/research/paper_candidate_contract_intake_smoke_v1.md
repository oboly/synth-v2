# Paper Candidate Contract Intake Smoke V1

## Layer

Research / contract validation smoke.

## Purpose

Validate JSONL exports produced by paper-candidate preview runners before any future adapter consumes them.

This is a boundary safety tool.

## Allowed

- Read JSONL from stdin or file.
- Validate `paper_candidate_contract_v1` rows.
- Report valid and invalid rows.
- Fail loudly on malformed payloads.

## Forbidden

This runner must not read or write:

- account balances
- live positions
- open orders
- execution plans
- broker/order state
- decision state
- execution intent
- portfolio state

## Current producer

- `src/research/run_swing_pullback_v5_paper_candidate_preview_v1.py --output jsonl`

## Architectural status

This does not promote any strategy into production.

It only verifies that the research preview output can cross a clean transport contract boundary.
