# Card Update Attention State v1

## Status

Todo / read-model and UI specification.

## Goal

Turn the left asset list into an attention map without turning normal refreshes into noise.

A card must show when meaningful information changed since the user last reviewed it. The opened card must show exactly which sections changed.

This feature is informational only. It must not create, suppress, modify, or submit orders.

## Scope

Applies to the Short Swing / Profit Plan asset list and main detail card.

Build:

```text
market/read-model change detection
→ semantic update batches
→ per-profile seen state
→ left-list attention treatment
→ opened-card changed-section highlights
```

Do not change:

* `selection_engine` market logic;
* Breathline calculation;
* Fib / native-short map calculation;
* `decision_gate`;
* `execution_planner`;
* executor / broker integrations;
* order lifecycle or account permissions.

## Core Semantics

### Structural status is separate from unread updates

| Visual state | Meaning | Clear condition |
|---|---|---|
| Light red wash | `MAP_INVALIDATED`, `MAP_COMPLETED`, or `MAP_EXPIRED` structural state | Only when a valid successor map becomes active |
| Green wash | One or more unseen semantic update batches | User reviews the relevant card state |
| Green intensity | Number of unseen semantic update batches | Decreases only when batches are marked seen |
| Section highlight | A visible card section changed in one or more unseen batches | Clears when those batches are marked seen |

Red is structural and wins as the background treatment. A red card with unseen updates uses a green badge, green left stripe, and green section highlights. Do not layer a full green wash over red.

## User Experience

### Left asset list

Use unread semantic update batches, not refresh count or raw card revision count.

| Unseen batch count | Treatment |
|---:|---|
| `0` | Normal card treatment |
| `1` | Subtle green wash |
| `2–3` | Stronger green wash and numeric badge |
| `4+` | Strongest allowed green wash and `4+` badge |

Example:

```text
TAO                                              3
MAP COMPLETED                              NEW · 3
Breathline · re-entry zone · navigation targets
```

Do not automatically reorder the list because a card changed. Preserve spatial memory while monitoring.

Provide an optional list filter:

```text
Changed (7)
[ Show changed only ]
```

### Opening a card

When a closed card is opened:

1. Mark all update batches that existed before the open action as seen for the current profile/account/card.
2. Remove green list attention for those reviewed batches.
3. Keep structural red state unchanged.

When a new semantic update arrives while that card is already open:

1. Create a new unseen update batch.
2. Do not auto-clear it merely because the card is visible.
3. Increase the green attention intensity/count.
4. Highlight changed sections on the open card.
5. Show a compact summary strip at the top.

Example:

```text
CHANGES SINCE OPENED · 2
Breathline phase · navigation target
[ Mark reviewed ]
```

`Mark reviewed` clears the current unseen batches for the open card only. It must not clear future updates.

### Changed sections on the main card

Do not tint the entire main card strongly. Highlight only changed visible sections with a subtle green edge/wash and a compact `UPDATED` marker.

Example:

```text
BREATHLINE                                      UPDATED
IGNITION_PRE_SPIKE · −3

RE-ENTRY ZONE                                   UPDATED
€180.42 – €177.60

NAVIGATION TARGET ZONE                          UPDATED
€182.29 – €193.23
```

The summary strip must list changed sections in human-readable form and link/scroll to the relevant section when feasible.

## What Counts as a Semantic Update

### Required update kinds

```text
MAP_GENERATED
MAP_ACTIVATED
MAP_REPLACED
MAP_COMPLETED
MAP_EXPIRED
MAP_INVALIDATED
MAP_REBUILD_REQUIRED

BREATHLINE_PHASE_CHANGED
BREATHLINE_SUBPHASE_CHANGED
BREATHLINE_CHECKPOINT_CHANGED
BREATHLINE_REVERSAL
BREATHLINE_CONFIDENCE_CHANGED

REENTRY_ZONE_CHANGED
BUY_THRESHOLD_CHANGED
SELL_THRESHOLD_CHANGED
TARGET_ZONE_CHANGED
INVALIDATION_CHANGED
SETUP_CHANGED
ACTIONABILITY_CHANGED

FIB_LEVELS_CHANGED
RELEVANT_PRICE_CROSS
```

### Explicit non-events

Do not create an update batch for:

* data freshness text alone, for example `0.4 min ago`;
* an ordinary price tick;
* a repeated render with identical visible output;
* a Fib calculation that reruns but yields identical visible levels;
* timestamp-only or layout-only changes.

### Fib rule

A new Fib calculation is meaningful when its visible output changes, even when the current map identity stays the same.

