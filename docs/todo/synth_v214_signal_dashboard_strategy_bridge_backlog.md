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

Canonical internal `strategy_id` / proposal id format:

```text
{ACTION}_{HORIZON}_{SETUP}
```

`ACTION` enum:

- `BUY`: entry, re-entry, rebuy, reload, dip-buy. Use `BUY` as the only
  canonical action for adding or restoring exposure.
- `SELL`: exit, take-profit, reduce, trim. Use `SELL` as the only canonical
  action for reducing exposure.
- `HOLD`: keep exposure with levels, trailing, or invalidation.
- `ROTATE`: reduce or shift exposure in favor of another thesis or opportunity.
- `WARN`: no-action warning such as no-chase or stale-context warning.

`HORIZON` enum:

- `SHORT`: tactical `15m` / `1h` / `4h` trade-management bucket
- `MID`: swing bucket across `4h` / `1d` / several days
- `LONG`: core thesis / multi-week or multi-month bucket

`SETUP` enum starter set:

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
- `SELL` and `BUY` must remain separate proposals, even when linked by the same
  `trade_cycle_id`.
- Internal ids are all-caps stable enums.
- Dashboard labels should be human-readable sentence-case.
- Joost may rename display labels later, but internal canonical ids should
  remain stable.

Strategy proposals must include:

- `strategy_id`
- `profile_id`
- `bucket_id`
- `bucket_target_pct`
- `bucket_available_pct` or `bucket_current_pct` when known
- `trade_cycle_id`
- `symbol`
- `horizon`
- `action = BUY / SELL / HOLD / ROTATE / WARN`
- `setup`
- `activation_condition`
- `leg_state`
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

Candidate strategies:

- `SELL_SHORT_SPIKE`
- `BUY_SHORT_PULLBACK`
- `BUY_SHORT_RECLAIM`
- `HOLD_MID_REL_STRENGTH`
- `SELL_MID_EXHAUSTION`
- `ROTATE_LONG_LEGACY_EXIT`
- `BUY_LONG_BASE`
- `WARN_SHORT_NO_CHASE`

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
- `SELL_SHORT_SPIKE` and `BUY_SHORT_PULLBACK` both operate on the
  `SHORT_TACTICAL` bucket.
- `SELL_SHORT_SPIKE` can reduce or sell the tactical bucket into strength.
- `BUY_SHORT_PULLBACK` can restore or buy the tactical bucket after pullback.
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

1. Runtime freshness audit and ownership docs.
2. Signal inventory.
3. Horizon-separated signal matrix.
4. Asset-card dashboard.
5. Strategy proposal contract.
6. Manual Excel or dropfolder path.
7. LLM strategy bridge.
8. Outcome logging.
9. Promotion rules for measured strategy logic.
10. Only later: decision or execution integration, if explicitly approved.

## M. Anti-Patterns To Avoid

- Dashboard owns data intake.
- Dashboard recomputes canonical `signal_state`.
- Signals directly emit trade advice.
- Treating `SELL_SHORT_SPIKE 30%` and `BUY_SHORT_PULLBACK 30%` as `60%` total
  allocation.
- Re-selecting strategy profile every hour.
- Putting account bucket allocation in `selection_engine`.
- Letting signals directly activate account-aware actions without
  strategy/profile context.
- HTF context blocks LTF patterns.
- A+ treated as source of truth for Synth breath.
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
