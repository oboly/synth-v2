# Paper Advice Severity Calibration V1

## Purpose
Paper Advice Severity Calibration V1 adds display-level severity and substate labels for cockpit review.

It does not change paper advice state, action, selection eligibility, setup eligibility, decision permissions, execution permissions, or order behavior.

## Boundary
- Paper-advice and reporting only.
- Market context only.
- No account-aware allocation logic.
- No broker calls.
- No broker writes.
- No order submission.
- No live orders.
- No `decision_gate` changes.
- No `execution_planner` changes.
- No `executor` changes.
- No `selection_engine` behavior changes.

## Implementation
Helper:

```bash
src/reporting/paper_advice_severity_calibration_v1.py
```

Dashboard integrations:

```bash
src/reporting/run_paper_advice_static_dashboard_v1.py
src/reporting/run_position_rotation_static_dashboard_v1.py
```

The helper derives review severity from already assembled paper-advice rows, fast lifecycle state, target/risk state, price-progress state, and Market Breath Context Bridge diagnostics. It does not write to `paper_advice_observation`.

## Severity Values
`HARD_BLOCK`
: Current market/setup/risk context should remain visibly blocked. Used for missing critical market data, hard market damage, unknown risk, or structural invalidation.

`SOFT_BLOCK`
: Caution context. Not permission, but also not a current hard veto by itself.

`OPPORTUNITY_REVIEW`
: Market context deserves visibility even when selection/setup state is not currently eligible.

`MOMENTUM_EXTENSION_REVIEW`
: Target reached, target overshot, stale target, or refresh-needed extension context. This is not chase permission.

`RECLAIM_REVIEW`
: Reclaim has been confirmed or the old DOWN map was invalidated by reclaim.

`WAIT_FOR_RECLAIM`
: Active DOWN-map context where reclaim is the next review condition.

`WAIT_FOR_PULLBACK`
: Price is extended, late, or past the preferred entry/reaction window.

`CONTEXT_ONLY`
: Informational review context only.

## A+ Stale Avoid
A+ Table 1/2 are legacy external symbolic research context and are no longer actively filled.

When Market Breath Context Bridge marks A+ Table 1 as `STALE` or `VERY_STALE`, `APLUS_AVOID` is downgraded to:

```bash
STALE_APLUS_CONTEXT
```

Stale `APLUS_AVOID` must not be shown as a hard current veto by itself. If the current Market Breath context is constructive or neutral, stale A+ avoid maps to soft caution, reclaim review, or wait-for-reclaim review depending on lifecycle context.

## Market Breath Usage
Market Breath is used only as current market-derived context:
- constructive or neutral context can downgrade stale A+ avoid away from hard-veto presentation
- extension/target lifecycle maps to momentum-extension review
- reclaim lifecycle maps to reclaim review or wait-for-reclaim

Market Breath does not create buy/sell logic, trade permission, order intent, account allocation, or execution planning.

## Dashboard Labels
Dashboards show compact severity/substate labels:
- `STALE_APLUS_CONTEXT`
- `WAIT_FOR_RECLAIM`
- `MOMENTUM_EXTENSION_REVIEW`
- `RECLAIM_REVIEW`
- `WAIT_FOR_PULLBACK`
- `CONTEXT_ONLY`

Display notes intentionally use language such as:
- Review context, not trade advice.
- Soft caution, not permission.
- Stale A+ avoid is soft context, not a hard current veto by itself.
- Review reclaim context before any new map decision.

## Verification
Suggested checks:

```bash
python -m py_compile \
  src/reporting/paper_advice_severity_calibration_v1.py \
  src/reporting/market_breath_context_bridge_v1.py \
  src/reporting/run_paper_advice_static_dashboard_v1.py \
  src/reporting/run_position_rotation_static_dashboard_v1.py

python -m src.reporting.run_position_rotation_static_dashboard_v1 \
  --output-html /tmp/synth-rotation-preview.html \
  --output summary

git diff --check
```

Safety markers:
- `broker_private_calls=0`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `live_orders=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `account_awareness=0` for paper-advice display calibration
