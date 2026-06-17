
## Profit Plan Search-First Refactor TODO

Current behavior uses `Relevant candidates` / `card.is_relevant` as a default visibility gate.

This must be removed from the user-facing Profit Plan flow.

### Problem

The current UI defaults to a vague `Relevant` mode.

This hides non-relevant cards by default:

```text
mode != "all" and not card.is_relevant

EEOF
EOF'

## Profit Plan Search-First Refactor TODO

Current behavior uses `Relevant candidates` / `card.is_relevant` as a default visibility gate.

This must be removed from the user-facing Profit Plan flow.

### Problem

The current UI defaults to a vague `Relevant` mode.

This hides non-relevant cards by default:

    mode != "all" and not card.is_relevant

This creates a blackbox visibility problem.

Example:

    XLM is enabled, portfolio-enabled, tradeable, and has data,
    but may still be hidden from the default Profit Plan list because card.is_relevant=false.

This makes symbol discovery unclear.

### Required Direction

Remove the user-facing `Relevant` concept from Profit Plan.

Do not replace it with another vague filter.

The first refactor should be:

    Profit Plan page
      -> expanded search/filter interface
      -> user can find any supported/configured symbol
      -> selected symbol opens one full Profit Plan card

### Phase 1: Remove Relevant Default

- Remove `Relevant candidates` as the default visible mode.
- Do not default-hide cards only because `card.is_relevant=false`.
- Rename or remove the `Relevant` label.
- If `card.is_relevant` remains internally, treat it as backend metadata only.
- Do not expose `Relevant` as a user-facing concept.

Preferred replacement labels:

    All symbols
    Needs action
    No action
    Filtered by search

Avoid:

    Relevant
    Interesting
    Smart
    Good

### Phase 2: Expanded Search / Filter

Add a stronger search and filter interface before the one-card page is introduced.

Search should support at least:

- symbol
- token name
- asset class
- plan status
- map status
- ladder status
- order status
- account status
- risk status
- data status
- held / not held
- open order / no open order
- actionable / no action

Important:

Symbol discovery must not depend on holdings.

A symbol such as `XLM` must be findable when:

- `asset.is_enabled=1`
- `asset.is_tradeable=1`
- symbol is supported/configured
- data exists

Even if:

- current plan has no action
- selection state is neutral
- setup filter fails
- no current position exists

### Phase 3: One-Card Master/Detail Page

After the expanded search/filter is stable, replace the multi-card layout with a one-card master/detail UI.

Target layout:

    Selection / filter list
      symbol
      PPP
      PPT
      PPV
      Plan:
      Map:
      Ladder:
      Order:
      Account:
      Risk:
      Data:

    Selected detail pane
      one full Profit Plan card

    Future
      graph below selected card

The selection list chooses one symbol.

The detail pane renders exactly one full Profit Plan Card.

### Architecture Rules

The UI may:

- search
- filter using explicit backend-provided fields
- select a symbol
- render one selected card

The UI must not:

- compute PPP/PPT/PPV
- compute relevance
- infer trading status
- infer stale orders
- infer invalidation
- hide symbols based on wallet holdings
- decide account permission
- place orders

### Backend Contract Direction

Replace vague relevance semantics with explicit fields:

    visibility_scope
    actionable
    plan_status
    map_status
    ladder_status
    order_status
    account_status
    risk_status
    data_status
    symbol_status
    filter_reasons

If a card is not actionable, expose why:

    Plan: No action
    Data: OK
    Reason: Selection state not eligible

Do not hide it without explanation.

### Acceptance Criteria

- `Relevant candidates` is no longer the default Profit Plan view.
- User-facing `Relevant` label is removed.
- XLM can be found through search even when it has no current action.
- Search/filter list distinguishes discoverable symbols from actionable symbols.
- One-card master/detail layout is planned as the next UI phase.
- `card.is_relevant` does not remain as a silent user-facing visibility gate.
- Any remaining filtering is explicit and inspectable.
