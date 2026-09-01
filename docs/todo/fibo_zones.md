# TODO — Fibo / Zones

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- P0 production publication/cutover (canonical 4h Fib map writer, MariaDB publication, cockpit render, `/synth/fibo-map.html`) -> already implemented and deployed (merged PRs #171, #173); current live-defect follow-up owned by existing Issue #249 (existing; not duplicated)
- P2 — Exit-profile research continuation, P2 — Leak-free Zone/Fib touch evaluation, P2 — Native map level calibration / signed price bias -> Issue #270
- P2 — Zone context guardrails -> already canonical (duplicates `AGENTS.md` operational-table contamination rule); no Issue required
- P3 — Fibo/zone UI overlays, P3 — Target-box normalization backlog -> Issue #271
- Strategy-promotion design note (research fib/target maps -> asset_exit_profile -> decision_gate -> execution_planner -> executor) -> owned by Issue #657 (canonical architecture contract: `docs/architecture/automatic_exit_profile_promotion_v1.md`); producer implementation remains BLOCKED pending a validated Issue #270 evidence conclusion

Unmigrated executable scope:
- none

## Status

Active P0 repository-ready / activation pending (superseded — the production
cutover this line describes is already implemented and deployed; see GitHub
Issue migration block above and Issue #249 for the current live scope).

The recurring canonical 4h Fibonacci map writer and persisted dashboard
consumer are implemented on the current branch. Merge, DB migration/grant
application, exact-commit deployment, controlled publication/render, and timer
observation remain.

Production slice:

```text
devlap native_short_4h_chain
-> persisted 4h feat_candle + structure_state_engine v1.2 direction
-> directional FibNavigationMap over the same public 4h candle as-of
-> canonical_fib_zone_map publication cohort in MariaDB
-> Odroid MVP cockpit render
-> /synth/fibo-map.html
```

No sector rotation, multi-horizon Fibo, Native SHORT scope promotion, account
permission, decision, planning, execution, broker, or order path is included.
Bullish and bearish maps are direction-consistent; RANGE/UNKNOWN remains
explicitly unavailable rather than inheriting bullish display semantics.

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

## P2 — Leak-free Zone/Fib touch evaluation

Status: open research validation lane.

Source:

```text
docs/status/market_structure_progress.md
```

Tasks:

- Refactor `src/research/run_zone_fib_overlay_eval_v1.py` into a leak-free read-only evaluator.
- Preserve the current simple runner behavior only if it remains useful as a probe.
- Run conservative logic across 2026-03 and 2026-04.
- Compare touched outcomes across:
  - `TREND_UP`
  - `TREND_DOWN`
  - `RANGE`
  - `MID` / `HIGH` / `LOW` volatility buckets
- Only after that decide whether a zone/fib paper-candidate policy is worth designing.

Current recommendation:

```text
Zone/Fib touch evaluation is a possible next core strategy-validation lane.
Paper staging remains paused until a leak-free evaluator confirms broader edge.
```

Boundary:

```text
Read-only research evaluator.
No operational execution_zone_context backfill.
No strategy shortcut.
No paper/live promotion.
No order creation.
```

## P2 — Native map level calibration / signed price bias

Status: observation logged / requires replay and backtest.

Observed example:

```text
date: 2026-07-13
market: RED-EUR
chart interval: 1h
exchange chart current: approximately 0.09834
visible resting limit: 0.09730
Profit Plan current snapshot: 0.09785
invalidated re-entry zone: 0.10238 -> 0.10137
invalidation: below 0.09893
card state: INVALIDATED
map authority: reporting fallback / native map data unavailable
```

Initial user observation:

```text
Entry, target, and invalidation levels sometimes appear slightly too high,
possibly around 1% in some examples.
```

This is a calibration hypothesis, not a confirmed defect. The RED example is not clean proof because the card is already invalidated and its evidence shows fallback/unavailable native-map authority. Possible causes include:

- genuine systematic upward level bias;
- stale or superseded map geometry;
- current-price/reference-timestamp mismatch;
- chart candle versus persisted snapshot timing difference;
- invalidated-map display semantics;
- setup-family or timeframe-specific calibration error;
- volatility/regime-dependent top and bottom placement.

Required research tasks:

- Replay immutable published map levels against later realized price paths without look-ahead leakage.
- Evaluate entry, target, and invalidation separately.
- Compute signed level error, not only absolute error:
  - `(published_level - realized_reference) / realized_reference`;
  - positive values indicate levels placed too high;
  - negative values indicate levels placed too low.
- Define realized references explicitly per level type:
  - entry: first valid pullback/re-entry low or accepted touch band;
  - target: subsequent local high / target touch;
  - invalidation: structural break low, not arbitrary next-candle noise.
- Stratify results by:
  - regime: `TREND_UP`, `TREND_DOWN`, `RANGE`;
  - volatility bucket;
  - setup family;
  - primary/supporting timeframe;
  - asset liquidity and price scale;
  - map age and freshness;
  - current versus terminal/invalidated map state;
  - native authority versus reporting fallback.
- Test whether the error is:
  - a fixed percentage offset;
  - ATR-normalized;
  - proportional to swing size;
  - asymmetric for tops versus bottoms;
  - regime-dependent;
  - only a stale-data or fallback artifact.
- Compare uncorrected geometry with candidate research corrections:
  - fixed percentage shift;
  - ATR-based shift;
  - regime-specific shift;
  - setup/timeframe-specific shift.
- Require out-of-sample improvement before any promotion.
- Preserve original immutable map levels. Any correction must be a separate, versioned research projection; never rewrite historical map geometry.

Minimum outputs:

```text
sample count
median signed error
mean signed error
MAE
error quantiles
entry touch rate
target touch rate
target-before-invalidation rate
false invalidation rate
time-to-touch
breakdown by regime / volatility / setup / timeframe / authority
uncorrected versus corrected out-of-sample comparison
```

Guardrail:

```text
Do not apply an assumed -1% dashboard correction.
Do not tune from isolated screenshots.
Do not mutate selection_engine, decision_gate, execution_planner, or executor behavior.
Research evidence must precede any map-generation calibration change.
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
