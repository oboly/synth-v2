# Synth v2.14 Signal Dashboard Strategy Bridge Backlog

## A. Problem Summary

- Old dashboard was too table-like, too wide, and required too much scrolling.
- Symbol, current price, and headers were hard to keep visible.
- Labels were too technical and not immediately meaningful.
- Dashboard mixed signals, context, strategy advice, and refresh behavior.
- Dashboard became partly blackbox-like.
- Dashboard/runtime refresh coupling is an architecture violation if canonical
  data or signal freshness depends on dashboard rendering.

## B. Correct Architecture

- Signals are evidence, not advice.
- Signals feed strategies.
- Only a strategy may produce interpretation or proposals.
- Decision gate remains the account-aware permission layer.
- Execution planner remains execution intent only.
- Executor remains order handling.
- Dashboard is read-only visibility.
- LLM or agent bridge may temporarily act as external strategy interpreter, not
  decision gate or executor.

## C. Signal Dashboard Direction

- Build signal inventory first.
- Show primitive signals per symbol, timeframe, and asof.
- No hidden combinations.
- No HTF/LTF veto logic.
- Every timeframe may have its own truth.
- `5m` bullflag remains valid even if `1d` is bearish; HTF is containment or
  context, not block.
- Outcome validation comes before promoting signal combinations.

## D. Horizon-Separated Dashboard

Dashboard should show horizons separately:

- `15m`: micro setup / bullflag / spike / compression
- `1h`: short-term repair / rejection / continuation
- `4h`: swing context; old dashboard mostly lived here
- `1d`: structural trend / support / damage
- `1w`: cycle / macro / breath / external research
- `external`: Martee / A+ / BTC regime / legacy-alt context

## E. UI Design Principles

- Use asset cards as primary view, not huge wide tables.
- Symbol and current price must always be visible.
- Strategy focus must be visible.
- TP, rebuy, invalidation, and urgency must be near the top.
- Raw technical signals should be in expandable or details sections.
- Human labels first; internal enum names only in tooltip or details.
- No `BUY_READY` / `AVOID` / `WATCH_ONLY` style final labels unless tied to an
  explicit strategy, visible inputs, sample counts, and freshness.

## F. Strategy-Linked Proposals

Canonical strategy/proposal identity must use opaque ids only.

```text
market_event_id
strategy_definition_id
strategy_profile_id
proposal_id
trade_cycle_id
```

Do not use concatenated semantic ids such as `{ACTION}_{HORIZON}_{SETUP}` as
canonical identity or logic input.

Combined phrases such as `SELL_SHORT_SPIKE` may remain only as
legacy/debug/search/display tags. They must not be canonical ids and must not
drive logic.

Proposal semantics must be explicit fields:

- `symbol`
- `horizon`: `SHORT` / `MID` / `LONG`
- `timeframe`: `15m` / `1h` / `4h` / `1d` / `1w` / etc.
- `setup`
- `action`: `BUY` / `SELL` / `HOLD` / `ROTATE` / `WARN`
- `position_side`: `LONG` / `SHORT`
- `exposure_effect`: `OPEN` / `ADD` / `REDUCE` / `CLOSE` / `NONE`

Semantic separation rules:

- `SHORT` / `MID` / `LONG` are horizon labels.
- `SHORT` must never implicitly mean a short position.
- `timeframe` remains separate from `horizon`.
- `position_side` remains separate from `action`.
- `exposure_effect` remains separate from `action`.
- Profile, bucket, and account intent remain outside `selection_engine`.

`action` enum:

- `BUY`: buy-side order/intent direction or proposal category only.
- `SELL`: sell-side order/intent direction or proposal category only.
- `HOLD`: hold/review proposal category only.
- `ROTATE`: linked rotation proposal category only.
- `WARN`: no-action warning category such as no-chase or stale-context warning.

`action` must never be interpreted without `position_side` and
`exposure_effect`.

`exposure_effect` is the only canonical field describing net exposure change:

- `OPEN`
- `ADD`
- `REDUCE`
- `CLOSE`
- `NONE`

Compatibility table:

