# Execution Offset Preview + Paper Validation V1 (#317)

## Scope

This is the research-only core for #317 steps 3-4. It consumes the merged #224 execution-offset episode/policy contract. It does not alter `selection_engine`, `decision_gate`, `execution_planner`, executor/agents, broker state, orders, or runtime configuration.

The architecture boundary is explicit:

`canonical market level -> research preview/evidence -> paper validation evidence`

No arrow from this module grants permission or execution intent.

## Read-only preview

`build_execution_offset_preview()` preserves `ideal_market_level` exactly from `ExecutionOffsetEpisodeV1.canonical_level`. It derives the raw policy price only through #224 `execution_price_for_policy()` and carries policy id/version/fingerprint and `source_map_id` provenance.

Tick normalization reuses `src.market_rules.price_tick_normalization_v1`, the public-market metadata owner. The research module deliberately does not import `execution_planner` rounding code. BUY uses the existing `REENTRY_BUY` floor semantics; SELL uses `TARGET_SELL` ceiling semantics. Missing tick metadata is `NON_ACTIONABLE / MISSING_TICK_RULE`, never silently treated as a valid proposal. A tick-rounded candidate that reaches or crosses the immutable invalidation barrier is likewise `NON_ACTIONABLE / INVALID_INVALIDATION_GEOMETRY`; the preview never repairs either level.

Preview output is evidence only: `preview_only=true`, `decision_permission=false`, `execution_intent=false`.

## Paper validation

`build_paper_validation_report()` accepts explicit #224 episodes, replay candles, caller-supplied policy instances, and explicit research cost assumptions. It requires coverage of `EXACT_LEVEL`, `STATIC_BUFFER`, and `VOLATILITY_SCALED_BUFFER`, but does not hardcode the rejected #559 fixed-buffer grid as a promoted default.

Fill, near-miss, MFE, MAE, invalidation-before-fill, and time-to-fill come from the shared #224 `replay_episode()` implementation. This module does not reconstruct those semantics.

Paper replay uses the exact tick-rounded `execution_price` emitted by the preview. To avoid duplicating #224 fill logic, the validator creates an immutable derived replay episode pinned to that rounded price and delegates to #224 `EXACT_LEVEL`; the resulting evidence is then labeled with the original policy id/version/fingerprint and preserves the original canonical market level separately. Thus paper fills cannot silently use a theoretical pre-rounding price that the venue cannot quote.

Cost assumptions are explicit Decimal values:

- `fee_bps_per_side`
- `slippage_bps_per_fill`

The round-trip research cost proxy is `(2 * fee_bps_per_side + 2 * slippage_bps_per_fill) / 100` percentage points. `fee_slippage_adjusted_mfe_proxy_pct` is MFE minus that cost. It is an evaluation proxy, not a claim of realized PnL.

## Post-fill outcomes

A profit target is never invented. When `PaperOutcomeContextV1.profit_target_price` is absent, target-hit metrics have no eligible denominator. The episode invalidation remains independently measurable after fill whenever it exists. Paper validation is specifically an entry-policy simulation: BUY requires profit target above the tick-valid execution price and invalidation below it; SELL requires target below and invalidation above. Reversed target/invalidation geometry fails closed even when only one of those levels is supplied.

The fill timestamp is taken from #224 `time_to_fill_seconds`. Post-fill scanning re-applies the episode full-interval boundary: candle open must be at/after issuance, candle close must be at/before `valid_until_ts_utc`, and candle close must be strictly after the fill candle. Outcomes can therefore never leak beyond the episode validity horizon. If one OHLC candle spans both target and invalidation, the result is explicit `AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE`; no intrabar order is guessed.

## Segmentation and confidence

Reports are deterministic and segment each policy by:

- symbol
- market regime (`UNKNOWN_REGIME` when the input has no genuine regime fact)

Every segment carries a positive-integer minimum-sample confidence gate. No map lifecycle state is relabeled as market regime.

## Safety

`research_only=1`
`account_awareness=0`
`decision_permission=0`
`execution_intent=0`
`broker_writes=0`
`order_submission=0`
`runtime_activation=0`

Any later runtime consumption remains outside #317 and requires a separate reviewed decision-gated/planner path.

## Batch fail-closed semantics

Paper validation is deliberately fail-fast. If any episode cannot produce an actionable tick-valid preview for any requested policy, the whole requested cohort fails with `PAPER_PREVIEW_NON_ACTIONABLE:<reason>` rather than silently dropping that episode and changing comparison denominators. Cohort splitting/exclusion must be explicit at a higher research orchestration layer.
