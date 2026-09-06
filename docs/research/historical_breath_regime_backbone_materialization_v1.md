# Historical Breath / Regime Backbone Materialization V1

Status: #805 materialization and coverage acceptance complete
Scope: research-only, market-only, account-agnostic

## Decision

`DEEP_CONTEXT_BACKBONE_AVAILABLE_FOR_RESEARCH_REPLAY`

The existing candle-driven market-breath replay can materialize a deep historical context backbone without introducing a new regime classifier or new label semantics.

For market-level breadth-dependent fields, the accepted replay uses `breadth_scope=all-enabled`: breadth is computed by the existing `add_breadth_and_scores()` logic over the enabled/tradeable asset universe while only the requested research symbols are emitted as output rows.

The earlier selected-10-asset breadth run was useful preflight evidence only and is not the accepted market-breadth interpretation.

## Accepted replay scope

```text
venue=bitvavo
interval=4h
start=2025-09-01T00:00:00Z
end=2026-09-01T00:00:00Z
output_symbols=BTC,ETH,SOL,ADA,XRP,DOT,LINK,AAVE,NEAR,ARB
asof_timestamps=2,191
output_rows=21,910
breadth_scope=all-enabled
breadth_enabled_assets=433
assets_with_breadth_history=432
```

Source data is canonical historical `obs_market_candle`. The replay uses only observations at or before each as-of timestamp.

## #306 overlap acceptance

Strict identity join:

```text
symbol + interval + asof_ts_utc
context_asof <= exhaustion_asof
max_context_age=4h
```

Observed against the Phase C #306 replay:

```text
exhaustion_rows=20,184
matched_context_rows=20,184
coverage=100.0%
avg_context_age_seconds=0
max_observed_context_age_seconds=0
```

Every #306 output symbol has 100% timestamp coverage.

### Field coverage

```text
market_regime known = 20,180 / 20,184
btc_context known   = 20,180 / 20,184
symbol_regime known = 10,658 / 20,184
breath_phase known  =  2,484 / 20,184
breath_alignment    =  2,484 / 20,184
```

Unknown breath labels remain UNKNOWN. The materialization does not manufacture unsupported phase/alignment states.

### High-score coverage

```text
buyer score >=70: 147 / 147 matched, 147 / 147 market_regime known
seller score >=70: 134 / 134 matched, 134 / 134 market_regime known
```

This removes the Phase D context-coverage blocker for market-regime interaction research.

## Full-universe breadth interaction diagnostic

These results are discovery evidence only. They do not promote thresholds or trading behavior.

### Buyer score >=70

| market_regime | n | avg reversal 1b | avg reversal 3b | avg reversal 6b | median reversal 6b |
|---|---:|---:|---:|---:|---:|
| MIXED | 49 | +0.446% | +0.781% | +0.461% | +0.166% |
| RISK_ON | 47 | +0.206% | -0.131% | +0.077% | +0.322% |
| ALT_STRENGTH | 36 | +0.608% | +0.733% | +1.122% | +2.456% |
| BTC_DAMAGE | 10 | +1.038% | +2.916% | +2.313% | +0.565% |
| RISK_OFF | 5 | -0.498% | -0.568% | +0.119% | -0.058% |

Buyer 70+ remains a plausible reversal hypothesis, but strength is regime-dependent and sample sizes differ materially.

### Seller score >=70

| market_regime | n | avg reversal 1b | avg reversal 3b | avg reversal 6b | median reversal 6b |
|---|---:|---:|---:|---:|---:|
| MIXED | 92 | +0.133% | +0.162% | +0.234% | +0.539% |
| RISK_ON | 19 | -0.024% | -0.152% | +0.631% | -0.058% |
| RISK_OFF | 13 | -1.075% | -2.124% | -3.485% | -3.494% |
| ALT_STRENGTH | 6 | +1.026% | +0.454% | +0.419% | -1.686% |
| BTC_DAMAGE | 4 | -0.429% | +1.051% | -0.511% | -0.385% |

The key discovery is that seller score >=70 is not a universal exhaustion state. In `RISK_OFF`, the same raw score is associated with strong continuation rather than reversal.

Correct interpretation:

```text
raw seller exhaustion score
+ independent market regime context
-> research interaction hypothesis
```

Not:

```text
seller score >=70 -> confirmed reversal
```

## Architecture

The backbone remains market-only evidence:

```text
canonical historical candles
-> existing market-breath feature/classification helpers
-> historical context materialization
-> strict PIT research joins
-> downstream validation
```

It does not grant selection authority, account permission, execution intent, or order authority.

## Remaining validation requirement

The interaction table above was observed on the same historical window used to discover the relationship. Before any candidate-state change or promotion proposal:

1. freeze the side-specific hypotheses;
2. define a chronological discovery/validation/holdout split or separate untouched period;
3. evaluate buyer and seller separately;
4. require minimum cohort sizes and report uncertainty;
5. preserve failed regimes/horizons;
6. only then propose any change to #306 candidate semantics.

No production threshold is accepted by this document.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
selection_engine_change=0
decision_gate_change=0
execution_planner_change=0
executor_change=0
db_writes=0
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
