# Regime Evidence Matrix V1

Issue: #617

## Purpose

`RegimeEvidenceMatrixV1` is a reporting/read-model seam for presenting canonical market evidence side by side without creating new indicator, regime, ranking, permission, planning, or execution truth.

Canonical flow:

```text
canonical market evidence producers/contracts
-> RegimeEvidenceCellV1
-> RegimeEvidenceMatrixV1
-> reporting/dashboard renderer
```

The matrix is not a composite classifier. It does not decide the market regime and does not convert raw evidence into BUY/SELL or account-aware actionability.

## Current canonical inputs

The first implementation slice can consume:

```text
PRICE_STRUCTURE
  SignalHorizonV1Evidence from structure_evidence_contract_v1

RELATIVE_STRENGTH
  SignalHorizonV1Evidence from structure reclaim and cross-sectional rank adapters

ROTATION
  SignalHorizonV1Evidence from rotation_evidence_contract_v1

MOMENTUM
  MomentumEvidenceSnapshot from momentum_evidence_snapshot_v1

BREADTH
  MABreadthSnapshot from ma_breadth_snapshot_v1

ETH_BTC_LEADERSHIP
  EthBtcLeadershipSnapshot from eth_btc_leadership_snapshot_v1
```

Known unavailable or not-yet-canonical general families may be represented explicitly with `status=INSUFFICIENT_DATA` and `reason_code=NO_CANONICAL_OWNER` so a renderer can show an honest gap.

Current examples:

```text
VOLATILITY
MACRO_LIQUIDITY
```

The unavailable marker describes repository/contract availability only. It is not bearish, bullish, or neutral market evidence.

## Source-owned semantics are preserved

The matrix deliberately does not normalize all producer statuses into one invented vocabulary.

Examples:

- `SignalHorizonV1Evidence.status`, `freshness`, `effective_horizon`, `observed_lifecycle`, raw values, reason codes and provenance are copied verbatim.
- `MomentumEvidenceSnapshot.status`, `freshness`, `observed_lifecycle_status`, `data_quality`, raw MACD/signal/histogram values and reason codes are copied verbatim. The read model does not synthesize a richer lifecycle object than the producer owns.
- `MABreadthSnapshot.data_status`, `freshness_status`, `effective_horizon` and raw participation values are copied verbatim. `UNKNOWN` freshness/horizon is not upgraded in reporting.
- `EthBtcLeadershipSnapshot` raw return/ratio evidence is copied verbatim. No `ETH_LED` or `BTC_LED` state is inferred by the matrix.

This matters because several upstream contracts intentionally remain fail-closed or partially unmapped. Reporting must display those gaps rather than repair them locally.

## Scope identity

Some canonical `SignalHorizonV1Evidence` adapters use the generic value `market="asset"`. That label is not sufficient to distinguish BTC from ETH or other assets inside one matrix.

`RegimeEvidenceCellV1` therefore carries a separate `scope_key` used only for deterministic identity and ordering. It is built from already-prepared provenance, for example:

```text
venue=bitvavo;asset_id=1
venue=bitvavo;asset_id=2
```

No symbol lookup, pair inference, threshold, or market classification occurs while building `scope_key`.

## Renderer boundary

`src/reporting/regime_evidence_matrix_html_v1.py` is presentation-only. It accepts an already-built `RegimeEvidenceMatrixV1` and renders the prepared fields as a static HTML table.

It may:

```text
escape user/source text for HTML safety
format exact Decimal/datetime/lifecycle values for display
use existing cockpit CSS/navigation helpers
map technical availability states to visual tone
```

Technical tone mapping is limited to display treatment for exact source values such as `VALID`, `AVAILABLE`, `FRESH`, `STALE`, `INSUFFICIENT_DATA`, and `UNKNOWN`. The exact source label is always visible as text, so color is never the only carrier of meaning. Tone cannot alter the source status or create market direction.

The renderer does not fetch databases or invoke producers. Producer orchestration/data loading remains a separate later wiring slice so source selection, point-in-time identity and freshness ownership can be reviewed independently from presentation.

## Forbidden behavior

The matrix and its renderer must not:

```text
calculate MACD/EMA
classify momentum as EARLY_UP / UP / MOMENTUM_REVERSAL
invent breadth bands such as EXPANDING / CONTRACTING
invent ETH_LED / BTC_LED thresholds
invent relative-strength/reclaim thresholds
infer effective_horizon from input_interval
invent freshness thresholds
combine components into one opaque score
emit BUY / SELL
read account balances or positions
modify selection_engine
grant decision permission
create execution intent
submit orders
```

If a state is not already owned by a reviewed upstream contract, it remains absent or explicitly unavailable.

## Determinism

A matrix cell identity is:

```text
family
component
market
scope_key
input_interval
lookback_horizon
```

Duplicate identities fail closed. Duplicate detection uses those exact source values, including the distinction between `None` and a real empty string.

For ordering only, nullable `input_interval` and `lookback_horizon` values use a tagged comparison representation:

```text
None       -> (0, "")
any string -> (1, value)
```

This prevents Python from comparing `None` directly with strings while preserving a deterministic distinction between `None` and `""`. The canonical cell values themselves are never rewritten. The explicit `scope_key` allows multiple assets with the same generic upstream `market` label to coexist safely.

For an identical matrix, the renderer emits identical HTML. It does not read wall-clock time or mutable external state.

## Phasing

Phase 1 owns the read model and normalization boundary.

Phase 2 owns the pure HTML renderer only.

A later #617 wiring slice may load reviewed canonical evidence and construct the matrix for publication. That wiring must remain market-only, replay-safe and read-only, and must not duplicate producer logic inside reporting.

## Safety

```text
reporting_only=1
market_truth_creation=0
account_awareness=0
selection_engine_change=0
decision_gate_change=0
execution_planner_change=0
executor_change=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_activation=0
```
