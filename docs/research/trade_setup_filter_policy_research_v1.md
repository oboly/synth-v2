# Trade Setup Filter Policy Research V1

## Status

Research note for trade_setup_filter policy evolution.

Current operational version:

- `trade_setup_filter_v1:1.1`

Current research candidates:

- `v1.2_sim`: strict ranking alignment
- `v1.3_sim`: strict ranking alignment plus minimum selection score

## Operational v1.1

Change already committed:

- BTC prior overheat is no longer treated as PASS.
- Former `PASS / MARKET_MARKUP_CANDIDATE` is now treated as:
  - `FAIL / BTC_PRIOR_OVERHEAT_ZONE`

Reason:

Backtest/research results showed `MARKET_MARKUP_CANDIDATE` behaved as a toxic overheat condition, not as a valid entry setup.

Observed on bt_run_id `14`:

| State | Reason | Rows 4h | Avg net 4h | Avg gross 4h | Winrate 4h |
|---|---:|---:|---:|---:|---:|
| PASS | RANK_AND_MARKET_CONTEXT_OK | 59 | -0.001324821356 | 0.003675178644 | 0.4068 |
| FAIL | BTC_PRIOR_OVERHEAT_ZONE | 15 | -0.049094234000 | -0.044094234000 | 0.0000 |

## v1.2 simulation

Rule:

```text
PASS only when:
- setup_filter_state = PASS
- setup_filter_reason = RANK_AND_MARKET_CONTEXT_OK
- rotation_bucket = ROTATION_FOLLOWER
- classification_code = CONTINUATION_CANDIDATE
- sleeve_fit_code = SWING_STRUCTURAL~