```text
position_side=LONG:
  BUY  + OPEN/ADD
  SELL + REDUCE/CLOSE

position_side=SHORT:
  SELL + OPEN/ADD
  BUY  + REDUCE/CLOSE

HOLD:
  exposure_effect=NONE

WARN:
  exposure_effect=NONE
```

For `ROTATE`, do not allow one ambiguous proposal to encode both legs.
Represent the reduction/close leg and the open/add leg as separate linked
proposals, each with its own `position_side` and `exposure_effect`.
`trade_cycle_id` may link them.

`position_side=SHORT` is future/venue-capability dependent and remains subject
to `decision_gate`.

`horizon` enum:

- `SHORT`: tactical `15m` / `1h` / `4h` trade-management bucket
- `MID`: swing bucket across `4h` / `1d` / several days
- `LONG`: core thesis / multi-week or multi-month bucket

`setup` starter set:

- `SPIKE`
- `PULLBACK`
- `RECLAIM`
- `BASE`
- `REL_STRENGTH`
- `LEGACY_EXIT`
- `EXHAUSTION`
- `NO_CHASE`

Synonym rules:

- Do not use entry, re-entry, rebuy, reload, dip-buy, retrace, or
  pullback-buy as separate canonical action names.
- Use `BUY` for the action.
- Use `PULLBACK` for the setup when buying after a retrace or dip.
- Use `RECLAIM` when waiting for price to regain a level before buying.
- Do not use exit, take-profit, reduce, or trim as separate canonical action
  names.
- Use `SELL` for the action.
- Use `exposure_effect`, not `action`, to encode whether exposure opens, adds,
  reduces, closes, or remains unchanged.
- `SELL` and `BUY` must remain separate proposals, even when linked by the same
  `trade_cycle_id`.
- Stable ids are opaque identifiers. Semantic enums are fields, not ids.
- Dashboard labels should be human-readable sentence-case.
- Joost may rename display labels later, but canonical opaque ids and semantic
  field values should remain stable.

Strategy proposals must include:

- `proposal_id`
- `strategy_definition_id`
- `strategy_profile_id`
- `trade_cycle_id`
- `bucket_target_pct`
- `bucket_available_pct` or `bucket_current_pct` when known
- `symbol`
- `horizon`
- `timeframe`
- `setup`
- `action`
- `position_side`
- `exposure_effect`
- `activation_condition`
- `leg_state`
- `input_market_event_refs`
- `input_signal_refs`
- `input_context_run_id`
- `created_ts_utc`
- `expiry_ts_utc`
- `sell_levels` only when action is `SELL` or `HOLD`
- `buy_levels` only when action is `BUY`
- `invalidation_level`
- `confidence`
- `rationale`
- `requires_manual_review=true`

No broker write fields.
No order submission fields.

Legacy/debug/search/display tags only:

- `SELL_SHORT_SPIKE`
- `BUY_SHORT_PULLBACK`
- `BUY_SHORT_RECLAIM`
- `HOLD_MID_REL_STRENGTH`
- `SELL_MID_EXHAUSTION`
- `ROTATE_LONG_LEGACY_EXIT`
- `BUY_LONG_BASE`
- `WARN_SHORT_NO_CHASE`

These tags are not canonical identity, not strategy definition ids, and not
logic inputs.

## F1. Market Event Layer

Add one canonical market-event layer between primitive signals and later
strategy definitions.

This layer is:

- market-only
- account-agnostic
- observable/replayable
- not advice
- not permission logic
- not execution intent

Initial event types:

- `BREAKOUT_RETEST_OBSERVED`
- `REVERSAL_RECLAIM_OBSERVED`
- `EXPANSION_CONTINUATION_OBSERVED`
- `EXHAUSTION_FAILURE_OBSERVED`

Each event must retain explicit evidence/reference fields where available:

