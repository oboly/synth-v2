# TODO — Idiosyncratic Catalyst Override

## Status

Research/TODO lane.

This document captures the XLM/DTCC/Stellar spike interpretation from the Synth v2.14 handover stream.

## Core lesson

XLM did not spike because the whole market became broadly risk-on or because altseason was confirmed.

XLM spiked because of an asset-specific institutional catalyst:

```text
DTCC + Stellar public-chain tokenization announcement
-> narrative shock
-> thin / under-owned positioning
-> forced repricing
-> dirty squeeze inside caution regime
```

The correct interpretation is:

```text
macro caution regime correct
but idiosyncratic catalyst override occurred
```

Not:

```text
macro caution regime was wrong
global altseason confirmed
```

## Source event

Asset:

```text
XLM
```

Catalyst:

```text
DTCC_STELLAR_PUBLIC_CHAIN_TOKENIZATION
```

Event date:

```text
2026-05-27
```

Official event summary:

```text
DTC's tokenization service plans to connect with Stellar's public blockchain.
DTC-tokenized assets are expected to become available on Stellar during 1H 2027.
DTCC framed the connection as part of a standards-driven, multi-chain strategy.
DTC-tokenized assets are intended to retain investor protections, entitlements, and safeguards similar to traditionally held securities.
```

Primary source:

```text
https://www.dtcc.com/news/2026/may/27/tokenization-service-to-connect-with-stellar-public-blockchain-as-dtc-advances-multi-chain-strategy
```

Next event window:

```text
2027-H1 go-live / availability window
```

## New concept

```text
idiosyncratic_catalyst_override_v1
```

Purpose:

```text
Allow asset-specific institutional catalysts to explain or flag outperformance inside macro caution regimes, without flipping the entire market regime.
```

Examples:

```text
XLM + DTCC/Stellar public-chain tokenization announcement
LINK + DTCC Collateral AppChain / CCIP
CC + DTCC/Canton institutional rails
ONDO + tokenized securities / SEC no-action narrative
PLUME + formal external RWA-plumbing list addition
```

## Dirty squeeze model

```text
dirty_squeeze_v1
```

Definition:

```text
A sharp asset-specific move during macro caution, driven by catalyst repricing + thin positioning + forced chase, not broad market regime confirmation.
```

Typical features:

```text
one asset or narrow theme spikes
broader crypto remains mixed
macro caution remains active
volume expands suddenly
price gaps or candles extend before clean retest
late buyers chase after news
fresh entry quality deteriorates near first target/resistance
```

## XLM-specific interpretation

```text
asset: XLM
state: IDIOSYNCRATIC_CATALYST_SQUEEZE
macro_regime: CAUTION
catalyst: DTCC_STELLAR_PUBLIC_CHAIN_TOKENIZATION
event_date: 2026-05-27
next_event_window: 2027-H1 go-live
fresh_entry_quality_after_spike: LOW_TO_MEDIUM
preferred_manual_interpretation: WAIT_FOR_RETEST_OR_SECONDARY_CONFIRMATION
```

Important:

```text
XLM spike != broad altseason confirmation
XLM spike = regulated public-chain rails repricing
```

## What Synth should learn

Current too-simple logic:

```text
macro caution active
-> block / ignore all bullish asset moves
```

Better logic:

```text
macro caution active
+ asset-specific catalyst
+ relative strength spike
= catalyst exception / dirty squeeze flag
```

Still true:

```text
no automatic buy
no global regime flip
no execution bypass
```

## Inputs

Potential v1 inputs:

```text
macro_regime
asset_return_24h
asset_return_72h
relative_strength_vs_BTC
relative_strength_vs_theme_basket
volume expansion
known catalyst label
external narrative registry match
distance_to_target/resistance
liquidity/spread quality
```

## Outputs

Possible labels:

```text
IDIOSYNCRATIC_CATALYST_OUTPERFORMANCE
DIRTY_SQUEEZE_ACTIVE
FRESH_ENTRY_QUALITY_LOW
WAIT_FOR_RETEST
TP_REVIEW_IF_POSITIONED
DO_NOT_FLIP_GLOBAL_REGIME
```

## Strategy implication

This fits with:

```text
external_support_shoulder_reaction_strategy_v1
```

After a dirty squeeze, the better manual/research response is usually:

```text
do not chase first vertical candle
wait for retest / shoulder hold / volume confirmation
then classify continuation or fade
```

## XLM target / event tracking notes

```text
source event: DTCC/Stellar announcement, 2026-05-27
event window 1: announcement spike
event window 2: 2027-H1 go-live
external target claim: USD 1.00-1.20 by summer / one pump before end of summer
low-confidence community dip note: below USD 0.14 before summer ends
source currency: USD
runtime conversion required: USD -> EUR
```

The USD target and dip notes are external narrative claims and must be stored/validated as research labels, not runtime targets.

## Hoofdpiet one-liner

```text
XLM's move was a narrow institutional-catalyst dirty squeeze inside macro caution, not a broad regime flip. Add idiosyncratic_catalyst_override_v1 so Synth can flag real asset-specific repricing without turning caution off globally.
```

## Boundary

```text
Research-only initially.
No selection_engine changes until validated.
No decision_gate bypass.
No execution_planner changes.
No executor changes.
No orders.
No global regime flip from a single-asset catalyst.
```

## Dashboard relevance

The Manual Ladder Dashboard should eventually be able to show:

```text
catalyst label
catalyst event date
macro regime remains caution
DIRTY_SQUEEZE_ACTIVE
WAIT_FOR_RETEST
TP_REVIEW_IF_POSITIONED
DO_NOT_FLIP_GLOBAL_REGIME
```

This belongs as a contextual interpretation layer, not as execution permission.
