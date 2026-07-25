# Synth Market-Only Runtime V1 — Deployment Guide

## Status and Host Authorization

The `native_short_4h_chain` capability is not currently production-authorized:

```text
candidate_host=UNASSIGNED
selected_host=UNASSIGNED
acceptance_host=UNASSIGNED
acceptance_status=UNASSIGNED
production_runtime_owner=UNASSIGNED
production_authorization_status=UNASSIGNED
runtime_lifecycle=UNASSIGNED
observed_runtime_state=[]
```

The committed `deploy/systemd/synth-chain-4h.service` and `.timer` are
devlap-bound candidate artifacts (`ConditionHost=devlap`, `User=gurk`,
`Group=gurk`, `WorkingDirectory=/home/gurk/projects/synth-v2`). They are not
host-neutral and do not authorize devlap as production owner.

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

---

## Purpose

Run the Synth 4h market-only chain after each 4h candle closes. Separately
authorized public-price and candle capabilities own ingestion. This chain
consumes those persisted inputs, fails closed unless both are fresh, publishes
the canonical Native SHORT runtime state, and then runs the remaining
market-only stages. It does not refresh public prices or candles, render or
transport dashboards, place orders, write to a broker API, activate the
decision gate, or touch the execution planner or executor.

**Hard boundaries enforced by environment variables in the service unit:**

| Variable | Value |
|---|---|
| `SYNTH_EXECUTION_MODE` | `paper` |
| `SYNTH_LIVE_EXECUTION_PERMISSION` | `NOT_GRANTED` |
| `SYNTH_BROKER_WRITE_PERMISSION` | `NOT_GRANTED` |
| `SYNTH_REPO_DIR` | `/home/gurk/projects/synth-v2` |
| `SYNTH_CHAIN_4H_LOCKED` | `0` (inherited bypass state is discarded) |
| `SYNTH_CHAIN_4H_LOCK_FILE` | `/tmp/synth_chain_4h.lock` |
| `SYNTH_WRITER_EXECUTION_MODE` | `PRODUCTION` (still denied while ownership is `UNASSIGNED`) |

No live trading. No broker writes. No order submission. No decision_gate activation. No execution_planner activation. No executor activation.

The unit has no `EnvironmentFile=` directive. Runtime modules load the fixed
working-directory `.env` directly; systemd does not inject its full contents.

---

## Files

| File | Purpose |
|---|---|
| `deploy/systemd/synth-chain-4h.service` | oneshot service — runs `scripts/run_chain_4h.sh` |
| `deploy/systemd/synth-chain-4h.timer` | calendar timer — fires at 00:12, 04:12, 08:12, 12:12, 16:12, 20:12 UTC |
| `scripts/run_native_short_scope_status_chain_once.sh` | locked native SHORT runtime wrapper owned by the 4h chain |
| `src/market_data/run_native_short_scope_status_chain_v1.py` | bounded adapter from persisted `SUPPORTED` scopes to the canonical scope-status orchestrator |

Timer fires 12 minutes after each 4h candle close, after the separately owned
public-price and multi-interval candle writers. `Persistent=true`
ensures a missed fire runs on next boot. `RandomizedDelaySec=120` spreads load
across a 2-minute jitter window and `AccuracySec=1s` fixes timer coalescing.
The timer does not require either writer service; SELECT-only freshness
validators are the fail-closed dependency boundary.

The native SHORT runtime does not add a timer or service. Canonical ownership is:

```text
synth-chain-4h.timer
-> synth-chain-4h.service
-> scripts/run_chain_4h.sh
-> SELECT-only persisted public-price freshness validation
-> SELECT-only expected 4h candle boundary validation
-> scripts/run_native_short_scope_status_chain_once.sh
-> run_native_short_scope_status_materializer
-> native_short_scope_status_v1
-> native_short_map_level_status_v1
-> run_native_short_fib_context_snapshot_v1 --publish
-> remaining 4h chain stages
```

The wrapper uses `/tmp/synth-native-short-scope-status-chain-v1.lock` by
default. Lock contention and materializer failure are fail-fast and therefore
fail the owning 4h chain visibly. Runtime scope defaults to the exact current
`SUPPORTED` rows in `native_short_map_scope_v1` for
`bitvavo/EUR/SHORT/4h/1h`; it does not expand to every enabled asset.

The system service invokes the repository script through non-login
`/bin/bash`, with a fixed working directory and absolute script path. The
script derives its repository root from its own path, discards inherited
repository and lock values, and holds file descriptor 8 on the fixed
`/tmp/synth_chain_4h.lock` path for its full lifetime. A second outer chain
invocation exits with status 75; child stages run only while that outer process
owns the lock.

Production source identity remains strict by default. This chain alone passes
one exact controlled-untracked exception:
`docs/todo/replay_parameter_study_harness_v1.md`. Tracked or staged changes,
any other untracked path, a similar path, or more than that one exact path fail
closed before freshness validation or publication.

Bounded BTC verification remains available without changing scheduler scope:

```bash
bash scripts/run_native_short_scope_status_chain_once.sh \
  --venue bitvavo \
  --symbols BTC \
  --quote-currency EUR \
  --fib-trading-horizon SHORT \
  --primary-interval 4h \
  --supporting-interval 1h
```