- `market_event_id`
- `symbol`
- `timeframe`
- `asof_ts_utc`
- `current_price`
- structure / higher-low / breakout / reclaim observations
- support-resistance and breakout level
- relative-volume ratio and baseline definition
- RSI value and slope/divergence observation
- MA alignment and slope observation
- ATR or volatility compression/expansion observation
- relative strength versus BTC / ETH / sector proxy
- fibo anchors, target room, invalidation distance
- spread/depth/executable-liquidity observation
- market-regime reference
- asset-regime reference
- source/freshness/replay-safety metadata

Do not introduce hidden composite scores such as
`liquidity_expansion_score`. Transparent feature fields and event evidence are
the source of truth.

Existing regimes remain the canonical market/asset context. Do not add a
second lifecycle state machine or permanent asset category such as:

- `ALT_PRE_RUNNER`
- `PRE_RUNNER_COIN`
- `LIQUIDITY_EXPANSION_ENGINE`

Compression/building/expansion/exhaustion language is initially only explicit
observation/event grouping. It can become a formal derived lifecycle tag only
after validation proves incremental value over existing regimes and primitive
signals.

## Strategy Profile Ownership

- Strategy selection is not re-decided every hour.
- Joost chooses a strategy profile and target allocation buckets per coin or
  portfolio.
- Synth or the agent only evaluates which strategy legs are active inside that
  existing profile.
- Signals do not select strategies directly.
- Signals provide evidence to strategy legs.
- Strategy profile or bucket config is account-aware intent and must not live
  in `selection_engine`.
- Decision or other account-aware layers later enforce whether a proposal fits
  current exposure, cash, and open orders.

## Bucket Allocation Model

Example profile:

- `SHORT_TACTICAL: 30%`
- `MID_SWING: 15%`
- `LONG_CORE: 55%`

Explanation:

- These buckets sum to `100%`.
- `BUY` and `SELL` legs inside the same bucket are not separate allocations.
- Legacy/debug tags such as `SELL_SHORT_SPIKE` and `BUY_SHORT_PULLBACK` may
  both describe proposals that operate on the `SHORT_TACTICAL` bucket.
- A `SELL` proposal with `horizon=SHORT`, `position_side=LONG`, and
  `exposure_effect=REDUCE` can reduce the long tactical bucket into strength.
- A `BUY` proposal with `horizon=SHORT`, `position_side=LONG`, and
  `exposure_effect=ADD` can increase the long tactical bucket after pullback.
- `LONG_CORE` remains untouched by short tactical proposals unless a `LONG`
  strategy leg explicitly applies.
- `MID_SWING` remains separate from `SHORT_TACTICAL` and `LONG_CORE`.

## Strategy Leg Lifecycle

- Strategy profile persists.
- Strategy legs change state on signal or event refresh.
- Cadence examples:
- `SHORT` legs: evaluate on `15m` / `1h` / `4h` or event triggers.
- `MID` legs: evaluate on `4h` / `1d`.
- `LONG` legs: evaluate on `1d` / `1w` or external macro or cycle review.
- Proposals expire.
- Strategies can continue running, but individual proposals must have
  `expiry_ts_utc`.
- `BUY` / `SELL` proposals can be linked by `trade_cycle_id` but remain
  separate proposals.

## G. LLM / Agent Bridge

- Codex or Synth gathers context.
- ChatGPT or an LLM can temporarily provide strategy interpretation.
- Joost remains manual executor.
- LLM proposals are proposal-only and expire.
- Later, successful LLM process patterns can be measured and promoted into
  Synth strategies.
- LLM bridge must not bypass `decision_gate`, `execution_planner`, or
  `executor`.

## H. Manual Fallback Path

- If token or agent limits are hit, Joost can provide exported context
  manually.
- ChatGPT can return `strategy_proposal_v1.xlsx`.
- Synth can ingest the Excel through dropfolders.
- Use `incoming/`, `processed/`, and `rejected/` folders.
- Use `.ready.json` marker to signal file completeness.
- Receiver must ignore partial files.
- Proposals must show freshness, expiry, and require manual review.

## I. Breath / A+ Separation

- Synth breath is self-calculated from market data, pivots, fibo-time, phase
  alignment, and volume / impulse / compression.
