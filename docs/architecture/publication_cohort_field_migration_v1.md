# Publication Cohort Field Migration v1

Issue: #375. Repository implementation only; no production schema or data
change is authorized by this document.

`asset.is_portfolio` is the legacy compatibility name for the global,
account-agnostic publication cohort. `asset.is_publication_cohort` is the
canonical name. Neither represents `account_asset.is_portfolio_member`.

## Sequenced production procedure

1. Apply `20260812_asset_publication_cohort_additive_v1.sql` only after
   explicit production change authorization.
2. Apply `20260812_asset_publication_cohort_backfill_v1.sql` under the same
   authorization, then verify zero mismatched rows with
   `is_portfolio <=> is_publication_cohort`.
3. Deploy the dual-read repository code and observe the verified compatibility
   window. In a dual schema, every reader uses the canonical field only after a
   deterministic equality check; any mismatch raises
   `PublicationCohortCompatibilityError` and no cohort is widened.
4. After the dual-read window is verified, deploy a separately reviewed
   new-column-only cutover. Only then may a separately authorized, manual
   removal of `asset.is_portfolio` be planned. No drop migration is included:
   destructive removal must never auto-run.

The migration never derives, reads, or writes
`account_asset.is_portfolio_member`.

```text
production_apply=0
production_db_writes=0
production_schema_changes=0
production_backfill=0
old_column_drop=0
```
