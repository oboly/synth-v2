# FFG Research Universe v1

## Purpose

Persistent market-only research universe derived from the FFG "THE Crypto List" source page (saved 2026-06-20).

This is a data-lane change only. It does not change global asset selection, create account plan rows, enable positions, or submit orders.

## Acceptance counts

| Metric | Value |
|---|---|
| Source rows | 109 |
| Canonical symbols | 102 |
| Research universe members | 101 |
| Excluded | 1 (USDT) |

## Tables

| Table | Purpose |
|---|---|
| `ffg_research_universe_member_v1` | Canonical membership, one row per `(universe_key, source_symbol)` |
| `ffg_research_source_pair_v1` | Source exchange pairs, one row per `(universe_key, source_symbol, source_pair)` |
| `ffg_external_signal_snapshot_v1` | Beta flow snapshot keyed by `(source, captured_on, timeframe)`; same-key corrections update in place, `source_confidence=low` |

## Boundary

```
selection_engine = untouched
decision_gate    = untouched
execution_planner = untouched
executor / agents = untouched
asset.is_enabled  = untouched
broker calls      = none
```

The `account_plan_default` column is enforced to `NOT_ENABLED` by a CHECK constraint.
The importer reconciles both canonical members and source pairs to the current seed for that exact `universe_key`; stale rows for other universes are untouched.
The `ffg_external_signal_snapshot_v1` table enforces `source_confidence IN ('low','medium','high')`.
No beta flow field is wired to any decision_gate or execution_planner path. This data is research metadata only and never trading eligibility.

## Bitvavo EUR resolution

Derived at import time from local DB (`obs_venue_ticker_24h`, `obs_market_candle`):

| Status | Condition |
|---|---|
| `RESOLVED` | Symbol in asset table + Bitvavo market data found |
| `UNAVAILABLE_ON_BITVAVO` | Symbol not in asset table, or in asset table but no Bitvavo data |
| `REQUIRES_MANUAL_RESOLUTION` | `identity_status = requires_identity_resolution` or `do_not_import` |
| `PENDING_LOCAL_MARKET_SYNC` | Default; replaced on import |

No alternate exchange mappings are invented or scraped.

## Beta flow snapshot

Stored with:
- `timeframe = UNVERIFIED_BETA`
- `source_confidence = low`
- No downstream gate, score, or selection effect.

Logical snapshot behavior:
- Same `(source, captured_on, timeframe)` on a corrected import updates the existing logical snapshot deterministically.
- Different capture dates or timeframes preserve distinct historical research snapshots.

The reported 10 inflows vs 8 captured is a known source discrepancy documented in the seed notes.

## Migration

`db/migrations/20260620_ffg_research_universe_v1.sql`

## Import command

```bash
python -m src.research.run_ffg_research_universe_import_v1 \
    --seed-file /path/to/ffg_research_universe_seed_v1.json --validate-only

# Dry-run (DB-backed plan, no writes; migrated research tables required):
python -m src.research.run_ffg_research_universe_import_v1 \
    --seed-file /path/to/ffg_research_universe_seed_v1.json --dry-run

# Transactional write:
python -m src.research.run_ffg_research_universe_import_v1 \
    --seed-file /path/to/ffg_research_universe_seed_v1.json --write-db
```

Mode semantics:
- `--validate-only`: seed-only validation, no DB connection, no migration requirement.
- `--dry-run`: resolves local asset/Bitvavo state and shows the member/source-pair/snapshot synchronization plan without writes. Fails clearly with `Migration required` when the research tables are absent.
- `--write-db`: executes the same DB-backed plan transactionally.

## Verification flow

Use these read-only commands:

```bash
python -m src.research.run_ffg_research_universe_import_v1 \
    --seed-file /path/to/ffg_research_universe_seed_v1.json --validate-only

python -m src.research.run_ffg_research_universe_import_v1 \
    --seed-file /path/to/ffg_research_universe_seed_v1.json --dry-run
```

Mode distinction:
- `--validate-only`: validates seed structure and source integrity only; no database connection.
- `--dry-run`: validates the DB-backed import plan and reports proposed reconciliation; no database writes.
- `--write-db`: transactionally applies the reconciliation; not a verification command.

`--write-db` remains the mutating import path and should not be used as post-import verification.

## Non-goals

- Does not add assets to any Short Swing card set
- Does not create `is_core_sensor` flags (that is a separate operational migration per asset)
- Does not establish Bitvavo exchange pairs — resolution is read-only from local market sync
- Does not derive multi-horizon score from the beta snapshot
- FFG return, flow, peak tag, or source pair are source metadata only, not Synth scores or permissions
