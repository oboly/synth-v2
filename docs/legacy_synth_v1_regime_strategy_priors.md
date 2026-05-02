# Legacy Synth v1 Regime / Strategy Priors

Status: research/design prior  
Scope: Synth v2.5 strategy architecture  
Source: historical Synth v1 config/result audit  
Live trading permission: NOT_GRANTED

---

## Purpose

This document preserves useful strategy evidence from Synth v1 without importing the old Synth v1 architecture.

Synth v1 showed materially different asset behavior across:

- MTF strategy variants
- no-MTF strategy variants
- ADX-based adaptive switching

The v2 lesson is not to copy the old strategy matrix directly.

The v2 lesson is:

1. classify market regime first
2. select strategy family second
3. keep asset behavior as research input
4. keep account, order, and execution concerns outside strategy selection

---

## Architectural boundary

This document is research/design only.

It must not directly modify or drive:

- selection_engine
- decision_gate
- execution_planner
- executor
- account tables
- order tables
- live runtime tables

Allowed future usage:

- research replay
- backtest comparison
- strategy-family test design
- asset/profile/regime prior generation
- documentation of historical behavior

Forbidden usage:

- direct live trade trigger
- future-aware live feature
- account-aware strategy logic
- hard-coded live asset strategy routing without replay validation

---

## Synth v1 adaptive meaning

In Synth v1, the notation:

    ADAPTIVE:<threshold>

should be interpreted as an ADX-threshold regime selector, not as a standalone strategy family.

Confirmed legacy interpretation:

    ADX >= threshold -> TREND -> no-MTF
    ADX < threshold  -> CHOP  -> MTF

This maps to v2 as two separate layers:

    regime_selector
        outputs TREND / CHOP / RANGE / TRANSITION / UNKNOWN

    strategy_selector
        maps asset profile + regime + available strategy families
        to a strategy candidate or no-trade candidate

Do not collapse this back into one monolithic strategy matrix.

---

## Evidence sources from Synth v1

Useful legacy files/artifacts identified during the v1 audit:

- services/adaptive_switch.py
- tools/adaptive_compare.py
- tools/compare_mtf_vs_nomtf.py
- tools/compare_mtf_vs_nomtf_plus_debug.py
- tools/compare_selected_assets.py
- tools/mtf_hybrid_picker.py
- tools/live_step.py
- configs/strategy_matrix.yaml
- configs/strategy_matrix.yaml.A
- configs/mtf_dual_flow_v1.yaml
- results/mtf_compare*/summary_mtf.csv
- results/mtf_compare*/summary_nomtf.csv
- results/strategy_matrix/strategy_matrix_summary.csv
- results/adaptive/adaptive_summary.csv
- old trade CSVs with entry_time / exit_time / pnl / R

Important caution:

The old strategy_matrix format should not be ported directly into v2.

The useful part is the historical evidence that some assets had different strategy-family affinity under different regimes.

---

## Historical asset priors

These are research priors only.

They are not live rules.

| Asset | Synth v1 prior | Evidence summary | V2 interpretation |
|---|---|---|---|
| LINK | no-MTF candidate | no-MTF materially beat MTF in observed comparisons | Trend/no-MTF family deserves priority in replay tests |
| XLM | no-MTF candidate | no-MTF materially beat MTF in observed comparisons | Trend/no-MTF family deserves priority in replay tests |
| HBAR | adaptive candidate | MTF beat no-MTF in raw comparison; adaptive threshold 30 improved meaningfully over base-best | Regime-aware switching is high-priority to retest |
| HOT | adaptive candidate | MTF slightly beat no-MTF; adaptive threshold 16 improved meaningfully over base-best | Regime-aware switching is high-priority to retest |
| HYPE | MTF / weak adaptive candidate | MTF beat no-MTF; adaptive uplift was small at threshold 43 | Retest as MTF/adaptive candidate |
| XRP | weak adaptive / retest | Results were weak/negative, but adaptive threshold 17 improved over base in one summary | Retest only with stricter validation |
| SUI | caution / retest | Both MTF and no-MTF were negative; adaptive uplift small at threshold 42 | Do not trust without new evidence |
| DEEP | disable or retest | Low-confidence / weak evidence | Disable or retest only in research |

---

## Concrete historical result notes

Observed old Synth v1 MTF vs no-MTF summaries included:

