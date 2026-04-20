# SYNTH V2 CODING STANDARDS

## 1. CORE PRINCIPLE
The system is built as a **layered pipeline**:

obs → feat → signal → ranking → selection → decision → execution

Each layer:
- reads from upstream tables
- writes only to its own table
- never mixes responsibilities

---

## 2. CANONICAL KEYS (MANDATORY)

All state tables MUST use:

- asset_id        (INT)
- venue           (VARCHAR)
- interval_code   (VARCHAR)
- asof_ts_utc     (DATETIME UTC)

UNIQUE KEY:
(asset_id, venue, interval_code, asof_ts_utc)

### Rules

- asset_id = identity (always use for joins)
- venue = execution context (bitvavo, binance, etc.)
- symbol = display only (NEVER for joins)

---

## 3. TIME HANDLING

- Always UTC
- Always `[start_ts, end_ts)` convention
- Never mix timezone-aware and naive timestamps

---

## 4. ENGINE CONTRACT

Each engine must:

- accept:
  - `--venue`
  - `--interval`
- optionally:
  - `--asset-id`
  - `--dry-run`

### Historical support

If engine does NOT support history:

- create a separate:
  - `run_<engine>_backfill.py`

---

## 5. FILE HEADER STANDARD (MANDATORY)

Each runner must start with:

"""
ENGINE: <name>
MODE: latest-only | historical | hybrid

INPUT:
- <table1>
- <table2>

OUTPUT:
- <table>

CLI:
python -m <module> \
  --venue bitvavo \
  --interval 4h

HISTORICAL:
- supported / use backfill runner

NOTES:
- any critical assumptions
"""

---

## 6. DATABASE RULES

- DB = source of truth
- no logic duplication outside DB + engines
- all writes must be:
  - idempotent
  - UPSERT-based

---

## 7. BACKFILL RULE

Backfill must:

- iterate over snapshots
- never recalc everything blindly
- be restart-safe
- log progress per snapshot

---

## 8. NAMING CONVENTION

Tables:

- obs_*
- feat_*
- signal_*
- ranking_*
- selection_*
- decision_*

Columns:

- *_score → decimal scoring
- *_signal → categorical
- *_state → interpreted state

---

## 9. NO SHORTCUTS RULE

Forbidden:

- joining on symbol
- mixing layers (e.g. signal + ranking logic)
- skipping upstream dependencies

---

## 10. DEVELOPMENT STYLE

- always provide full-file replacements (no patch snippets)
- avoid partial SQL edits
- CLI must be copy-paste runnable
- logs must show:
  - snapshot index
  - timestamp
  - rows written

---

## 11. FUTURE PROOFING

Design must support:

- multi-exchange (venue)
- multi-timeframe (1h, 4h, 1d)
- multi-strategy (sleeves)

---

## 12. PRIORITY RULE

Always prioritize:

1. Data correctness
2. Pipeline completeness
3. Only then strategy tuning

Never optimize strategy on incomplete data.

---

## Encoding & Unicode Standard

The entire Synth system uses a strict UTF-8 standard.

### Database

- All tables must use:
  - CHARSET = utf8mb4
  - COLLATE = utf8mb4_unicode_ci

- Never use:
  - utf8 (incomplete UTF-8)
  - latin1

### Python

- Always assume UTF-8 encoding
- When reading/writing files:

```python
open(path, "r", encoding="utf-8")
open(path, "w", encoding="utf-8")
EOF
