# Paper Candidate Curve Compare V1

## Purpose

`run_paper_candidate_curve_compare_v1.py` compares a staged paper-candidate simulated equity curve against passive benchmark curves such as BTC and ETH buy-and-hold.

This is used to answer whether the paper candidate adds value versus simply holding a major asset during the same window.

## Boundary

Allowed:

```text
read staged paper candidate rows
read research/backtest eval rows
compute simulated strategy equity curve
compute passive benchmark equity curves
write PNG/JSON files to requested output paths
Forbidden:

no database writes
no decision_state writes
no execution_plan writes
no live orders
no account balance mutation
Research-only warning

This tool intentionally uses simulated future returns and forward prices.

It must remain in the research/backtest namespace only.

Default candidate
policy_name: swing_pullback_recovery_v5_24h_tactical
signal_status: PROMOTION_CANDIDATE
hold_hours: 24
target_fraction: 0.03300000
benchmarks: BTC,ETH
Example
python -m src.research.run_paper_candidate_curve_compare_v1 \
  --database synth_bt \
  --batch-id arena_v2_24h_tactical_2021 \
  --account-equity-eur 1000 \
  --target-fraction 0.03300000 \
  --hold-hours 24 \
  --benchmark-symbols BTC,ETH \
  --output-file /tmp/synth_paper_candidate_audit/curve_compare_2021.png \
  --json-output-file /tmp/synth_paper_candidate_audit/curve_compare_2021.json \
  --output table

