# Synth Market-Only Runtime V1 — Deployment Guide

## ⚠ DO NOT INSTALL ON DEV WSL

This guide and these systemd files are for the **24/7 runtime host only** (likely Odroid or equivalent Linux host). The dev WSL instance is code and git only. Do not run any `sudo cp`, `systemctl enable`, or `daemon-reload` commands on the dev machine.

---

## Purpose

Run the Synth 4h market-only chain automatically after each 4h candle closes. The chain collects market data, runs the selection engine, and writes paper advice. It does not place orders, write to any broker API, activate the decision gate, or touch the execution planner or executor.

**Hard boundaries enforced by environment variables in the service unit:**

| Variable | Value |
|---|---|
| `SYNTH_EXECUTION_MODE` | `paper` |
| `SYNTH_LIVE_EXECUTION_PERMISSION` | `NOT_GRANTED` |
| `SYNTH_BROKER_WRITE_PERMISSION` | `NOT_GRANTED` |

No live trading. No broker writes. No order submission. No decision_gate activation. No execution_planner activation. No executor activation.

---

## Files

| File | Purpose |
|---|---|
| `deploy/systemd/synth-chain-4h.service` | oneshot service — runs `scripts/run_chain_4h.sh` |
| `deploy/systemd/synth-chain-4h.timer` | calendar timer — fires at 00:08, 04:08, 08:08, 12:08, 16:08, 20:08 UTC |

Timer fires 8 minutes after each 4h candle close to allow candle ETL to complete. `Persistent=true` ensures a missed fire (host was off) runs on next boot. `RandomizedDelaySec=120` spreads load across a 2-minute jitter window.

---

## Preflight checks — run on target host before installing

Complete every check before proceeding. Do not install if any check fails.

### 1. Confirm you are on the correct host

```bash
hostname
# expected: <runtime hostname, e.g. odroid>
# NOT: dev WSL hostname
```

### 2. Confirm repo exists at expected path

```bash
ls /home/gurk/projects/synth-v2/scripts/run_chain_4h.sh
# must exist
```

### 3. Confirm venv exists and activates cleanly

```bash
source /home/gurk/projects/synth-v2/venv/bin/activate
python --version
deactivate
```

### 4. Confirm .env exists (do not print secrets)

```bash
ls -la /home/gurk/projects/synth-v2/.env
# must exist; do not cat it
```

### 5. Confirm DB connectivity

```bash
cd /home/gurk/projects/synth-v2
source venv/bin/activate
python -c "from src.common.db import get_connection; c = get_connection(); print('DB OK'); c.close()"
```

### 6. Confirm broker write permission is NOT_GRANTED

```bash
grep SYNTH_BROKER_WRITE_PERMISSION /home/gurk/projects/synth-v2/.env
# must be NOT_GRANTED
grep SYNTH_LIVE_EXECUTION_PERMISSION /home/gurk/projects/synth-v2/.env
# must be NOT_GRANTED
```

### 7. Confirm chain runs manually without error

```bash
cd /home/gurk/projects/synth-v2
source venv/bin/activate
bash scripts/run_chain_4h.sh
# Check exit code: echo $?  → 0
# Check output for broker_calls=0, order_submission=0
```

---

## Install — target host only

After all preflight checks pass:

```bash
# Copy unit files
sudo cp /home/gurk/projects/synth-v2/deploy/systemd/synth-chain-4h.service /etc/systemd/system/
sudo cp /home/gurk/projects/synth-v2/deploy/systemd/synth-chain-4h.timer /etc/systemd/system/

# Reload systemd and enable the timer
sudo systemctl daemon-reload
sudo systemctl enable --now synth-chain-4h.timer

# Confirm timer is active
systemctl list-timers 'synth-*'
```

The timer starts immediately. The service will first fire at the next scheduled time (00:08, 04:08, 08:08, 12:08, 16:08, or 20:08 UTC, plus up to 120 s jitter).

---

## Update — after a code change on the runtime host

```bash
cd /home/gurk/projects/synth-v2
git pull --ff-only origin main

# If the .service or .timer file changed:
sudo cp deploy/systemd/synth-chain-4h.service /etc/systemd/system/
sudo cp deploy/systemd/synth-chain-4h.timer /etc/systemd/system/
sudo systemctl daemon-reload
# No need to re-enable; the timer is already enabled.
```

---

## Verification after install

### Timer status

```bash
systemctl list-timers 'synth-*'
# NEXT column shows next scheduled fire
# LAST column shows most recent fire
```

### Service logs (last 100 lines)

```bash
journalctl -u synth-chain-4h.service -n 100 --no-pager
```

### Confirm latest market candle was written

```sql
SELECT MAX(close_ts_utc) FROM obs_market_candle;
-- should be within the last 4h
```

Or via Python:

```bash
cd /home/gurk/projects/synth-v2
source venv/bin/activate
python -c "
from src.common.db import get_connection
conn = get_connection()
with conn.cursor() as cur:
    cur.execute('SELECT MAX(close_ts_utc) FROM obs_market_candle')
    print('latest candle:', cur.fetchone())
conn.close()
"
```

### Confirm latest strategy runtime snapshot was written

```bash
python -c "
from src.common.db import get_connection
conn = get_connection()
with conn.cursor() as cur:
    cur.execute('SELECT MAX(snapshot_ts_utc) FROM strategy_runtime_snapshot')
    print('latest snapshot:', cur.fetchone())
conn.close()
"
```

### Confirm dashboard safety marker

Check the generated paper-advice dashboard HTML or chain log output for:
```
broker_calls=0
order_submission=0
live_orders=0
```

---

## Stop / disable

```bash
sudo systemctl disable --now synth-chain-4h.timer
# The service will no longer fire automatically.
# A running oneshot will complete normally.
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Timer shows no LAST time | `journalctl -u synth-chain-4h.service` for errors |
| `run_chain_4h.sh` exits non-zero | Run manually and inspect output |
| DB connection error | Check `.env` DB credentials and host reachability |
| venv not found | Confirm venv path; recreate if needed |
| Permission denied on script | Check file permissions on `scripts/run_chain_4h.sh` |
| Missing candles after run | Check ETL step in chain log |

---

## Architecture boundary reminder

This service runs only:

```
ETL (market candles)
  -> selection_engine (market-only, account-agnostic)
  -> paper advice output
```

It does **not** run:
- `decision_gate`
- `execution_planner`
- `executor`
- any broker API call
- any live order path

These boundaries are enforced by `SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED` and `SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED` in the service environment.
