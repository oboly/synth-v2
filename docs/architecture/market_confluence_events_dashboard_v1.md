# Market Confluence & Events Dashboard V1

**Canonical name:** `market_confluence_events_dashboard_v1`
**Layer:** reporting/display only
**Status:** design — pre-implementation
**Outputs:** `/synth/confluence.html`, `/synth/confluence.json`

---

## Purpose

One read-only page answering:

- What important events occurred in the last 30 days?
- What important events are expected in the next 30 days?
- Which events may materially affect crypto, liquidity, volatility, regulation, AI, quantum, tokenization, bonds, energy, or currencies?
- Which assets and theme buckets may be affected?
- Is sentiment supportive, fearful, overheated, risk-off, or conflicted?
- Which events deserve immediate operator attention?

The dashboard displays. It never derives trading proposals, permissions, or orders.

---

## Architecture Ownership

```
event/source ingestion
→ canonical event/context registry
→ optional framework_context interpretation
→ optional strategy proposal
→ decision_gate
→ execution_planner
→ executor
```

Layer assignments:

| Concern | Owner |
|---|---|
| Dashboard rendering (HTML/JSON) | `src/reporting/` |
| Canonical event data | event/context data layer |
| Sentiment snapshots | market/context data layer |
| Historical impact calculations | `src/research/` or validation layer |
| Framework/strategy interpretation | downstream of event context |

Hard boundaries:

- No `selection_engine` changes.
- No `decision_gate` changes.
- No `execution_planner` changes.
- No `executor` changes.
- No broker calls or writes.
- No order creation or modification.
- No direct event-to-buy/sell permission.
- No news/API retrieval from rendering code.
- No duplicate canonical event storage.

---

## Read-Only Constraint

