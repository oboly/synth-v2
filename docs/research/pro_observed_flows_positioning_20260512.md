# PRO Observed Flows & Positioning — 2026-05-12

Status: research-only  
Runtime impact: none  
Decision/execution impact: none  
Live trading impact: none  

## Purpose

This document preserves external PRO observed-flows, positioning, narrative, Elliott/Fibo, and target-band claims for ALGO, AERO, and ENJ.

These values are external research references, not verified truth and not direct signals.

## Boundary

Allowed downstream use:

- `data/external/pro_elliott_fibo/`
- `research_external_analysis_source`
- `research_external_narrative_claim`
- `research_external_target_level`
- `research_external_chart_observation`
- research charts
- target-band validation
- narrative/regime labeling
- fib/exit-profile comparison

Forbidden downstream use:

- selection override
- decision gate override
- execution planner instruction
- executor/order logic
- live or paper execution trigger

## Broad market context

External PRO text describes early-stage rotation from BTC/ETH into select altcoins, with BTC framed as mid-ABC corrective on long-term structure and ETH potentially offering lower re-entry.

Monero prior movement is cited as a possible historical leading indicator for broader altcoin cycles three to six months ahead.

Macro variables remain unresolved:

- Federal Reserve rate policy
- Middle East geopolitics
- U.S. regulatory clarity / CLARITY Act path

The current environment is framed as preconditions for an altcoin cycle, not confirmation.

## ALGO

Asset status: existing Synth asset  
Scenario: `ALGO_PRO_FIBO_SCENARIO_V1`  
External theme: `QUANTUM_SAFE_INFRA`  
Narrative quality: `LONG_DURATION`  
Risk theme: `LOW_NEAR_TERM_CATALYST`  
Time horizon: `MULTI_YEAR`

Key levels:

- context price claim: 0.11
- primary target zone: 4.43–4.77
- secondary target: 7.65
- 2.618 extension target: 10.00
- reassessment level: 3.60

Notes:

- Multi-year, low-velocity positioning scenario.
- Quantum-safe infrastructure and RWA/institutional settlement narratives are long-dated.
- No near-term catalyst identified.
- Regulatory and quantum timeline claims remain unverified external claims.

## AERO

Asset status: external candidate  
Scenario: `AERO_PRO_EXPANSION_SCENARIO_V1`  
External theme: `BASE_DEFI_LIQUIDITY_HUB`  
Narrative quality: `STRUCTURAL`  
Risk theme: `BASE_DEPENDENCY`

Key levels:

- entry zone claim: 0.42–0.45
- critical breakout threshold: 2.37
- near-term 2.618 extension zone: 2.29–2.47
- 0.5–0.618 target zone: 3.52–3.79
- golden-ratio target zone: 5.96–6.28

Notes:

- Structural question is whether Aerodrome can replicate Base dominance across other EVM-compatible chains.
- PRO text cites supply lock, holder fee distribution, and lack of VC/team unlock overhang as differentiators.
- Base dependency and competitive displacement remain key risks.

## ENJ

Asset status: external candidate  
Scenario: `ENJ_PRO_ELLIOTT_SCENARIO_V1`  
External theme: `GAMING_NFT_REVIVAL`  
Narrative quality: `SPECULATIVE`  
Risk theme: `LEGACY_SUPPLY_OVERHANG`

Key levels:

- continuation threshold: 0.31
- resistance: 1.04
- resistance: 1.80

Notes:

- Framed as speculative and sector-bounded.
- PRO text cites completed shorter-timeframe Elliott 1-2-3-4-5 and high monthly RSI.
- Failure to clear 0.31 with conviction suggests distribution / exit by legacy holders.

## Architecture note

All rows loaded from this document and manifest remain research-only.

Correct path:

external PRO note → file/manifest lane → normalized research DB rows → validation reports → optional future feature only after validation.

No direct path to `selection_engine`, `decision_gate`, `execution_planner`, executor, broker writes, or orders.
