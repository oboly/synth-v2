# Issue #456 automatic BUY asset FK compatibility

Production inventory on 2026-08-20 confirmed:

```text
trading_account.trading_account_id = bigint(20) unsigned
asset.asset_id = int(11)
executor_credential_binding.executor_credential_binding_id = bigint(20) unsigned
```

The unapplied migration `20260819_automatic_buy_runtime_v1.sql` previously declared both automatic BUY `asset_id` foreign-key columns as `BIGINT UNSIGNED`, which is incompatible with the production `asset.asset_id INT(11)` parent key.

This repository correction changes only those two unapplied child columns to signed `INT` so the foreign keys match production exactly.

No production migration has been applied as part of this change. No data, credentials, LIVE authority, kill-switch state, service/timer state, broker capability, or order state is mutated.

After merge, Issue #456 Stage A may resume from the read-only inventory and apply the reviewed migration set in dependency order.
