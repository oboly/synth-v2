# Paper Candidate Stage Inspector V1

## Layer

Research / paper-candidate staging inspection.

This tool is read-only.

## Purpose

Inspect rows staged through `research_paper_candidate_signal` after contract validation.

It verifies:

- batch coverage
- policy coverage
- symbol coverage
- sampled staged candidates
- absence of obvious account/execution columns

## Boundary

Allowed:

- read staged research candidates
- summarize validated market-only rows
- act as a preflight before any future adapter

Forbidden:

- account balances
- positions
- orders
- execution plans
- broker actions
- decision writes
- execution writes
- database writes

## Canonical command

```bash
python -m src.research.run_paper_candidate_stage_inspect_v1 \
  --database synth_bt \
  --table research_paper_candidate_signal \
  --signal-status VALIDATED \
  --policy-name swing_pullback_recovery_v5
```

## Architectural note

This is a kennel inspection tool. It must not become a decision gate shortcut.
