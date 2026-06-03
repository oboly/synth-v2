# Bitvavo Market Sync V1

## Purpose

`bitvavo_market_sync_v1` syncs the global Bitvavo market universe to the
`asset` and `venue_market` tables. It is a public-API-only runner with no
authentication requirement and no broker write calls.

It does not:

- submit orders
- cancel orders
- write to any broker/exchange
- set `is_enabled=0` on existing assets
- delete markets (marks missing ones as `is_tradeable=0` instead)
- create `decision_gate` permission
- create `execution_planner` intent
- enable `executor`

## Truth model

DB is source of truth. Syncing this runner populates `venue_market` so that
`account_wallet_refresh_v1` can look up venue markets during account asset
discovery.

## Dependency

Requires migration `20260603_multi_account_asset_foundation_v1.sql` to have
been run (creates `venue_market` and `account_asset` tables).

## Files

| File | Role |
|------|------|
| `src/market/run_bitvavo_market_sync_v1.py` | Runner — public API + DB upsert |
| `src/account/account_snapshot_models_v1.py` | Shared dataclasses (`MarketSyncRow`, `MarketSyncResult`) |

## What it upserts

### `asset`

- **INSERT** if symbol not present: dynamically adapts to the current `asset` schema
- Required legacy flags are set conservatively on insert only:
  - `is_enabled=1`
  - `is_tradeable=1`
  - `is_portfolio=0`
  - any other required legacy boolean/tinyint flag with no default → `0`
- **UPDATE**: only repairs `name` if NULL/empty; never changes existing `is_enabled`, `is_tradeable`, or `is_portfolio`
- `is_enabled` is a system-wide ETL pipeline gate; the market sync must not override it

## Migration apply

Do not rely on local `mariadb synth` socket access on a dev laptop.

Repo-connected apply command:

```bash
python - <<'PY'
from pathlib import Path
from src.common.db import get_connection

sql_path = Path("db/migrations/20260603_multi_account_asset_foundation_v1.sql")
sql_text = sql_path.read_text(encoding="utf-8")
statements = []
buffer = []
for line in sql_text.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("--"):
        continue
    buffer.append(line)
    if stripped.endswith(";"):
        statements.append("\n".join(buffer).strip().rstrip(";"))
        buffer = []

conn = get_connection()
try:
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()
finally:
    conn.close()
PY
```

### `venue_market`

- **INSERT** new markets with `is_tradeable` derived from Bitvavo `status == "trading"`
- **UPDATE** existing: `is_tradeable`, `price_precision`, `updated_ts`
- Markets seen in this sync but not in current run → `is_tradeable=0` (never deleted)

## Usage

Dry-run (no DB writes, public prices only):

```bash
python -m src.market.run_bitvavo_market_sync_v1 \
  --venue bitvavo \
  --output summary
```

Write mode:

```bash
python -m src.market.run_bitvavo_market_sync_v1 \
  --venue bitvavo \
  --write-db \
  --output summary
```

Expected summary output:

```
runner=bitvavo_market_sync_v1 version=0.1
venue=bitvavo
total_markets=210
unsupported_quote_filter=48
asset_inserted=3
asset_existing=207
venue_market_inserted=3
venue_market_updated=207
broker_writes=0
order_submission=0
executor=none
```

## Safety markers

```
broker_writes=0
order_submission=0
db_writes=asset+venue_market_upsert_only
executor=none
```
