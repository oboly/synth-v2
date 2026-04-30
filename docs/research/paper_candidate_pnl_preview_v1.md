# Paper Candidate PnL Preview V1

## Purpose

`run_paper_candidate_pnl_preview_v1.py` provides a read-only diagnostic PnL preview for rows staged in `research_paper_candidate_signal`.

It is used after a strategy candidate has passed the research/paper-candidate bridge and before building a permanent paper simulation ledger.

## Boundary

Allowed:

```text
read staged paper candidate rows
compute deterministic simulated PnL
aggregate by batch and symbol
print table or JSON output
```

Forbidden:

```text
account balance writes
portfolio position writes
execution_plan writes
decision_gate writes
executor calls
broker/exchange actions
live trading permission
```

## Current validated candidate

```text
policy_name: swing_pullback_recovery_v5_24h_tactical
policy_version: arena_v2_bridge_v1
batch_id: arena_v2_24h_tactical_2026
signal_status: PROMOTION_CANDIDATE
sleeve: TACTICAL_PULSE
target_fraction: 0.03300000
diagnostic_account_equity_eur: 1000.00
```

## Latest read-only preview result

```text
trades: 27
symbols: 20
wins: 19
losses: 8
winrate: 0.7037
gross_notional_eur: 891.00
total_sim_pnl_eur: 28.9187
avg_sim_pnl_eur: 1.0711
avg_sim_return: 0.03245645
```

## Interpretation

The tactical 24h candidate has a clean read-only preview path:

```text
arena_v2 result
-> bridge JSONL
-> contract validation
-> stage writer
-> stage inspector
-> decision gate preview
-> execution planner preview
-> PnL preview
```

Live trading permission remains explicitly not granted.

## Example

```bash
python -m src.research.run_paper_candidate_pnl_preview_v1 \
  --database synth_bt \
  --table research_paper_candidate_signal \
  --policy-name swing_pullback_recovery_v5_24h_tactical \
  --batch-id arena_v2_24h_tactical_2026 \
  --signal-status PROMOTION_CANDIDATE \
  --account-equity-eur 1000 \
  --target-fraction 0.03300000 \
  --output table
```
