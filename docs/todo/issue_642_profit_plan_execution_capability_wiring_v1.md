# Issue #642 Profit Plan execution capability wiring

The read-only adapter now exists at:

`src/reporting/execution_capability_reporting_adapter_v1.py`

The remaining runner hook in `src/reporting/run_manual_short_trader_profit_plan_v1.py` is intentionally tiny:

1. import `fetch_execution_mode_by_symbol` from the adapter;
2. before `apply_execution_capability_overlay`, open a read-only DB connection and call the adapter for `{card.symbol for card in cards}`;
3. on read failure, warn and use `{}` so existing safe/default `AUTOMATED` rendering is preserved;
4. replace the current no-op call
   `apply_execution_capability_overlay(cards, execution_mode_by_symbol={})`
   with the resolved map.

No broker calls, DB writes, planner, executor, or symbol-specific logic belong in this hook.
