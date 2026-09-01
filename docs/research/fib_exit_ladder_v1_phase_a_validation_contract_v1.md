# Fib Exit Ladder V1 — Phase A validation contract (Issue #270 Phase A)

Status: frozen contract, pre-execution
Layer: research only
Live trading permission: not granted
Evidence-gate role: upstream validation input for `docs/architecture/automatic_exit_profile_promotion_v1.md` (#657 Phase B). This document does not itself validate, revise, or reject anything; it fixes the method before any new outcome is read, per the #270 comment requiring exactly one of `VALIDATED` / `REVISED` / `REJECTED` / `INSUFFICIENT_DATA`.

This contract is frozen **before** any Phase A query beyond schema/connectivity checks was run. It must not be edited after validation results are inspected. Any change to bucket definitions, thresholds, or eligibility rules after results are seen invalidates the run and requires a new contract version.

## Provenance of the frozen original logic

Original methodology and code, unchanged, reconstructed from:

```text
src/research/run_fib_exit_ladder_backtest_v1.py     sha256:ffd3b4477f426e2c1bcbb93b59df06d12b5451b0f991344f190319f8efab760d
src/research/run_fib_exit_ladder_scoreboard_v1.py   sha256:07af7776f50716ee3654c61455452ba5de535ce91f3d0d835b35b38138b70ad5
docs/research/fib_exit_ladder_v1_findings.md        sha256:4dcab868ac8a6197cff5dfd1c94bb7c4b9f0fb0fa3ee502f6435141ff3c17b0e
```

Last commit touching the runners before this contract: `93a3d73` (help-text formatting only; the last logic-bearing commit is `a36350b`, "Add fib exit ladder research runners"). Base SHA for this Phase A branch: `c98f2a49e990cf79e9f4477f5241070b215ecd2c` (`origin/main`).

Phase A must call the existing functions in `run_fib_exit_ladder_backtest_v1.py` and `run_fib_exit_ladder_scoreboard_v1.py` unmodified. If a bug is found, it is reported as a finding, not silently patched, and the original (unpatched) run is still the one whose numbers back the disposition.

## 1. Source dataset(s)

- Table: `obs_market_candle` (read-only), columns resolved dynamically via `detect_candle_columns` (`open_price`/`open`, `high_price`/`high`, `low_price`/`low`, `close_price`/`close`).
- Join key: `asset.symbol -> asset.asset_id` (`fetch_asset_id`).
- `venue = "bitvavo"`, `interval_code = "1d"` (original defaults, unchanged).
- Connection: read-only session (`SET SESSION TRANSACTION READ ONLY`, `START TRANSACTION READ ONLY`, explicit `rollback()` on close) as already implemented in `run_fib_exit_ladder_scoreboard_v1.connect_read_only`. No write-capable connection may be opened for Phase A.
- DB credentials are sourced only from `SYNTH_DB_*` / `DB_*` / `MYSQL_*` / `MARIADB_*` environment variables or an explicit `--env-file`; no credential may be hardcoded or committed.

## 2. Eligibility rules (deterministic anchor detector, unchanged)

`find_anchor_set` in `run_fib_exit_ladder_backtest_v1.py`, run with its documented defaults:

```text
pivot_threshold_pct        = 0.25
min_wave1_gain_pct         = 1.00   (wave1 high >= 2x anchor low)
min_wave1_days             = 14
min_wave2_days_after_high  = 3
wave2_min_retrace          = 0.236
wave2_max_retrace          = 0.886
```

An asset is eligible for a window only if this detector returns a non-`None` `AnchorSet` for that window's candle series (`anchor_low -> wave1_high -> wave2_low`, `method="deterministic_low_high_retrace_expansion"`). No alternate anchor-detection method may be substituted. `min(candles) >= 20` remains a hard precondition (`evaluate_symbol`).

## 3. Original training/discovery window

```text
interval: 1d
from:     2020-01-01 00:00:00
to:       2022-01-01 00:00:00
venue:    bitvavo
```

This window is re-run unchanged as the reproduction baseline (§ Validation requirements: "reproduce original logic unchanged"), before any new window is evaluated.

## 4. New validation window(s)

Two out-of-sample windows, chosen to be disjoint from and entirely after the original window, extending evidence to the present:

```text
VALIDATION_WINDOW_1 (extension):     2022-01-01 00:00:00  ->  2024-01-01 00:00:00
VALIDATION_WINDOW_2 (recent/live):   2024-01-01 00:00:00  ->  2026-09-01 00:00:00   (today)
```

Each window is run independently (its own anchor search over only that window's candles — no anchor may be detected using candles outside the window it is scored in, which is also the project's no-look-ahead requirement for this contract). A combined `2020-01-01 -> 2026-09-01` run is permitted only as a descriptive cross-check, never as a substitute for the disjoint per-window runs the disposition is based on.

## 5. Asset universe handling

```text
Original usable (2021):     LINK, SOL, XRP, HOT, XLM
Original excluded (2021):   HBAR, SUI   (insufficient historical candles at that time)
```

Phase A re-attempts all seven original symbols (`LINK,SOL,XRP,HBAR,HOT,SUI,XLM`) in every window, including `HBAR`/`SUI`, since more candle history may now exist. No symbol may be silently dropped: every symbol/window pair must resolve to exactly one of the outcome statuses in § Missing-data handling. No symbol outside this original seven-symbol universe may be added — this validates the existing buckets, it does not discover new ones.

## 6. Setup/anchor logic

Unchanged from § Eligibility rules. Bucket assignment (asset -> exit-profile family) is **not** re-derived per window; it stays pinned to the original mapping so validation measures whether the *original* assignment still holds, not whether some other assignment would score better:

```text
EXIT_PROFILE_CONTROLLED_3X4X      (target_family=PRO_3X4X)              LINK, XLM
EXIT_PROFILE_SUPERCYCLE_BALANCED  (target_family=SUPERCYCLE)            SOL, XRP
EXIT_PROFILE_EXPLOSIVE_MOONBAG    (target_family=EXPLOSIVE_SUPERCYCLE)  HOT
```

`HBAR` and `SUI` have no original bucket assignment; if they now produce a usable anchor, they are reported as unassigned/descriptive only (§ Missing-data handling: `INSUFFICIENT_DATA` at the per-symbol-original-window level, since no 2021 bucket exists for them to validate).

Ladder parameters held at original defaults for every run: `max_ladder_sell_fraction=0.80`, `rungs_per_target=5`, `distribution=front_loaded`, `target_zone_low_pct=0.04`, `target_zone_high_pct=0.04`, `front_run_pct=0.08`, `end_pct_of_zone_high=0.98`. `TARGET_FAMILIES` multiplier/fraction tuples are used exactly as defined in the module (no retuning — see § Non-negotiable constraints).

## 7. Metrics

Per symbol per window, taken directly from `SymbolResult` / scoreboard row, no re-derivation:

```text
status                                         (OK / ASSET_NOT_FOUND / INSUFFICIENT_CANDLES / NO_ANCHOR_SET_FOUND / NO_FUTURE_CANDLES)
sample count                                    = 1 candidate structure per symbol per window (this methodology is single-anchor,
                                                   not a multi-trade sample; § Acceptance thresholds treats cross-window/cross-asset
                                                   agreement, not within-window trade count, as the sample axis)
fill_count / filled_fraction                    (how much of the ladder actually filled)
remaining_fraction
avg_exit_price
realized_return_pct_on_full_position
remaining_return_pct_on_full_position
total_return_pct_with_remaining                 (primary return metric)
hold_return_pct                                 (baseline)
peak_oracle_return_pct                          (upper bound)
top_capture_ratio                               (total_return / peak_oracle_return)
alpha_vs_hold_pct = total_return_pct_with_remaining - hold_return_pct
```

Cross-window stability metrics (computed in the findings report, not new runner code):

```text
bucket_sign_agreement     = alpha_vs_hold_pct has the same sign in >=2 of the 3 windows (original + both validation windows)
bucket_rank_agreement     = the asset's originally-assigned family remains the highest-total_return family among the 3
                             defined families for that asset in each window where an anchor was found
top_capture_stability     = |top_capture_ratio(window) - top_capture_ratio(original)| reported per window, no pass/fail threshold
                             by itself (informational)
```

## 8. Acceptance thresholds

Applied per originally-bucketed asset (`LINK`, `SOL`, `XRP`, `HOT`, `XLM`), across the two validation windows plus the reproduced original window:

```text
VALIDATED for an asset  requires ALL:
  - original window reproduces status=OK with total_return_pct_with_remaining and hold_return_pct
    matching the historical findings doc within rounding (sanity check that logic is unchanged).
  - at least 1 of the 2 validation windows yields status=OK with a detected anchor.
  - in every validation window with status=OK: alpha_vs_hold_pct > 0 (ladder beats hold) AND
    the originally-assigned target family remains the best-total_return family among the 3 families
    for that asset in that window (bucket_rank_agreement holds).

REVISED for an asset  requires:
  - at least 1 validation window yields status=OK, AND
  - bucket_sign_agreement holds (ladder beats hold in at least 2 of the 3 windows including original) but
    bucket_rank_agreement fails in >=1 validation window (a different family scores better), so the
    asset->family mapping itself is not defensible unchanged, though "use a ladder over holding" still is.

REJECTED for an asset  requires:
  - at least 1 validation window yields status=OK, AND
  - alpha_vs_hold_pct <= 0 in every validation window with status=OK (ladder never beats hold
    out of the original window).

INSUFFICIENT_DATA for an asset  requires:
  - both validation windows return a non-OK status (ASSET_NOT_FOUND / INSUFFICIENT_CANDLES /
    NO_ANCHOR_SET_FOUND / NO_FUTURE_CANDLES), i.e. the deterministic detector never finds a
    qualifying structure outside the original window, so the original claim cannot be re-tested
    at all (this is distinct from REJECTED: it is inability to reproduce the methodology, not a
    negative result from reproducing it).
```

The overall Phase A disposition is the least favorable of the five per-asset dispositions, using the ordering `REJECTED < REVISED < VALIDATED` for defensibility and treating any `INSUFFICIENT_DATA` asset as forcing an overall `INSUFFICIENT_DATA` unless the findings report explicitly narrows the claim to the subset of assets that did produce a result (allowed, but the narrowing itself must be stated, not silent).

If Phase A cannot execute the runners against real data at all (no DB access, no equivalent dataset), the disposition is `BLOCKED`, a distinct state from `INSUFFICIENT_DATA` (inability to run vs. the detector legitimately finding nothing).

## 9. Missing-data handling

- A symbol/window pair that raises `ASSET_NOT_FOUND` is reported as such, not treated as `0` return.
- A symbol/window pair with `INSUFFICIENT_CANDLES` (`< 20` candles) or `NO_ANCHOR_SET_FOUND` or `NO_FUTURE_CANDLES` is reported with that exact status string; it never falls back to a synthesized anchor or interpolated candle.
- `HBAR`/`SUI` (no 2021 bucket) are reported descriptively only; they cannot produce `VALIDATED`/`REVISED`/`REJECTED` under this contract because there is no original assignment to validate — at most `INSUFFICIENT_DATA` (no baseline) or a note that new bucket discovery is out of scope (§ Non-negotiable constraints).
- Fail-closed: if the DB is unreachable, or `obs_market_candle` lacks coverage for a required venue/interval/window, Phase A stops and reports `BLOCKED`, never a partial run presented as a full one.

## 10. Deterministic outcome categories

Exactly one of the following is the Phase A conclusion, stated explicitly in the findings report:

```text
VALIDATED           all five originally-bucketed assets meet the VALIDATED bar in § Acceptance thresholds
REVISED              at least one asset meets REVISED and none meet REJECTED or force-level INSUFFICIENT_DATA
REJECTED             at least one asset meets REJECTED
INSUFFICIENT_DATA    the runners execute against real data but the detector/coverage cannot produce
                     an evaluable result for enough of the universe to judge the original claim
BLOCKED              Phase A cannot execute the runners against real historical data at all in this
                     environment (e.g. no DB access, no substitute dataset) — distinct from INSUFFICIENT_DATA
```

## Non-negotiable constraints

- No bucket definition, multiplier, fraction, or threshold in `TARGET_FAMILIES` or the anchor detector may change after any query result is seen. A finding that the current buckets look wrong is reported as `REVISED`/`REJECTED`, not silently retuned.
- No new bucket, family, or asset assignment may be invented to force a usable result.
- No production write path (`automatic_exit_profile_v1`, `selection_engine`, `decision_gate`, `execution_planner`, `executor`) is touched by Phase A.
- No account-aware, balance-aware, or order-aware data may enter this evaluation.
- Phase A produces research artifacts under `docs/research/` and, if a run executes, `data/research/` only.