- A+ / Martee / Oracle context is external research or validation context.
- A+ may validate or calibrate Synth breath.
- A+ must not replace Synth breath as source of truth.
- Dashboard must show Synth breath and external A+ context separately.
- FFG is not required input.
- FFG is not runtime market data.
- FFG must not affect `selection_engine`, `decision_gate`,
  `execution_planner`, or `executor`.
- No manual daily FFG capture may be required to detect spikes.
- At most, external FFG observations may later be stored as non-canonical
  comparison/research overlays with `runtime_effect: NONE`.
- The canonical basis for the liquidity-expansion / breakout-reclaim lane is
  Synth market data: OHLCV, volume, structure, relative strength, fibo context,
  spread/depth, and executable liquidity.

## J. Freshness Model

- Every dashboard page or card must show data age or freshness.
- Show latest market timestamp, signal timestamp, and account or order snapshot
  timestamp when account-aware.
- Strategy proposals must show `input_context_run_id`, `created_ts`, and
  `expiry_ts`.
- If context is stale, proposal must not look active.
- Pipelines must keep running even if dashboard render fails.
- Dashboard failure must not stop data collection or signals.

## K. External Research / Macro Context

- Martee / A+ / Oracle updates are external research, not order logic.
- Example: BTC downside pressure, legacy-alt deterioration, HYPE
  relative-strength exception.
- External context can inform strategy interpretation, but must not become
  hidden selection or decision logic.

## L. Deferred Implementation Order

P0a — Canonical market-data, replay, and executable-liquidity audit.

P0b — Define separate schemas/contracts for primitive signal, market event, and
strategy proposal.

P1 — Signal matrix inventory and transparent display.

P2 — Market-event logging only.

P3 — Manual Ladder consumes the same context/event outputs downstream.

P4 — Outcome validation by event cohort.

P5 — Promote only proven event definitions into `strategy_definition` records.

P6 — Manual/paper proposals with profile and bucket context.

P7 — Only later, explicitly approved `decision_gate` / `execution_planner`
integration.

## L1. Outcome Validation Requirements

No canonical general event-cohort outcome-validation TODO currently exists.
Until one is created through a separate documentation task, this backlog is the
bounded home for the liquidity-expansion / breakout-reclaim validation
requirements.

Compare each event family and explicit feature combination against:

- structure-only baseline
- structure + volume baseline
- ordinary top-mover baseline
- random liquid-asset control
- same events with and without market-regime segmentation

Measure:

- `1h` / `4h` / `12h` / `24h` returns
- MFE / MAE
- target-hit and invalidation-hit rate
- time-to-target / time-to-invalidation
- fees, spread, realistic slippage
- symbol concentration
- regime dependence
- out-of-sample performance

No feature combination becomes runtime strategy logic without positive net
expectancy and documented promotion evidence.

## M. Anti-Patterns To Avoid

- Dashboard owns data intake.
- Dashboard recomputes canonical `signal_state`.
- Signals directly emit trade advice.
- Treating debug tags such as `SELL_SHORT_SPIKE 30%` and
  `BUY_SHORT_PULLBACK 30%` as canonical ids or as `60%` total allocation.
- Re-selecting strategy profile every hour.
- Putting account bucket allocation in `selection_engine`.
- Letting signals directly activate account-aware actions without
  strategy/profile context.
- HTF context blocks LTF patterns.
- A+ treated as source of truth for Synth breath.
- FFG treated as required runtime input.
- Adding an alt pre-runner engine or second regime/state-machine.
- Hiding explicit liquidity/structure/volume evidence inside a composite
  expansion score.
- Hidden final labels without visible strategy, input, or freshness.
- Agent or LLM places or cancels orders.
- Big refactor before measurement.

## Existing Overlap

This backlog overlaps with, but does not replace:

- `docs/todo/signal_matrix_dashboard.md`
- `docs/todo/manual_ladder_dashboard.md`
- `docs/ops/runtime_chain_ownership_v1.md`
- `docs/ops/market_breath_context_bridge_v1.md`
- `docs/todo/external_research_ingestion.md`

This file is the v2.14 cross-cutting design backlog for the signal dashboard,
strategy proposal layer, and temporary LLM bridge boundary.
