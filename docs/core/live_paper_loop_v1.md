# Live Paper Loop v1

## Doel

`run_live_paper_loop_v1.py` laat de paper engine semi-live draaien op gesloten 1h candles.

Het is de operationele runner voor paper trading.

---

## Kernprincipe

De loop draait alleen op:

- nieuwe gesloten `1h` candle

Dus niet continu dezelfde state opnieuw verwerken.

---

## Volgorde per cycle

Per nieuwe candle draait de runner:

1. selection write
2. exit policy
3. entry planner
4. executor
5. lifecycle
6. compacte statuslog

---

## Input / configuratie

Belangrijke parameters:

- `account_id`
- `sleeve_code`
- `venue`
- `take_profit_pct`
- `stop_loss_pct`
- `entry_cooldown_candles`
- `poll_seconds`

---

## Runtime persistence

De runner bewaart voortgang in:

- `runtime_state`

Met key:

- `runner_name`
- `scope_key`

Daarmee onthoudt hij:

- `last_processed_close_ts_utc`

Dus na restart verwerkt hij niet opnieuw dezelfde candle.

---

## Waiting behavior

Tussen candles in logt de runner:

- eerste waiting-melding direct
- daarna periodiek volgens `waiting_log_every_polls`

Dit houdt de terminal bruikbaar zonder logspam.

---

## Compacte cycle-log

Per verwerkte candle logt de runner onder meer:

- `selection`
- `eligible`
- `exit_plans`
- `entry_plans`
- `cooldown_blocked`
- `executor`
- `lifecycle`
- `active_plans`
- `open_positions`
- `reserved`
- `deployed`
- `available`
- `last_event`
- `last_symbol`

---

## Waarom deze laag nuttig is

De live loop maakt van losse modules een bruikbare paper bot.

Hij zorgt voor:

- candle-close discipline
- restart-safe gedrag
- geautomatiseerde entry/exit flow
- compacte operator-feedback

---

## v1 scope

Geïmplementeerd:

- 1h candle-close gating
- runtime persistence
- entry cooldown
- exit policy
- compact cycle logging

Nog niet gedaan:

- multi-timeframe scheduling
- per-asset scheduling
- service/daemon packaging
- external alerting
- live trading
