# Synth Documentation

## Core Pipeline

selection_engine → decision_gate → execution_planner → executor

- `selection_engine`: market opportunity, account-agnostic
- `decision_gate`: account-aware permission / duplicate / balance checks
- `execution_planner`: plan creation + execution commitment
- `executor`: paper fills, position mutation, execution events

---

## Stateful Paper Pipeline (current)

The current paper runtime can do:

    selection
    → decision
    → execution plan
    → capital reservation
    → executor fill / ack
    → portfolio_position mutation
    → lifecycle invalidation / release
    → dashboard / runtime loop

This means Synth now has a working stateful paper engine skeleton.

---

## Wat werkt nu

### Entry flow
- selection write
- decision gating
- passive entry planning
- capital reservation
- paper fill
- position open
- sleeve capital moves from `reserved` to `deployed`

### Prepare flow
- prepare plan creation
- prepare acknowledgement
- reservation release on cancel / invalidation

### Exit flow
- explicit exit planning
- automatic TP/SL exit policy
- paper close fill
- realized pnl booking
- sleeve capital moves from `deployed` back to `available`

### Runtime / operations
- paper cycle runner
- paper dashboard
- live paper loop on closed 1h candles
- runtime persistence via `runtime_state`
- entry cooldown after close

---

## Core Docs

Located in `docs/core/`

- `decision_gate_v1.md`
- `execution_planner_v1.md`
- `capital_reservation_v1.md`
- `executor_v1.md`
- `exit_policy_v1.md`
- `entry_cooldown_v1.md`
- `live_paper_loop_v1.md`
- `paper_dashboard_v1.md`

---

## Important Runtime Files

Main operators / runners:

- `src/orchestration/run_paper_cycle_v1.py`
- `src/reporting/run_paper_dashboard_v1.py`
- `src/orchestration/run_live_paper_loop_v1.py`

Policy / support:

- `src/policy/exit_policy_v1.py`
- `src/policy/entry_cooldown_v1.py`

Persistence / state:

- `runtime_state`
- `execution_plan`
- `capital_reservation`
- `portfolio_position`
- `execution_event`
- `portfolio_sleeve`

---

## Operational Commands

### Run one paper cycle

    python -m src.orchestration.run_paper_cycle_v1 \
      --account-id 1 \
      --sleeve-code SWING_STRUCTURAL \
      --venue bitvavo \
      --limit 20 \
      --output table

### Show dashboard

    python -m src.reporting.run_paper_dashboard_v1 \
      --account-id 1 \
      --sleeve-code SWING_STRUCTURAL \
      --venue bitvavo

### Run live paper loop

    python -m src.orchestration.run_live_paper_loop_v1 \
      --account-id 1 \
      --sleeve-code SWING_STRUCTURAL \
      --venue bitvavo \
      --limit 20 \
      --take-profit-pct 0.020000 \
      --stop-loss-pct 0.010000 \
      --entry-cooldown-candles 2 \
      --poll-seconds 30

---

## Infrastructure

- DB draait remote (Odroid), niet lokaal
- verbinding via `.env`
- UTC timestamps
- geen lokale MariaDB aannemen als source of truth

---

## Principes

- strikte scheiding van verantwoordelijkheden
- selection blijft market-only
- decision blijft account-aware
- planner doet commitment, niet execution
- executor doet state transitions
- explainability > black box
- geen overcommit van capital
- restart-safe live loop behavior

---

## Live Bitvavo execution: what is still missing

Er wordt nu nog geen echte actie op Bitvavo uitgevoerd.

Voor live execution ontbreekt nog minimaal:

- Bitvavo execution adapter (REST/WebSocket integratie)
- canonical `exchange_order` / `order_state` laag
- live executor naast paper executor
- idempotent client order ids
- fill reconciliation terug naar:
  - `execution_event`
  - `portfolio_position`
  - `portfolio_sleeve`
- live safety controls:
  - max notional
  - max active orders
  - kill switch
  - hard mode separation paper/live
- retry / rate-limit / error handling

Belangrijk:
dit hoort als aparte live execution laag gebouwd te worden, niet als plakband op `executor_v1`.

---

## Backtesting database approach

Voor backtests:

- live/paper operational DB mag prima gebruikt worden als **read/source**
- maar liever NIET als **write target** voor backtest-resultaten

Aanbevolen:

- operational schema/DB voor live + paper runtime
- aparte backtest schema/DB voor:
  - bt trades
  - bt positions
  - bt metrics
  - visualizer outputs
  - experiment state

Dus:

- source data: mag uit live database komen
- backtest writes: liever apart

Dat voorkomt vervuiling en verwarring tussen echte paper runtime en backtest resultaten.

---

## Research / next likely areas

- backtest visualizer met buy/sell markers op price graph
- live execution state design
- exit policy uitbreiden
- live loop service packaging
- better reporting / status views
- later: realistic execution microstructure

