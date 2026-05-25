# Watch Symbol Entry V1

## Purpose

`scripts/odroid/watch_symbol_entry_v1.py` is a temporary manual-watch tool for public market data only.

It polls Bitvavo public endpoints for one market and prints simple pullback/readiness states for manual review.

It is not connected to execution.

## Safety

- public market data only
- no broker keys
- no private broker calls
- no broker writes
- no order submission
- no DB writes
- no `decision_gate`
- no `execution_planner`
- no `executor`

Every poll prints:

```text
broker_writes=0 order_submission=0 executor=none
```

## Inputs

Bitvavo public:

- `GET /ticker/price`
- `GET /{market}/candles?interval=15m`
- `GET /{market}/candles?interval=1h`

Optional notifications:

- `ntfy.sh/<topic>`

## States

- `IMPULSE_CONTINUATION`
- `WICK_REJECTION_PULLBACK`
- `SHALLOW_PULLBACK_STRONG`
- `NORMAL_RETEST_ZONE`
- `DEEP_RETEST_ZONE`
- `NO_CLEAN_ENTRY`

The script is generic.
It is not NEAR-only.

## CLI

```bash
python scripts/odroid/watch_symbol_entry_v1.py --help
```

Arguments:

- `--market`, default `NEAR-EUR`
- `--topic`, optional ntfy topic
- `--seconds`, default `60`
- `--once`
- `--notify-on-wait`
- `--cooldown-minutes`, default `10`
- `--base-url`, default `https://api.bitvavo.com/v2`

## Notifications

By default, notifications are sent only for:

- `SHALLOW_PULLBACK_STRONG`
- `NORMAL_RETEST_ZONE`
- `DEEP_RETEST_ZONE`

If `--notify-on-wait` is set, non-entry wait states may also notify.

Notification body includes:

- market
- current price
- 15m state
- 1h state
- shallow/normal/deep zones
- decision key
- `Manual review only. No order was placed.`

## Usage

One-shot smoke:

```bash
python scripts/odroid/watch_symbol_entry_v1.py \
  --once \
  --market NEAR-EUR \
  --topic synth-near-watch-test \
  --notify-on-wait
```

Continuous run:

```bash
python scripts/odroid/watch_symbol_entry_v1.py \
  --market NEAR-EUR \
  --topic synth-near-watch \
  --seconds 60 \
  --cooldown-minutes 10
```

## ntfy

Browser/mobile example:

1. Subscribe to your topic in a browser or ntfy mobile app.
2. Use the same topic in `--topic`.

Example topic:

```text
synth-near-watch
```

## Example

Example use case:

- `NEAR-EUR` manual dip watch

This is manual tooling only.
It must not be connected directly to execution.
