# Manual Trade Execution Capability V1

Issue: #638

## Purpose

Separate **instrument identity and analysis eligibility** from **automated execution capability**.

An instrument may be held, valued, analyzed, signaled and subject to risk/exit reasoning even when Synth cannot or must not submit an automated order for it.

MDT on Bitvavo is the first production trigger, but this contract is deliberately asset-class and venue agnostic. The same model is intended for RFQ-only crypto, commodities, metals, bonds, equities/securities, OTC and broker-assisted products.

## Canonical capability

`asset.execution_mode` is one of:

- `AUTOMATED` — capability layer does not block normal automated execution; all existing decision/risk/permission/runtime gates still apply.
- `MANUAL_RFQ` — actionable analytical outcomes become `MANUAL_ACTION_REQUIRED`; automated executor handoff is not eligible.
- `MANUAL` — same manual-action disposition without assuming RFQ mechanics.
- `NONE` — monitor/value/analyze only; no executable action disposition.

Existing assets default to `AUTOMATED` so current behavior is preserved.

`execution_mode=AUTOMATED` is **not** live authority. It is only one capability prerequisite. Existing account permission, decision gate, planner, executor, kill switch and runtime gates remain authoritative.

## Operator semantics

Machine-readable:

```text
execution_mode=MANUAL_RFQ|MANUAL
manual_trade=true
execution_disposition=MANUAL_ACTION_REQUIRED
automated_execution_eligible=false
```

Operator-facing UI should show a compact `Manual Trade` indicator. Venue-specific details such as RFQ may appear in expanded detail/evidence views.

## Snapshot semantics

Canonical asset identity does not require an automated `venue_market`.

The exact-account position snapshot path reads `asset.execution_mode` and records capability in position `raw_json`. A manual instrument can therefore be represented in a COMPLETE account-state bundle even when no automated venue market exists.

Missing mark price is not the same as missing holding identity. If no canonical market candle exists, `mark_price_eur` may be NULL while the positive holding remains represented.

Unknown asset identity still fails closed. The snapshot writer does not auto-create arbitrary broker-returned symbols.

## Controlled identity registration

`src.market.run_manual_trade_asset_registration_v1` registers an `asset` identity with `MANUAL_RFQ` or `MANUAL` capability.

It is dry-run by default. `--apply` requires operator + reason and writes only the `asset` table. It never creates or mutates `venue_market`.

This prevents an RFQ/manual product from being misrepresented as a normal CLOB/Pro market merely to make account-state persistence pass.

## Manual action routing

`route_action_by_execution_capability_v1()` preserves the analytical action (`BUY`, `SELL`, `REDUCE`, `EXIT`, etc.) while deriving execution disposition.

For manual modes:

```text
action=SELL
execution_disposition=MANUAL_ACTION_REQUIRED
manual_trade=true
automated_order_submission=false
```

The pure router imports neither broker nor executor code and grants no authority.

## Safety invariants

```text
manual_trade != automated_trade_permission
execution_mode=AUTOMATED != live_authority
broker_writes=0 from capability/manual-action modules
order_submission=0 from capability/manual-action modules
venue_market_writes=0 from manual asset registration
kill_switch_bypass=0
executor_bypass=0
```

## Production sequencing for MDT

Repository implementation and migration merge first.

Production DB changes remain separate explicit mutations:

1. apply `20260831_asset_execution_mode_v1.sql`;
2. dry-run manual asset registration for MDT;
3. explicitly authorize/apply MDT as `asset_class=CRYPTO`, `execution_mode=MANUAL_RFQ`;
4. verify no `MDT-EUR` venue_market was fabricated;
5. rerun exact account-state refresh `--write-db` under its separately authorized bounded private-read contract;
6. verify COMPLETE bundle includes MDT with `manual_trade=true` and `automated_execution_eligible=false`.

UI/manual notification wiring may evolve independently as long as it consumes the same capability contract and cannot reach automated order submission for manual modes.