The Native SHORT stage is a market-data writer. It emits `STARTED`,
`FINISHED`/`FAILED`, scope, run, row-count, elapsed-time, and safety markers. It
makes no private broker calls and has no decision, execution, order, account,
reporting, dashboard, or remote-transport ownership.

Paper-advice dashboard rendering remains separately owned by the existing
render-only consumer contract in
`docs/ops/systemd/synth-paper-advice-dashboard-render.service`. That downstream
path reads persisted state; the 4h chain neither calls it nor transports its
output.

---

## Preflight Checks

Complete every check before proceeding. Do not install if any check fails.

Run this only after a candidate host has been identified. Replace the host and
commit values with the separately selected candidate facts.

```bash
python -m src.operations.run_host_preflight_v1 \
  --capability native_short_4h_chain \
  --expected-host <candidate-host> \
  --expected-commit <exact-commit> \
  --checkout-path <candidate-checkout> \
  --strict
```

Installed systemd equivalence is a separate mandatory, read-only check:

```bash
python -m src.operations.run_native_short_systemd_equivalence_preflight_v1 \
  --checkout-path <candidate-checkout>
```

It requires the exact repository service/timer fragments, no drop-ins, the
fixed service identity/path/command/environment/lock contract, the exact
cadence and host conditions, disabled/inactive pre-activation state, and
absence of the legacy `synth-4h-market-chain.*` pair. Matching cadence alone
does not make an orphan installed timer canonical.

The current committed unit is devlap-bound, so these manual devlap path checks
are valid only when devlap has explicitly become the selected candidate host.

### 1. Confirm selected candidate host

```bash
hostname
# expected: selected candidate host
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

### 7. Confirm the repository boundary without invoking the chain

```bash
cd /home/gurk/projects/synth-v2
bash -n scripts/run_chain_4h.sh
systemd-analyze verify \
  deploy/systemd/synth-chain-4h.service \
  deploy/systemd/synth-chain-4h.timer
grep -n 'run_persisted_market_.*freshness_v1' scripts/run_chain_4h.sh
python -m src.market_data.native_short_repository_source_identity_v1 \
  --repository-commit "$(git rev-parse --verify HEAD)" \
  --allowed-untracked-path docs/todo/replay_parameter_study_harness_v1.md
```

Do not manually start `synth-chain-4h.service` or invoke `run_chain_4h.sh` to
manufacture operational acceptance. Acceptance requires the ordered state
machine in `docs/ops/writer_capability_host_ownership_contract_v1.md`.

---

## Post-Merge Install and Activation Gate

Do not execute these steps from a repository-only PR. After merge, a separately
authorized rollout may copy unit files only for the selected host. The files
below are devlap-bound examples and are invalid for another host without a
separate selected-host artifact:

```bash
# Copy unit files
sudo cp /home/gurk/projects/synth-v2/deploy/systemd/synth-chain-4h.service /etc/systemd/system/
sudo cp /home/gurk/projects/synth-v2/deploy/systemd/synth-chain-4h.timer /etc/systemd/system/

# Reload systemd; activation remains a separate explicit decision
sudo systemctl daemon-reload
sha256sum deploy/systemd/synth-chain-4h.service /etc/systemd/system/synth-chain-4h.service
sha256sum deploy/systemd/synth-chain-4h.timer /etc/systemd/system/synth-chain-4h.timer
python -m src.operations.run_native_short_systemd_equivalence_preflight_v1 \
  --checkout-path /home/gurk/projects/synth-v2
```

Only after preflight, controlled acceptance, legacy runtime inventory,
old-timer containment, and production authorization may the rollout lane
explicitly authorize `systemctl enable --now synth-chain-4h.timer`. The service
must not be started manually to manufacture evidence.

---

## Update — after a code change on the runtime host

```bash
cd /home/gurk/projects/synth-v2
git pull --ff-only origin main

# If the .service or .timer file changed:
sudo cp deploy/systemd/synth-chain-4h.service /etc/systemd/system/
sudo cp deploy/systemd/synth-chain-4h.timer /etc/systemd/system/
sudo systemctl daemon-reload
# Do not enable the timer during repository deployment. Initial activation is
# controlled by the separate post-merge host-acceptance lane above.
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

Dashboard freshness is verified under its separate reporting owner. Dashboard
render or transport output is not 4h-chain acceptance evidence.

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
| `run_chain_4h.sh` exits non-zero | Inspect the natural service journal and the first failed gate |
| DB connection error | Check `.env` DB credentials and host reachability |
| venv not found | Confirm venv path; recreate if needed |
| Permission denied on script | Check file permissions on `scripts/run_chain_4h.sh` |
| Missing public prices | Check the separate public-price writer timer and its journal |
| Missing candles | Check the separate candle writer timer and its journal |

---

## Architecture boundary reminder

The ownership sequence is:

```
separate public-price writer -> persisted prices
separate candle writer -> persisted candles
synth-chain-4h -> SELECT-only freshness gates
  -> Native SHORT publication
  -> market-only features/signals/selection/advice snapshots
```

It does **not** run:
- public-price refresh
- candle ETL
- reporting or dashboard render
- `ssh`, `scp`, or other remote transport
- account refresh
- `decision_gate`
- `execution_planner`
- `executor`
- any broker API call
- any live order path

These boundaries are enforced by `SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED` and `SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED` in the service environment.
