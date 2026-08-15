# Automatic BUY entry policy V1 (Issue #399 Phase 1)

Phase 1 only: the market-only, account-agnostic automatic BUY/re-entry
candidate contract. Phases 2-7 of Issue #399 (`decision_gate` BUY permission
and allocation, the `execution_planner` BUY ladder, runtime/persistence,
DRY_RUN/PAPER acceptance, shared executor integration, and separately
authorized LIVE activation) are out of scope for this document and are not
implemented here.

## Boundary

```text
selection / signal / advice evidence (already decided setup readiness)
-> entry_policy.automatic_buy_candidate_v1
-> decision_gate account permission/allocation/conflict validation   (Issue #399 Phase 2, not built)
-> execution_planner immutable BUY ladder                            (Issue #399 Phase 3, not built)
-> executor                                                          (Issue #399 Phase 6, not built)
```

`selection_engine` remains market-only and account-agnostic. This module
does not read balances, positions, orders, account settings, API keys, or
broker state, and does not decide account permission. It never writes state,
builds a broker payload, resolves a base quantity/notional, constructs a
ladder, or bypasses `decision_gate`.

## Existing-contract audit (why a new module)

Issue #399 Phase 1 requires preferring an existing canonical
`StrategyProposal`/selection output over inventing a parallel strategy-truth
model. Two existing contracts were evaluated:

- `src.advice_route.interfaces_v1.StrategyProposal` is the closest
  existing contract by name and already enforces account-agnosticism
  (`account_awareness=False`, `broker_write_allowed=False`,
  `order_submission=False`, `decision_required=True`) via
  `validate_forbidden_fields_absent`. It is a general multi-action
  (`BUY`/`SELL`/`HOLD`/`ROTATE`/`WARN`) paper-advice interpretation contract
  keyed on a single `symbol`, versioned by `route_version` (the advice-route
  schema version, not a strategy identity/version), with no explicit
  numeric staleness bound. It was not reused in place because doing so would
  either widen a paper-advice-interpretation contract to carry BUY-lane
  identity/freshness semantics it was not designed for, or require
  subclassing a frozen dataclass.
- `src.selection.selection_engine_v2.SelectionCandidate`/`SelectionRow`
  confirm `selection_engine` is genuinely market-only, but are raw
  multi-interval ranking-score rows, not an entry-candidate contract with
  entry/re-entry zone context or evidence/provenance ids.

Neither binds the exact minimum field set Issue #399 Phase 1 requires
without reshaping an unrelated layer's contract. This module therefore
defines a new, narrowly-scoped BUY-only candidate under `src/entry_policy/`
(mirroring `src/exit_policy/`'s naming and structural pattern), and reuses
the *pattern* of `advice_route.interfaces_v1.validate_forbidden_fields_absent`
as a local, BUY-lane-specific forbidden-field-substring guard rather than
importing and mutating the shared paper-advice module. Like
`automatic_exit_candidate_v1`, it consumes an already-decided market-only
`strategy_id`/`strategy_version`/`setup_id` and entry/re-entry zone context
as explicit input; it does not rank markets, score setups, or recompute
strategy logic, so it does not create a parallel source of strategy truth.

## V1 contract

`evaluate_automatic_buy_candidate_v1` takes an explicit
`AutomaticBuySetupContextV1` market-only observation plus an explicit
evaluation timestamp. It returns exactly one of:

- `NO_ACTION`: the setup is not yet ready, or no entry/re-entry zone
  condition is currently met.
- `NON_ACTIONABLE`: identity/evidence is missing, price or zone bounds are
  invalid, timestamps are naive, policy config is unsafe, or the setup
  context is stale.
- `CANDIDATE`: a typed `ENTER` or `RE_ENTER` candidate carrying only
  venue/market/asset identity, strategy identity/version, setup identity,
  the entry zone bounds, evidence id, and an observed timestamp.

`AutomaticBuySetupContextV1` binds the Issue #399 Phase 1 minimum field set:

```text
venue, market                    -> venue + market
strategy_id, strategy_version    -> strategy identity/version
setup_id                         -> setup identity
observed_ts_utc (+ evaluation_ts_utc, max_setup_context_age_seconds)
                                  -> asof/freshness
entry_zone_low/high,
re_entry_zone_low/high           -> desired entry/re-entry market context
evidence_id                      -> evidence/provenance
```

`AutomaticBuyCandidateV1` carries the same identity/evidence fields plus the
decided `candidate_action` and `reason_code`; it never carries a quantity,
notional, or price other than the entry-zone bounds it was evaluated
against.

## Account-agnosticism

`FORBIDDEN_FIELD_SUBSTRINGS` and `validate_no_account_or_broker_fields` fail
closed (raise `ValueError`) if any bound field name on
`AutomaticBuySetupContextV1`, `AutomaticBuyPolicyConfigV1`,
`AutomaticBuyCandidateV1`, or `AutomaticBuyEvaluationV1` contains an
account, balance, wallet, allocation, sizing, credential, or broker
substring (including the literal terms Issue #399 names: `trading_account_id`,
`balance`, `wallet`, `allocation`, `permitted_quantity`, `position_size`,
`credential`, `broker`). The module calls this validator on its own
dataclasses at import time, so a future edit that adds a forbidden field
fails the import immediately rather than silently shipping an
account-aware candidate. `tests/test_automatic_buy_candidate_v1.py` proves
this both by field-name inspection and by constructing locally-defined
dataclasses with forbidden field names and asserting the validator rejects
them.

## Freshness and fail-closed behavior

Freshness defaults to fifteen minutes (`max_setup_context_age_seconds`,
mirroring `automatic_exit_candidate_v1`'s default). The explicit
`evaluation_ts_utc` parameter makes same-input/same-output deterministic.
All timestamps must be timezone-aware UTC instants; naive timestamps fail
closed to `NON_ACTIONABLE`/`NAIVE_TIMESTAMP`. Missing identity/evidence,
non-positive price, or an inverted/non-positive zone bound fails closed to
`NON_ACTIONABLE`/`INVALID_SETUP_CONTEXT`. A stale setup context fails closed
to `NON_ACTIONABLE`/`SETUP_CONTEXT_STALE`. A not-yet-ready setup is the
common per-cycle state and is `NO_ACTION`/`SETUP_NOT_READY`, not an error.
