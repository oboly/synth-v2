# Sticky Dashboard Identity Target Columns v1

## Purpose

Wide cockpit tables are hard to scan when the symbol, current price, and target context scroll out of view. This cleanup keeps the key identity and target columns visible while preserving existing read-only dashboard behavior.

## Sticky Columns

Shared dashboard CSS now supports:

- `sticky-table`
- `sticky-header`
- `sticky-symbol` / `sticky-col-symbol`
- `sticky-price` / `sticky-col-price`
- `sticky-target` / `sticky-col-target`

The sticky header stays above body rows. Symbol and current price stay on the left. Relevant target stays on the right so the target context remains visible while scanning policy, lifecycle, and recompute columns.

## Changed Pages

- `rotation-preview.html`: retitled to `Portfolio Cockpit` with subtitle `portefeuille / rotatie / huidige holdings`; existing TP/target zone display is now a sticky leg-aware relevant target column.
- `paper-advice.html`: adds a sticky `Relevant target` column derived from the current target zone or next-zone preview.
- `entry-candidates.html`: adds a sticky `Relevant target` column derived from the current target zone or next-zone preview.

## Target Semantics

The target column is display-only and leg-aware:

- UP leg: TP / upside target.
- DOWN leg: downside target/support context.
- Reclaim context: next upside reaction target when next-zone preview provides it.
- Extension context: extension target when next-zone preview provides it.
- Unknown target: `—`.

The dashboards do not invent a target when no zone is present. Distance is shown only when it can be derived from current price and target midpoint.

## Safety Boundary

This is UI/reporting and documentation only.

It does not:

- change market logic
- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- activate `executor`
- call broker APIs
- write broker state
- submit orders
- create live orders
- mutate account state

## TODO Administration

Canonical TODO updates were made in:

- `docs/todo/ui_webview.md`: sticky columns, cockpit information split, and simplified per-coin dashboard direction.
- `docs/todo/market_breath.md`: future `/synth/regime.html` page and Market Breath spelling/breadth usage rules.
- `docs/todo/strategy_candidates.md`: long-term regime classifier, dual-bucket policy, and super-bull/god-candle research follow-ups.
- `docs/todo/README.md`: TODO index status/purpose updates.
