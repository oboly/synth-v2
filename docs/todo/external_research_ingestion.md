# External Research Ingestion TODO

Status: TODO  
Scope: research-only  
Runtime impact: none

## Purpose

Convert external PRO/RV/Martee/A+ research into structured, testable research inputs.

External notes often contain:

- support zones
- shoulder lines
- retest zones
- reset zones
- target zones
- TP review zones
- invalidation zones
- timing windows
- short signals
- long signals
- macro stress scores

These must be extracted separately from narrative summaries so Synth can later validate them.

## Hard boundaries

- Do not change selection_engine behavior.
- Do not change decision_gate.
- Do not change execution_planner.
- Do not change executor.
- Do not enable broker writes.
- Do not create orders.
- Do not mark external research assets BUY_READY.
- Do not mark PLUME tradeable without universe policy review.
- Keep all outputs research-only until validated.

## Core strategy idea

### external_support_shoulder_reaction_strategy_v1

Martee/PRO zones are structural map levels, not direct trade commands.

Synth should wait for market behavior around those levels:

- support touch
- reaction
- close above/below
- volume confirmation
- higher-low confirmation
- relative strength
- BTC/macro not damaging

Allowed research outputs:

- NO_ACTION
- WAIT_FOR_SUPPORT_TOUCH
- SUPPORT_REACTION_CANDIDATE
- SHOULDER_BREAKOUT_CANDIDATE
- SHOULDER_RETEST_ENTRY_CANDIDATE
- TARGET_APPROACHING
- TP_REVIEW
- INVALIDATED

## Martee signal horizon model

Martee is a high-confidence external technical/oracle source, but signals have different horizons and precision.

### signal_kind

- SHORT_SIGNAL
- LONG_SIGNAL
- TARGET_ZONE
- RESET_ZONE
- SUPPORT_ZONE
- SHOULDER_LINE
- CONFIRMATION_TRIGGER
- INVALIDATION_ZONE
- TP_REVIEW_ZONE
- MTF_CONFIRMATION

### signal_horizon

- INTRADAY
- SHORT_TERM
- MEDIUM_TERM
- LONG_TERM
- MULTI_MONTH

### zone_precision

- NARROW
- MEDIUM
- WIDE

### source_confidence_prior

Default for Martee:

- VERY_HIGH

Important rule:

Broad long-term zones must not be scored as failed just because they are not hit quickly. Validation must respect `signal_horizon` and expected validation window.

## Extraction schema

Required fields:

- asset
- source_name
- source_date
- source_type
- level_role
- signal_kind
- signal_horizon
- zone_precision
- source_confidence_prior
- source_quote_currency
- source_level_single
- source_zone_low
- source_zone_high
- runtime_quote_currency
- runtime_level_single
- runtime_zone_low
- runtime_zone_high
- fx_pair
- fx_rate
- fx_rate_asof_ts
- fx_conversion_method
- reaction_required
- breakout_required
- retest_required
- confirmation_type
- target_usage
- synth_validation_status
- actionability
- notes

## level_role values

- SUPPORT_ZONE
- SHOULDER_LINE
- SHOULDER_ZONE
- RETEST_ZONE
- RESET_ZONE
- TARGET_ZONE
- TP_REVIEW_ZONE
- INVALIDATION_ZONE

## confirmation_type values

- TOUCH_REACTION
- CLOSE_ABOVE
- CLOSE_BELOW
- VOLUME_BREAK
- HIGHER_LOW
- MTF_CONFIRMATION

## target_usage values

- ENTRY_WATCH
- RETEST_WATCH
- TP_REVIEW
- REGIME_CONTEXT
- INVALIDATION_ONLY
- WAIT_FOR_REACTION

## Currency handling

Most external PRO/Martee/RV targets are quoted in USD.

Bitvavo/runtime prices are often EUR.

Rules:

- Never overwrite source USD levels.
- Store EUR conversion separately.
- Formula: EUR = USD / EURUSD.
- Historical validation should use FX rate at source_date or validation asof.
- Live validation should use latest available FX asof.
- If FX is unavailable, keep source USD only and mark conversion missing.

## Validation metrics

For every extracted level or zone:

- was_zone_reached
- first_touch_ts
- reaction_pct_after_touch
- max_drawdown_before_reaction
- direction_after_touch
- volume_confirmation
- relative_strength_confirmation
- invalidated_before_target
- time_to_target
- false_positive_notes

Questions to answer:

- Do Martee support zones work better than targets?
- Do shoulder retests work better than breakout chases?
- Do short signals validate faster than long signals?
- Does weekly confirmation materially improve outcomes?
- Which asset classes respond best: crypto, commodities, indices, FX?

