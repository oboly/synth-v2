# Fib Exit Ladder V1 PIT Replay Phase C Provenance v1

Issue: #707  
Runner PR: #717  
Methodology: `FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1`

## Raw evidence

| Field | Value |
|---|---|
| path | `data/research/fib_exit_ladder_v1_pit_replay/pit-replay.json` |
| sha256 | `0eab3c255e56ce49fa3265ab5f4e889e05886b0ee617038a6ce28578d5e80578` |
| venue | `bitvavo` |
| interval | `1d` |
| universe | `LINK,XLM,SOL,XRP,HOT` |
| code_commit_sha | `3d355648dc6bffaa196580740de369b63aed7459` |
| runner mode | `RESEARCH_READ_ONLY` |
| methodology_promotion_grade at capture | `0` |
| promotion_eligible at capture | `false` |

The raw file was produced on the research DB host from exact code commit
`3d355648dc6bffaa196580740de369b63aed7459` after PR #717 merged. The runner
reported `FINISHED ... status=SUCCESS` and the same SHA-256 shown above.

## Candle row counts

| Asset | SELECTION_WINDOW | OOS_WINDOW_1 | OOS_WINDOW_2 |
|---|---:|---:|---:|
| LINK | 365 | 730 | 974 |
| XLM | 365 | 730 | 974 |
| SOL | 151 | 730 | 974 |
| XRP | 365 | 730 | 974 |
| HOT | 365 | 730 | 974 |

## Safety markers captured at runtime

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

The runner opens the existing read-only research DB transaction path only.
No production/profile/runtime mutation is part of this evidence capture.

## Verification boundary

`src/research/verify_fib_exit_ladder_v1_pit_replay_phase_c_v1.py` verifies the
committed raw file hash, frozen scope, runner-selected policy against the full
selection grid, OOS non-retuning, per-asset dispositions, and overall
disposition directly from the raw evidence.

Promotion remains fail-closed. Frozen contract §10 criteria 4 and 7 require
an empirical repeated replay against the same underlying data, so this first
captured run alone does not raise `methodology_promotion_grade` above `0`.