```
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

The renderer reads completed upstream artifacts only. It performs no external fetches.

---

## Dashboard Sections

### 1. Current Sentiment

Displays:

- Fear & Greed index value
- Classification: `EXTREME_FEAR` / `FEAR` / `NEUTRAL` / `GREED` / `EXTREME_GREED`
- 7-day change
- 30-day range (low, high)
- Short history sparkline
- Direction: `IMPROVING` / `DETERIORATING` / `STABLE` / `VOLATILE`
- Source timestamp and freshness status

Future optional contextual indicators (context only — never direct trade signals):

- BTC volatility index
- BTC dominance
- DXY
- Bond yields (10Y US)
- Oil price
- Gold price
- Stablecoin flows
- Perpetual funding rates

### 2. High-Impact Alert Strip

Shows events with `operator_attention_required=True` and importance `HIGH` or `CRITICAL`.

Lifecycle states:

| State | Meaning |
|---|---|
| `ACTIVE_NOW` | Event window is open |
| `UPCOMING` | Starts within operator-defined look-ahead window |
| `AFTERMATH_ACTIVE` | Event passed but follow-up tracking active |

Importance levels:

| Level | Description |
|---|---|
| `LOW` | Informational; minimal expected market impact |
| `MEDIUM` | Relevant; moderate expected impact |
| `HIGH` | Significant; material impact likely |
| `CRITICAL` | Market-moving; immediate attention required |

### 3. Event Timeline

Default window: previous 30 days and next 30 days.

Timeline states:

| State | Meaning |
|---|---|
| `PAST` | Event ended |
| `ACTIVE` | Event window is open |
| `UPCOMING` | Start date in the future |
| `WINDOW_OPEN` | Date window uncertain; start boundary passed |
| `WINDOW_CLOSED` | Date window uncertain; end boundary passed |
| `CANCELLED` | Event cancelled or postponed |
| `DATE_UNCERTAIN` | Exact date unknown; displayed as a window |

Future filters:

- Time window (custom range)
- Category
- Importance
- Asset
- Theme
- Confidence
- Source type
- Confirmed/speculative state

### 4. Event Card

Fields:

| Field | Description |
|---|---|
| `title` | Human-readable short title |
| `description` | Full description |
| `event date/window` | `start_ts_utc` / `end_ts_utc`; displayed Amsterdam local |
| `category` | See §5 |
| `importance` | `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` |
| `confidence` | `LOW` / `MEDIUM` / `HIGH` / `VERIFIED` |
| `status` | Timeline state (see §3) |
| `expected mechanism` | How the event is expected to affect markets |
| `impact direction` | See §6 |
| `affected assets` | List of affected asset symbols |
| `affected themes` | List of affected theme buckets |
| `source type/ref/date` | See §8 |
| `public anchor status` | `CONFIRMED` / `PARTIALLY_CONFIRMED` / `UNCONFIRMED` / `SPECULATIVE` |
| `actual outcome` | `HIT` / `PARTIAL_HIT` / `MISS` / `INCONCLUSIVE` / `NOT_YET_MEASURABLE` |
| `follow-up status` | Whether post-event tracking is active |

### 5. Categories

| Category | Scope |
|---|---|
| `MACRO` | Global macro: growth, employment, CPI, PMI, etc. |
| `CENTRAL_BANK` | Fed, ECB, BoJ, BoE rate decisions, statements, minutes |
| `BOND_MARKET` | Treasury auctions, yield curve events, debt ceiling |
| `GEOPOLITICAL` | Wars, sanctions, diplomatic events, elections |
| `ENERGY` | Oil, gas, OPEC, energy infrastructure |
| `REGULATORY` | Crypto/AI/finance regulation, enforcement, legislation |
| `TOKENIZATION` | RWA tokenization launches, institutional pilots |
| `AI` | AI hardware, model releases, policy, compute infrastructure |
| `QUANTUM` | Quantum computing milestones, cryptography implications |
| `CRYPTO_MARKET` | ETF decisions, exchange events, market structure |
| `PROTOCOL` | Protocol upgrades, hard forks, network events |
| `TOKEN_UNLOCK` | Scheduled token vesting/unlock events |
| `EXTERNAL_PRO_FORECAST` | A+, FFGRV, or other external research time windows |
| `ASTRO_TIMING` | Lunar/solar timing context (research annotation only) |
| `OTHER` | Events not fitting above categories |

### 6. Impact Directions

| Direction | Meaning |
|---|---|
| `RISK_ON` | Expected to favor risk assets |
| `RISK_OFF` | Expected to pressure risk assets |
| `VOLATILITY_UP` | Increased volatility likely regardless of direction |
| `LIQUIDITY_UP` | Liquidity conditions improving |
| `LIQUIDITY_DOWN` | Liquidity conditions tightening |
| `ASSET_SPECIFIC_BULLISH` | Bullish for specific named assets only |
| `ASSET_SPECIFIC_BEARISH` | Bearish for specific named assets only |
| `MIXED` | Evidence supports conflicting directions |
| `UNKNOWN` | Insufficient evidence to classify |

Do not force directional classification when evidence is weak. Prefer `MIXED` or `UNKNOWN`.

### 7. Explainable Importance Model

Importance is derived from transparent component scores. The UI exposes primitive fields; operators can see exactly why `HIGH` or `CRITICAL` was assigned.

Importance components:

| Field | Description |
|---|---|
| `market_scope_score` | Breadth of market coverage |
| `liquidity_impact_score` | Expected liquidity effect |
| `volatility_impact_score` | Expected volatility effect |
| `regulatory_impact_score` | Regulatory/structural impact |
| `duration_score` | Persistence of impact |
| `confidence_score` | Evidence quality |
| `asset_exposure_score` | Number and weight of affected assets |
| `total_importance_score` | Derived sum; not a black-box quality score |

`total_importance_score` → importance tier mapping must be documented alongside the event data contract. Thresholds are explicit constants, not opaque ML weights.

### 8. Confidence and Source Quality

Confidence levels:

| Level | Meaning |
|---|---|
| `LOW` | Speculation or single uncorroborated source |
| `MEDIUM` | Multiple partial signals or early confirmation |
| `HIGH` | Strong multi-source confirmation |
| `VERIFIED` | Officially confirmed by issuing authority |

Source types:

| Type | Meaning |
|---|---|
| `OFFICIAL` | Government, regulatory, or institution direct release |
| `MARKET_DATA` | Exchange data, price feed, on-chain data |
| `NEWS` | News wire, mainstream media |
| `PRO_EXTERNAL_RESEARCH` | A+ or similar professional external research |
| `FFGRV` | FFGRV forecast or timing window |
| `MANUAL_OPERATOR` | Operator-entered observation |
| `MODEL_DERIVED` | Derived by an internal model |
| `UNKNOWN` | Source type could not be determined |

Public anchor status:

| Status | Meaning |
|---|---|
| `CONFIRMED` | Event date/details officially confirmed |
| `PARTIALLY_CONFIRMED` | Some details confirmed; others speculative |
| `UNCONFIRMED` | Date/details not yet officially confirmed |
| `SPECULATIVE` | No official basis; research/operator hypothesis only |

Importance and confidence are separate fields. A speculative event may still have high potential importance.

### 9. Asset and Theme Mappings

Example affected assets (all enabled and watch-list assets apply):

`BTC`, `ETH`, `XRP`, `XLM`, `HBAR`, `LINK`, `CC`, `ONDO`, `QNT`, `ALGO`, `TAO`, `RENDER`, `AKT`, `NEAR`, `WLD`, `CHIP`

Theme buckets:

| Theme | Description |
|---|---|
| `AI_COMPUTE` | AI hardware, inference, training compute |
| `QUANTUM_RESILIENCE` | Post-quantum cryptography, quantum threat |
| `MONETARY_SYSTEM_PLUMBING` | SWIFT, CBDC, correspondent banking rails |
| `TOKENIZED_ASSETS` | RWA tokenization on-chain |
| `RWA` | Real-world asset representation broadly |
| `SETTLEMENT_RAILS` | Payment finality, settlement infrastructure |
| `BOND_STRESS` | Treasury market stress, yield curve events |
| `ENERGY_SHOCK` | Energy price dislocations |
| `REGULATORY_CLARITY` | Positive or negative regulatory signals |
| `SELECTIVE_ALT_ROTATION` | Altcoin rotation dynamics |
| `MARKET_LIQUIDITY` | Broad market liquidity conditions |

### 10. Historical Outcome Tracking

The renderer may display upstream-calculated outcome results only. Calculations must not run inside the renderer.

Displayed metrics (read from completed research output):

- BTC return after 1h / 4h / 24h / 7d
- Affected basket return
- Volatility change
- Sentiment change
- Expected-versus-actual assessment

Outcome status:

| Status | Meaning |
|---|---|
| `HIT` | Event impact matched expected mechanism |
| `PARTIAL_HIT` | Partial match |
| `MISS` | Expected mechanism did not materialize |
| `INCONCLUSIVE` | Evidence insufficient to determine |
| `NOT_YET_MEASURABLE` | Outcome window not yet elapsed |

### 11. Confluence Summary

Displayed at the top of the page. Possible states:

| State | Meaning |
|---|---|
| `SUPPORTIVE` | Sentiment positive; no active high/critical risk events |
| `CAUTION` | Moderate concern; elevated upcoming events |
| `HIGH_VOLATILITY` | High-volatility events active or imminent |
| `RISK_OFF` | Dominant risk-off drivers active |
| `CONFLICTED` | Mixed signals; bullish and bearish events overlap |
| `INSUFFICIENT_DATA` | Sentiment or event data unavailable or stale |

Exposed components (non-opaque):

- Sentiment state and value
- High/critical events currently active (count)
- High/critical events next 7 days (count)
- Dominant risk themes (list)
- Dominant opportunity themes (list)
- Bullish / bearish / mixed / unknown event counts
- Event concentration in next 7 days

---

## Candidate Normalized Contracts

### Sentiment Snapshot

```
snapshot_ts_utc           UTC timestamp of this snapshot
fear_greed_value          0–100 numeric value
fear_greed_class          EXTREME_FEAR | FEAR | NEUTRAL | GREED | EXTREME_GREED
change_7d                 Point change over 7 days
range_low_30d             Minimum over 30 days
range_high_30d            Maximum over 30 days
sentiment_direction       IMPROVING | DETERIORATING | STABLE | VOLATILE
source_type               Source type code
source_ref                Source identifier or URL (read-only)
source_ts_utc             Timestamp of source observation
freshness_status          FRESH | STALE | SOURCE_UNAVAILABLE
```

### Event Row

```
event_id                  Surrogate primary key
event_key                 Stable human-readable key (e.g. "FED_FOMC_20260618")
event_cluster_key         Groups related events (e.g. recurring series)
supersedes_event_id       For updated/corrected versions
title                     Short title
description               Full description
category                  See §5
start_ts_utc              Event start (or best estimate)
end_ts_utc                Event end (null if instantaneous)
date_certainty            EXACT | ESTIMATED | WINDOW_ONLY | UNKNOWN
event_status              Timeline state; see §3
importance                LOW | MEDIUM | HIGH | CRITICAL
confidence                LOW | MEDIUM | HIGH | VERIFIED
impact_direction          See §6
affected_assets_json      JSON list of asset symbols
affected_themes_json      JSON list of theme codes
source_type               See §8
source_ref                Source identifier
source_published_ts_utc   When the source was published
source_count              Number of corroborating sources
public_anchor_status      CONFIRMED | PARTIALLY_CONFIRMED | UNCONFIRMED | SPECULATIVE
expected_mechanism        Free-text description of expected causal path
importance_components_json JSON object with component scores (see §7)
operator_attention_required Boolean
actual_outcome_status     HIT | PARTIAL_HIT | MISS | INCONCLUSIVE | NOT_YET_MEASURABLE
outcome_available         Boolean
follow_up_status          Text or structured follow-up state
created_at_utc            Row creation timestamp
updated_at_utc            Row last-updated timestamp
```

---

## Source and Freshness Rules

- DB timestamps and JSON payloads remain UTC.
- Human-facing display uses Europe/Amsterdam (CET/CEST) per the dashboard time display policy.
- See `docs/architecture/dashboard_time_display_policy_v1.md`.
- The renderer performs no external fetches.
- Stale or unavailable sources remain visible with freshness status:
  - `FRESH` — within acceptable staleness window
  - `STALE` — data present but outside acceptable window
  - `SOURCE_UNAVAILABLE` — source row absent or error
- Events with uncertain dates display as windows; no invented timestamps.

---

## MVP Scope

Read-only MVP delivers:

- Current Fear & Greed value, class, direction, and recent trend
- Previous 30-day event timeline
- Next 30-day event timeline
- Importance highlighting and alert strip
- Confidence and source type labels per event
- Affected assets and themes per event card
- Compact confluence summary with exposed components
- Source and freshness diagnostics
- Static HTML output at `/synth/confluence.html`
- JSON data file at `/synth/confluence.json`
- No DB writes
- No trading integration

---

## Delivery Phases

### Phase 1 — Inventory (next step)

Before schema or implementation:

- Inspect existing event tables and any external research tables (A+, FFGRV, macro/calendar).
- Inspect sentiment storage (Fear & Greed or equivalent).
- Inspect existing outcome/impact storage.
- For each concern decide:
  - `REUSE_EXISTING` — existing table/source is sufficient
  - `EXTEND_EXISTING` — existing table needs new fields
  - `NEW_CANONICAL_EVENT_REGISTRY_REQUIRED` — no suitable existing storage
- Document inventory findings before designing schema.

### Phase 2 — Read-Only Input Contracts

- Define SQL views or data access queries.
- Define Python data access in `src/reporting/` or a dedicated context layer.
- No writes. No schema changes before Phase 1 is complete.

### Phase 3 — Reporting MVP

- `src/reporting/run_confluence_dashboard_v1.py` (runner)
- Static HTML renderer using existing reporting patterns.
- JSON output with event rows and sentiment snapshot.
- Safety markers: broker_private_calls=0, broker_writes=0, order_submission=0.

### Phase 4 — Historical Outcome Validator

- `src/research/` validates event impact against forward price/volatility/sentiment data.
- Results written to a research output table or file.
- Dashboard Phase 3 reads these results; Phase 4 computes them.

### Phase 5 — Extensions

- Event clustering by key/series.
- Operator override / annotation layer.
- Configurable look-ahead and look-back windows.
- Additional contextual indicators (DXY, yields, funding rates).
- TradingView/Lightweight Charts integration if UI v2 proceeds.

---

## Safety Markers

```
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