## Latest unsaved research examples

### Martee 2026-05-25

BTC:

- $88K bullish continuation trigger.

HYPE:

- $68-$80 target zone.
- $75-$80 TP review zone.

NEAR:

- moved from ~$1 to $2.77.
- resistance near $3.
- bullish daily and weekly.

AKT:

- up 12% in session.
- positive daily and weekly.
- quiet outperformer.

CC / Canton:

- short-term signal active.
- target $0.25-$0.30 coming months.
- no weekly confirmation.

DXY:

- target 90 in 4-6 months.
- invalidation 102-103.

NASDAQ:

- target up to 32,000.

GOLD:

- needs above 5,000.

SILVER:

- possible reset to 70.

### VET

Classification:

- legacy enterprise / supply-chain infrastructure.
- likely final token-convexity cycle.

Levels:

- current reference: $0.066
- possible lower peak: $0.035-$0.050
- shoulder / breakout: $0.07-$0.09
- target: $0.11
- target: $0.16
- upper target: $0.41-$0.45
- outlier target: $0.72-$0.91

Labels:

- VET_LEGACY_ENTERPRISE_INFRA_FINAL_CYCLE
- VET_DUAL_TOKEN_VALUE_CAPTURE_DRAG
- VET_DIGITAL_PRODUCT_PASSPORT_LAYER
- VET_0709_SHOULDER_LINE_CONFIRMATION

### KITE

Classification:

- AI-agent payment coordination layer.

Levels:

- current reference: $0.23
- pullback zone: $0.18-$0.20
- first wave target: $0.47
- target: $1.00
- second-wave target: $1.00-$1.26

Labels:

- KITE_AGENTIC_PAYMENT_RAIL
- KITE_AI_AGENT_COORDINATION_LAYER
- KITE_TRANSACTION_BUYBACK_VALUE_CAPTURE

### PLUME

Classification:

- institutional RWA financial plumbing.
- add as external research candidate only.

Levels:

- current reference: $0.14
- launch reference: $1.21
- research signal date: 2026-05-15
- key resistance / momentum confirmation: $0.24
- conservative genesis wave range: $0.02-$0.055
- monthly emission: 3.6%
- annualized inflation: ~33.6%

Risks:

- EMISSION_PRESSURE
- UNLOCK_DILUTION
- RWA_DEPLOYMENT_DELAY
- LEGAL_ENFORCEABILITY_COMPETITION

Labels:

- PLUME_INSTITUTIONAL_RWA_PLUMBING
- PLUME_EMISSION_ABSORPTION_RISK
- PLUME_024_MOMENTUM_CONFIRMATION
- PLUME_RWA_LEGAL_ENFORCEABILITY_TESTBED

### Terafab AI chip security window

Registry key:

- FFGRV_2026_05_18_RV_TERAFAB_AI_CHIP_SECURITY_WINDOW

Event window:

- 2027-2029

Labels:

- DOMESTIC_AI_CHIP_SOVEREIGNTY
- AI_HARDWARE_VERTICAL_INTEGRATION
- TERAFAB_SECURITY_BREACH_2027_2029_WATCH
- TAIWAN_SEMICONDUCTOR_CONCENTRATION_RISK
- CLOSED_AI_COMPUTE_STACK
- OPEN_DECENTRALIZED_COMPUTE_COUNTERTHESIS

Crypto-adjacent watch:

- TAO
- RENDER
- AKT
- NEAR
- FET / ASI
- IO.net
- FIL

### NEAR live observation

State:

- ROTATION_CONTINUATION_CANDIDATE

Observed structure:

- second leg after higher-low

EUR levels:

- support: 2.00
- support zone: 1.90-1.95
- failure: below 1.75-1.80
- breakout: 2.12-2.15
- next watch zone: 2.25-2.35

Actionability:

- WATCH_ONLY

### Macro bond-confidence score update

Working hypothesis:

Bond confidence fracture is more important than immediate DXY crash.

Scores:

- global bond confidence fracture: 7.5 / 10
- Japan superlong bond stress: 8.5 / 10
- Gulf/UAE dollar backstop demand: 6.5 / 10
- USD squeeze before dollar bleed: 6.5 / 10
- dollar crash short-term: 3.5 / 10
- dollar structural bleed 3-6 months: 6.5 / 10
- monetary system transition: 6.5 / 10
- liquidity backstop probability: 6 / 10
- selective alt rotation: 7 / 10
- broad altseason: 5 / 10

Sequence:

Japan JGB stress
→ global duration repricing
→ Gulf/Asia dollar backstop demand
→ USD squeeze
→ liquidity response
→ dollar credibility bleed
→ BTC/gold/tokenized rails bid
