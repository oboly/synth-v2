# TODO — Fibo / Zones

## Status

Parked / open research and architecture lane.

This lane covers Fibonacci target maps, zone context, exit-ladder research, and future display/inspection overlays.

## Sources

```text
docs/research/fib_exit_ladder_v1_findings.md
src/research/run_pro_target_ladder_preview_v1.py
src/research/run_fib_exit_ladder_backtest_v1.py
src/zone/run_zone_engine_v1.py
execution_zone_context
fib_observation_v2
zone_observation_v2
```

## Current interpretation

External PRO Elliott/Fibonacci charts are research maps only:

- bull-run scenario maps
- target box maps
- partial sell ladder inputs
- not direct buy signals
- not direct sell orders

Target zones are harvest zones, not exact sell prices:

```text
start selling before the target box
distribute sell orders through the box
use front-loaded passive ladders
keep a moonbag reserve for blow-off extensions
```

## Existing research result

Initial Fib Exit Ladder V1 found that no single exit ladder fits all assets.

Observed profile buckets:

```text
EXIT_PROFILE_CONTROLLED_3X4X
  examples: LINK, XLM

EXIT_PROFILE_SUPERCYCLE_BALANCED
  examples: SOL, XRP

EXIT_PROFILE_EXPLOSIVE_MOONBAG
  example: HOT
```

Design implication:

```text
research fib/target maps
-> asset exit profile
-> decision_gate checks actual position and permission
-> execution_planner creates passive limit sell ladder
-> executor places and monitors orders
```

No live execution logic should be added from this research directly.

## P2 — Exit-profile research continuation

Status: open / parked.

Tasks:

- Extend Fib Exit Ladder tests beyond the initial 2021 window where useful.
- Validate whether asset-profile-aware exit ladders remain stable across broader windows.
- Keep `asset_exit_profile_hint` as metadata only until downstream contracts are explicitly designed.
- Do not hardcode sell behavior into executor or execution planner from research findings.
- Review whether LINK/XLM controlled, SOL/XRP balanced, and HOT moonbag buckets remain valid after more data.

Boundary:

```text
Research only.
Account-agnostic.
No order creation.
No decision/execution writes.
No live/paper trigger.
```

## P2 — Zone context guardrails

Status: open hygiene / architecture guardrail.

Known rule:

Operational `execution_zone_context` must not be polluted by historical/research backfills.

Tasks:

- Keep operational `execution_zone_context` refreshed only by the current operational zone runner path.
- Historical/research zone backfills must target replay/research tables, not operational runtime tables.
- Preserve the contamination guardrail from prior execution-zone recovery work.
- Keep source separation explicit:
  - operational/source DB for live context reads
  - research/backtest schema for historical replay outputs

Operational refresh shape:

```text
python -m src.zone.run_zone_engine_v1 \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --swing-window 5 \
  --write-db \
  --output table
```

Boundary:

```text
No historical backfill writes into operational execution_zone_context.
No strategy shortcut through zone context.
No executor/order behavior in zone research.
```

## P3 — Fibo/zone UI overlays

Status: open / parked behind UI/Webview lane.

Tasks:

- Display fib/zone markers only after the relevant research/runtime tables exist and are explicitly selected as source.
- Make marker DB/source explicit in the UI.
- Avoid mixing operational execution zones with research replay zones in one ambiguous overlay.
- Show zone relation metrics where useful:
  - `ABOVE_ZONE`
  - `INSIDE_ZONE`
  - `BELOW_ZONE`
  - distance to zone
  - distance to target

Boundary:

```text
UI display only.
Read-only queries.
No decision/execution/order/account writes.
```

## P3 — Target-box normalization backlog

Status: backlog.

Tasks:

- Normalize future external target boxes only when there is a concrete validation question.
- Store external target boxes as research labels, not runtime signals.
- Separate target-zone research from execution-zone operational context.
- Avoid using external PRO target boxes as buy signals.

Boundary:

```text
external target map -> research label -> validation -> optional exit-profile metadata
```

Not:

```text
external target map -> direct sell order
external target map -> direct buy signal
```

## Non-goals

- No live trading.
- No broker writes.
- No order submission.
- No direct executor ladder creation.
- No decision_gate bypass.
- No operational table contamination from research backfills.
