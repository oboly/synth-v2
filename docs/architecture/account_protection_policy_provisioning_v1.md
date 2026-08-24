# Account protection policy provisioning v1

Issue #504 owns the canonical write path for the immutable,
account-scoped `account_protection_policy_config_v1` contract. The owner is
`decision_gate`: policy provisioning is account configuration, not market
selection, execution planning, or order handling.

## API and operator interface

`src.decision_gate.account_protection_policy_provisioning_v1` exposes the
typed `AccountProtectionPolicyProvisioningRequestV1` and its sole writer,
`provision_account_protection_policy_v1`. The CLI is:

```bash
python -m src.decision_gate.run_account_protection_policy_provisioning_v1 --help
```

The operator supplies `--account-code` and `--venue`; neither the CLI nor its
arguments accept or print a raw `trading_account_id`. The writer resolves
exactly one matching `trading_account` row. Zero matches is
`UNKNOWN_TRADING_ACCOUNT`; more than one match is
`AMBIGUOUS_TRADING_ACCOUNT_IDENTITY`. Both reject before a policy write.

The policy input is explicit and versioned: config version, configuration
version, all three metric choices, metric age, UTC-effective window, and
source provenance are required. Every metric must use either its positive
threshold option or its explicit `--disable-...` option. An explicitly neutral
policy (all three disabled) is contractually valid: it keeps missing
configuration fail-closed while allowing only persisted account-protection
facts to govern the evaluator.

## Validation and lifecycle

The writer validates all text bounds, supported contract version, finite
positive decimal thresholds, positive streak threshold, non-negative metric
age, and a timezone-aware strict effective window. It normalizes both window
timestamps to UTC before it compares or writes them, because MariaDB
`DATETIME` does not preserve an offset.

Policy rows are append-only. The writer uses the existing
`resolve_account_protection_policy_v1` contract unchanged to validate the
candidate and existing history. It never updates or deletes a policy row or a
revocation fact. Exact same-value reruns are idempotent and return the
existing row; differing or overlapping requests fail closed. This prevents a
new row from creating an immediately or future-ambiguous effective policy.

Missing policy configuration remains unresolved and therefore remains
`BLOCKED / PROTECTION_CONFIGURATION_UNRESOLVED` in the existing #318
evaluator. Provisioning does not grant LIVE permission, create a decision,
construct a broker client, or submit an order.

## Production boundary

This repository feature authorizes no production mutation. A later production
invocation requires separately reviewed account identity and exact policy
values. It must not be replaced by direct SQL seeding.

```text
repository_phase_production_db_mutation=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
