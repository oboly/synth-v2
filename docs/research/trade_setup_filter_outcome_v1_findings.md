# Trade Setup Filter Outcome V1 Findings

Status: research-only  
Runtime impact: none  
Decision/execution impact: none  
Live trading: not enabled  

## Active runtime setup evaluated

Current market-only setup filter:

- filter: trade_setup_filter_v1
- version: 1.1
- mode: candidate_weak_set
- current runtime target horizon: 24H

The current setup filter is a broad candidate filter. It is not yet outcome-policy gated by symbol and horizon.

## Main finding

The current 24H setup-filter PASS population is too broad.

Overall 24H result:

- trades: 232
- wins: 86
- losses: 146
- win rate: 37.07%
- average return: -0.6805%

This means the current PASS state alone is not sufficient as a strategy edge.

## Strong 24H candidates

Symbols with sufficient sample size and positive 24H outcome profile:

| Symbol | Trades | Win rate | Avg return | Median return |
|---|---:|---:|---:|---:|
| POL | 20 | 85.00% | 0.9728% | 1.1286% |
| CRV | 8 | 75.00% | 1.6649% | 2.1690% |
| PEPE | 23 | 60.87% | 0.6476% | 0.7905% |
| BTC | 17 | 58.82% | 0.6960% | 0.3958% |

Candidate 24H allowlist:

- POL
- CRV
- PEPE
- BTC

## Horizon-dependent candidates

Several symbols are poor at 24H but strong at longer horizons.

Example:

### INJ

- 24H: negative
- 72H: positive
- 168H: strongly positive

Interpretation:

INJ should not be globally blocked. It should be classified as LONG_HORIZON_ONLY for this setup family unless a separate short-horizon setup proves valid.

## Candidate 24H blocklist

Symbols with sufficient sample size and poor 24H setup-filter outcome:

- MOG
- HYPE
- RENDER
- INJ
- VET
- DOT
- HBAR
- ALGO
- SUI
- FIL
- HOT
- AAVE

Important: this is a 24H-specific blocklist, not a global asset blocklist.

## Weak or insufficient samples

Symbols with too few samples or mixed evidence should not be promoted yet:

- LINK
- DEEP
- WAL
- ADA
- ONDO
- ICP
- TAO
- RLC
- FET

These require more observations before policy promotion.

## Cross-horizon strongest symbols

Best cross-horizon consistency:

- POL
- CRV
- BTC
- PEPE

Secondary / horizon-specific:

- VET
- ALGO
- DOT
- INJ

## Architecture rule

This research must not directly affect:

- decision_gate
- execution_planner
- executor
- broker/order path
- account logic
- live trading

Next correct step:

Build a read-only setup_outcome_policy_v1 preview that classifies latest setup-filter PASS rows by symbol and target horizon.
