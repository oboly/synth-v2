# Issue #399 Phase 7C automatic BUY executor LIVE readiness v1

Status: repository software readiness only. LIVE is not activated.

## Result

The existing shared #206 executor substrate is already side-neutral and
LIVE-capable for an automatic BUY handoff produced by Phase 7B. Phase 7C does
not introduce a BUY-specific executor, credential resolver, authority model,
kill switch, Bitvavo adapter, submission state machine, or reconciliation path.
Doing so would duplicate canonical executor ownership.

The canonical LIVE boundary is:

```text
exact persisted Automatic BUY shared LIVE handoff
-> exact ACTIVE TRADE_EXECUTION credential binding
   - account exact
   - venue exact
   - executor_identity exact
   - runtime_owner exact
   - allowed_order_write = true
   - allowed_withdrawal = false
-> global kill switch clear
-> exact effective finite/revocable BUY LIVE authority
   - account exact
   - venue exact
   - side = BUY
   - market exact or canonical wildcard semantics
   - executor_identity exact
   - runtime_owner exact
-> credential secret load / private client construction
-> shared submission state machine
-> shared Bitvavo adapter
-> shared reconciliation
```

Every private adapter operation re-verifies the persisted handoff, freshly
resolves credential scope, and freshly evaluates composed LIVE authority plus
the kill switch before secret loading or private-client construction. A stale,
missing, ambiguous, revoked, mismatched, withdrawal-capable, non-order-write,
non-TRADE_EXECUTION, or kill-switched state fails closed.

Existing `execution_live_authority_v1` tests own the finite/revocable authority
and global-kill-switch semantics. Existing `bitvavo_order_adapter_v1` tests own
side-neutral BUY/SELL order identity, broker acknowledgement classification,
uncertain-submission and reconciliation behavior. Phase 7C adds focused BUY
readiness evidence for the exact credential and pre-private-operation gate
ordering; it does not fork those owners.

## Readiness is not activation

No real production TRADE_EXECUTION credential is required or created to prove
software readiness. No production account flag is changed. No executor LIVE
authority grant or revocation is written. No kill-switch event is written. No
broker-write capability is enabled. No service or timer is activated. No
private broker operation or order submission is performed.

```text
production_live_trading_enabled_mutation=0
production_trade_execution_credential_creation=0
executor_live_authority_grant=0
executor_live_authority_revocation=0
kill_switch_mutation=0
broker_write_enablement=0
broker_private_calls=0
order_submission=0
service_timer_activation=0
production_migration_apply=0
production_data_seed=0
```

Production may remain fully non-LIVE throughout Phase 7C.

## Remaining path

Phase 7 repository readiness ends here. Production non-LIVE rollout and
production DRY_RUN acceptance are separate operational phases. Only after those
pass may a separately authorized pre-activation LIVE acceptance introduce real
scoped credential/configuration while submission remains hard-blocked. The
required end state before activation is:

```text
LIVE_READY=YES
LIVE_ENABLED=NO
```

Actual `live_trading_enabled`, finite authority, broker-write permission and
automatic BUY activation remain a distinct explicit operational change.
