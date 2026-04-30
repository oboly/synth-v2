# Paper Candidate Batch Scoreboard V1

## Purpose

`run_paper_candidate_batch_scoreboard_v1.py` compares staged paper candidate batches using read-only research metrics.

It gives a compact scoreboard across batches before deciding whether a permanent research paper ledger writer is worth freezing.

## Boundary

Allowed:

```text
read staged paper candidate rows
compute simulated PnL per batch
compute fixed-window exposure per batch
rank batches by capacity and simulated PnL
print table or JSON output
```

Forbidden:

```text
no database writes
no decision_state writes
no execution_plan writes
no live orders
no account balance mutation
```

## Example

```bash
python -m src.research.run_paper_candidate_batch_scoreboard_v1 \
  --database synth_bt \
  --table research_paper_candidate_signal \
  --policy-name swing_pullback_recovery_v5_24h_tactical \
  --signal-status PROMOTION_CANDIDATE \
  --account-equity-eur 1000 \
  --target-fraction 0.03300000 \
  --hold-hours 24 \
  --max-sleeve-fraction 0.25 \
  --output table
```

## Rule

This remains research-only. It uses simulated future returns and must not be moved into runtime execution layers.
