# Trade Setup Fail Reason Diagnostic V1

## Purpose

Explain why fresh paper advice rows show `SETUP FAILED` before changing any setup, policy, selection, decision, execution, or order logic.

This is a read-only diagnostic lane. It inspects the latest paper advice snapshot and related market-only source rows, then maps stored setup-filter reasons back to the guard that produced them.

## Boundary

- Diagnostic/reporting only.
- No strategy logic changes.
- No setup-filter behavior changes.
- No policy changes.
- No selection engine changes.
- No decision gate, execution planner, executor, broker, or order changes.
- No DB schema changes.
- No DB writes.

Safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
selection_engine_changes=0
policy_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## Runner

```bash
python -m src.research.run_trade_setup_fail_reason_diagnostic_v1 \
  --venue bitvavo \
  --interval 4h \
  --limit 80 \
  --output table
```

Focused HYPE run:

```bash
python -m src.research.run_trade_setup_fail_reason_diagnostic_v1 \
  --venue bitvavo \
  --interval 4h \
  --symbol HYPE \
  --output table
```

JSONL output is available with `--output jsonl`.

## Input Tables

The diagnostic reads:

- `paper_advice_observation`
- `trade_setup_filter_observation`
- `trade_setup_policy_preview_observation`
- `selection_state`
- `vw_paper_advice_execution_zone_context_v1`
- `obs_market_candle`

The runner uses `15m` candles only for display lifecycle context. It does not recompute zones and does not write lifecycle state.

## Layer Ownership

`selection_state`:

- produced by `selection_engine_v2`
- market-only candidate classification and rank context

`setup_filter_state`:

- produced by `trade_setup_filter_v1`
- market-only setup guard result
- current stored reason field: `setup_filter_reason`

`policy_decision`:

- produced by trade setup policy preview for setup-filter `PASS` rows
- can be blank when setup did not pass or no matching policy preview row exists

Paper advice labels:

- produced by `paper_advice_policy_v1`
- may still show `WATCH` / `WATCH_ONLY` context even when `setup_filter_state=FAIL`

Lifecycle badge:

- produced by the static dashboard from recent candle path data
- display-only path state, not a setup pass, policy permission, or order signal

## Why SETUP FAILED Can Coexist With WATCH

`WATCH` and `WATCH_ONLY` describe paper navigation context from the latest paper advice map. `SETUP FAILED` is a separate setup-filter guard result. A row can be watch-worthy as context while still failing the setup filter.

For example, HYPE can be:

```text
selection_state=WATCHLIST
advice_state=WATCH
advice_action=WATCH_ONLY
setup_filter_state=FAIL
setup_filter_reason=RANK_OUTSIDE_SWEET_SPOT
```

That means the dashboard is allowed to show HYPE as a watchlist context row, but the setup filter did not consider it a valid setup under the current guard configuration.

## Current Findings

Manual run on the latest available snapshot during this lane:

```text
latest_paper_advice_asof_ts_utc=2026-05-18 05:32:46
row_count=41
setup_pass_count=0
setup_fail_count=40
by_selection_state={"AVOID": 34, "NEUTRAL": 6, "WATCHLIST": 1}
by_advice_state={"WAIT": 40, "WATCH": 1}
by_policy_decision={"": 40, "WATCH_ONLY": 1}
by_fail_primary_reason={"RANK_OUTSIDE_SWEET_SPOT": 1, "SELECTION_STATE_NOT_ELIGIBLE": 39}
```

Interpretation:

- Most rows fail because `selection_state` is not `WATCHLIST`.
- HYPE is the only `WATCHLIST` row in this snapshot and fails because its rank is outside the configured sweet spot.
- This does not prove a bug. It indicates the current setup filter is intentionally narrow relative to the current selection distribution.

## HYPE Focus

Latest observed HYPE diagnostic:

```text
advice_state=WATCH
action=WATCH_ONLY
selection_state=WATCHLIST
setup_filter_state=FAIL
leg_direction=DOWN
entry_zone_low=37.5395
entry_zone_high=38.19499
tp_zone_low=34.713
tp_zone_high=34.762
invalidation_price=40.317
lifecycle_badge=PULLBACK WATCH
fail_primary_reason=RANK_OUTSIDE_SWEET_SPOT
failed_guard_name=rank_sweet_spot
threshold=4..10
observed_value=1
btc_prior_24h=-0.01451735382141
current_zone_asof_ts_utc=2026-05-18 04:00:00
previous_zone_asof_ts_utc=2026-05-18 04:00:00
previous_invalidation_price=40.317
zone_changed_from_previous_snapshot=False
```

HYPE is internally consistent in the current snapshot:

- It is watchlist context.
- It fails setup because priority rank `1` is outside the current configured setup sweet spot `4..10`.
- Its current invalidation was not reset versus the previous paper-advice snapshot inspected by this diagnostic.
- If lifecycle later shows reaction retest or entry touch while setup remains fail, that is not a contradiction; lifecycle is path context and setup filter is a separate guard.

## Reason Detail Sufficiency

Current DB detail is enough to identify the first failing setup-filter guard for known reasons:

- `SELECTION_STATE_NOT_ELIGIBLE`
- `PRIORITY_RANK_MISSING`
- `RANK_OUTSIDE_SWEET_SPOT`
- `BTC_PRIOR_24H_MISSING`
- `MARKET_DAMAGE_RISK`
- `BTC_PRIOR_OVERHEAT_ZONE`
- `ASSET_SUITABILITY_WEAK_SET_CANDIDATE`

Current DB detail is not enough to reconstruct a full guard trace for every row. The setup filter stores a single `setup_filter_reason` and a compact `notes` string, not every guard value and pass/fail result.

If a future row has `setup_filter_state=FAIL` without a known reason, the diagnostic reports:

```text
fail_primary_reason=INSUFFICIENT_REASON_DETAIL
```

## Recommended Next Step

No setup-filter logic change is recommended from this lane alone.

Recommended next step:

1. Keep observing fresh 4h snapshots with this diagnostic.
2. If the same pattern persists, decide whether the current rank sweet spot and required selection state still match the intended paper-monitoring semantics.
3. If deeper auditing is needed, add richer setup-filter reason persistence in a separate reviewed patch.

Do not relax guards or promote runtime behavior from this diagnostic.