```text
same map + changed visible Fib levels
= FIB_LEVELS_CHANGED
= semantic update batch
```

```text
same map + same visible Fib levels recalculated
= no update batch
```

A new map is not the only valid source of a Fib update.

## Update Batches

One semantic render/update may change several fields. Treat it as one update batch with multiple change kinds and sections.

Example:

```text
batch 1
  BREATHLINE_PHASE_CHANGED
  BREATHLINE_CHECKPOINT_CHANGED
  sections: [breathline]

batch 2
  REENTRY_ZONE_CHANGED
  INVALIDATION_CHANGED
  sections: [reentry_zone, invalidation]

batch 3
  MAP_COMPLETED
  sections: [map_status, navigation_targets]
```

The attention count for the left list is the number of unseen batches, not:

* number of render cycles;
* number of changed fields;
* `card_revision - seen_revision`.

Cap display count at `4+`; retain the exact count internally if needed.

## Read-Model Contract

Extend the card read model with equivalent fields:

```text
card_revision
card_content_fingerprint
latest_update_batch_id
latest_update_at_utc
changed_sections
change_kinds
structural_status
```

Suggested batch contract:

```text
card_update_batch
- card_key
- batch_id
- created_at_utc
- card_revision
- change_kinds[]
- changed_sections[]
- summary_labels[]
- source_map_id / source_map_cycle_id where available
```

`card_content_fingerprint` must be based only on meaningful visible values and structural state. Do not include freshness timestamps or arbitrary render timestamps.

Suggested visible section keys:

```text
map_status
setup
actionability
breathline
buy_zone
reentry_zone
sell_zone
navigation_targets
invalidation
fib_levels
price_cross
```

The read-model/diff layer owns generation of change kinds and sections. The UI only renders those explicit outputs; it must not infer changes by scraping card HTML.

## Seen-State Ownership

### v1: browser-local seen state

The current dashboard is static-rendered. Store seen state in browser `localStorage` for v1.

Required key dimensions:

```text
app_profile_id
trading_account_id
asset_id
card_key
```

Stored value concept:

```text
last_seen_batch_id
last_seen_card_revision
seen_at_utc
```

Rules:

* seen state is per profile and trading account;
* opening a closed card advances seen state only through batches present at open time;
* `Mark reviewed` advances seen state through batches present when clicked;
* a later batch remains unseen;
* switching account/profile must not reuse seen state from another account/profile;
* clearing browser storage may restore green attention; this is acceptable in v1.

### Future: server-synchronised state

Do not create a server table in v1.

A later cross-device feature may add an account/profile-scoped server-side seen-state table. It must preserve the same batch semantics and must not change market or execution ownership.

## State Precedence

1. Structural status decides the base card treatment.
2. Unseen batch count decides green attention treatment.
3. For invalidated/completed/expired cards, preserve red base treatment and use green accent markers only.
4. Section highlights always indicate unseen content change, independent of red/green list treatment.

## Acceptance Criteria

* A five-minute refresh without meaningful card changes creates no green state.
* A card with one unseen semantic update is visibly distinct in the left list.
* Green intensity/badge reflects unseen update batches, not refresh count.
* A closed card clears existing green attention when opened.
* A new update while a card is open remains visible as a new batch until `Mark reviewed`.
* The main card identifies the changed sections without requiring a user to compare old screenshots.
* Invalidated/completed/expired cards retain red structural treatment.
* A red card can still communicate unseen updates without becoming visually ambiguous.
* Same-map visible Fib changes create an update batch.
* Identical Fib recomputation does not create an update batch.
* No automatic list resort occurs because of a card update.
* No execution, policy, order, or broker behavior changes.

## Test Requirements

Minimum tests:

* identical render/fingerprint produces no batch;
* freshness-only changes produce no batch;
* each required semantic change kind maps to expected changed section(s);
* same-map visible Fib change produces `FIB_LEVELS_CHANGED`;
* same-map identical Fib recalculation produces no batch;
* multiple field changes in one render create one batch;
* unseen count increases by batch, not by field;
* card open marks only pre-existing batches seen;
* update while card is open remains unseen until `Mark reviewed`;
* per-profile and per-account localStorage keys do not collide;
* red structural state remains dominant while green accent still exposes unseen updates;
* changed-only filter uses unseen batch count and does not alter normal list ordering.

## Delivery Boundary

Implement as a dedicated read-model + UI PR after the current map-materialisation work is stable.

Do not combine this work with:

* native-short map materialisation;
* manual execution tray;
* ladder profile configuration;
* account or order changes.