| Asset | Stronger observed behavior | Notes |
|---|---|---|
| HBAR | MTF / adaptive | MTF strongly beat no-MTF in one comparison; adaptive threshold 30 improved over base-best |
| HOT | MTF / adaptive | MTF was better than no-MTF in one comparison; adaptive threshold 16 improved over base-best |
| HYPE | MTF / weak adaptive | MTF beat no-MTF; adaptive uplift was small |
| LINK | no-MTF | no-MTF beat MTF in repeated comparisons |
| XLM | no-MTF | no-MTF beat MTF in repeated comparisons |
| XRP | weak adaptive / caution | adaptive improved in one summary, but overall signal was not strong |
| SUI | caution | negative/unstable historical results |
| DEEP | caution | low-confidence / low-trade evidence |

Known adaptive threshold notes:

| Asset | Legacy adaptive threshold | Interpretation |
|---|---:|---|
| HBAR | 30 | meaningful adaptive improvement |
| HOT | 16 | meaningful adaptive improvement |
| HYPE | 43 | small adaptive improvement |
| SUI | 42 | small adaptive improvement; caution |
| XRP | 17 | weak adaptive improvement; retest |

These thresholds are historical priors, not parameters to copy into live v2.

---

## Design translation to Synth v2.5

Recommended v2 decomposition:

    market data
        -> features
        -> measurement / structure state
        -> regime_selector
        -> strategy_selector
        -> selection_engine
        -> decision_gate
        -> execution_planner
        -> executor

Responsibilities:

| Layer | Responsibility | Must not do |
|---|---|---|
| regime_selector | classify market condition | choose account action |
| strategy_selector | choose candidate strategy family | check balances/orders |
| selection_engine | rank market-only opportunity | use account state |
| decision_gate | permit/block action using account state | invent market signal |
| execution_planner | create execution intent | place orders |
| executor/agents | manage orders | reinterpret strategy |

---

## Candidate v2 strategy-family mapping

Initial research mapping:

| Regime | Candidate family | Notes |
|---|---|---|
| TREND | no-MTF / trend-follow continuation | Works where v1 showed trend preference |
| CHOP | MTF / range-aware confirmation | Mirrors old ADX adaptive behavior |
| RANGE | micro-scalp / passive range rotation | Future tactical module only |
| TRANSITION | watch / prepare only | Avoid forcing entries |
| UNKNOWN | no strategy | Must remain conservative |

Asset priors may influence candidate ranking in research, but should not override current regime evidence.

Examples:

    LINK + TREND may rank no-MTF higher
    XLM + TREND may rank no-MTF higher
    HBAR + CHOP may rank MTF higher
    HOT + CHOP may rank MTF higher
    SUI + any regime requires stricter validation

---

## Required replay validation before implementation

Before any live-path integration, run research-only validation:

1. Rebuild or refresh point-in-time replay inputs.
2. Join strategy candidates to point-in-time asset_profile_snapshot.
3. Evaluate by asset, regime, interval, and market phase.
4. Compare against simple benchmark families.
5. Check whether priors persist out-of-sample.
6. Promote only if invariant checks pass.

Minimum validation dimensions:

- asset
- interval
- regime group
- strategy family
- market phase
- liquidity class
- volatility bucket
- forward return horizon
- drawdown / adverse excursion
- exposure time
- benchmark-relative return

---

## Data safety rule

Future-aware labels and hindsight returns may only be used inside research/backtest namespaces.

They may never leak into:

- live selection_engine
- decision_gate
- execution_planner
- executor
- runtime account logic

Oracle/replay output is microscope data, not steering input.

---

## Open implementation TODO

Research-only next steps:

1. Define a v2 regime_selector contract.
2. Define a v2 strategy_selector contract.
3. Build a research export that labels historical rows with:
   - asset_id
   - symbol
   - interval_code
   - asof_ts_utc
   - regime_code
   - candidate_strategy_family
   - source_prior
4. Validate old priors on current v2 feature/signal data.
5. Only then consider selection_engine integration.

Do not implement direct old Synth v1 strategy routing in live code.

---

## Current recommendation

Keep this as a research prior, not operational logic.

The strongest architectural lesson from Synth v1 is:

    regime first
    strategy second
    account later
    execution last

This keeps Synth v2.5 modular, testable, and multi-account ready.
