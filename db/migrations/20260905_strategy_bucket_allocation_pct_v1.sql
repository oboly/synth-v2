-- Issue #752: extend #279's strategy_bucket_account_config_v1 with the
-- percentage-of-account-equity allocation fields it does not yet carry.
-- Migration artifact only; do not apply from this change.
--
-- #279 already owns absolute EUR ceilings (max_position_amount_eur,
-- max_bucket_amount_eur) and a per-asset exposure percentage
-- (max_asset_exposure_pct). It has no percentage-of-NAV bucket allocation
-- concept at all. This migration adds exactly that, without touching any
-- existing column, constraint, or the table's append-only/immutable
-- triggers (defined in 20260819_strategy_bucket_account_config_v1.sql and
-- untouched here).
--
-- allocation_target_pct: advisory target only. Never forces deployment;
--   decision_gate reads it as informational context, not a floor.
-- allocation_max_pct: hard percentage-of-account-equity ceiling for this
--   bucket. Combined with max_bucket_amount_eur (if configured) via
--   effective_bucket_ceiling = MIN(equity * allocation_max_pct,
--   max_bucket_amount_eur) -- computed in Python
--   (src/decision_gate/strategy_bucket_capacity_v1.py), not in SQL, since
--   equity is a runtime fact, not a config-time constant.
-- max_position_pct_of_bucket: optional per-position ceiling expressed as a
--   fraction of this bucket's own effective ceiling, alongside (not
--   replacing) the existing absolute max_position_amount_eur.
--
-- All three columns are nullable so every existing/pre-#752 config row
-- remains valid without a backfill: NULL allocation_target_pct/
-- allocation_max_pct means "no percentage-of-equity policy configured for
-- this row" and the effective bucket ceiling then reduces to the existing
-- #279 absolute max_bucket_amount_eur/max_position_amount_eur behavior
-- unchanged (see strategy_bucket_capacity_v1.py). This is the documented
-- backward-compatibility contract for #279 rows created before #752.

ALTER TABLE strategy_bucket_account_config_v1
    ADD COLUMN allocation_target_pct DECIMAL(9,6) NULL
        COMMENT 'Issue #752: advisory target fraction of account equity for this bucket (0-1). Never forces deployment.'
        AFTER risk_profile,
    ADD COLUMN allocation_max_pct DECIMAL(9,6) NULL
        COMMENT 'Issue #752: hard ceiling fraction of account equity for this bucket (0-1). Combined with max_bucket_amount_eur via MIN() in Python.'
        AFTER allocation_target_pct,
    ADD COLUMN max_position_pct_of_bucket DECIMAL(9,6) NULL
        COMMENT 'Issue #752: optional per-position ceiling as a fraction of this bucket''s own effective ceiling (0-1).'
        AFTER allocation_max_pct;

ALTER TABLE strategy_bucket_account_config_v1
    ADD CONSTRAINT chk_strategy_bucket_account_config_allocation_target_pct CHECK (
        allocation_target_pct IS NULL OR (allocation_target_pct >= 0 AND allocation_target_pct <= 1)
    ),
    ADD CONSTRAINT chk_strategy_bucket_account_config_allocation_max_pct CHECK (
        allocation_max_pct IS NULL OR (allocation_max_pct >= 0 AND allocation_max_pct <= 1)
    ),
    ADD CONSTRAINT chk_strategy_bucket_account_config_allocation_target_le_max CHECK (
        allocation_target_pct IS NULL OR allocation_max_pct IS NULL
        OR allocation_target_pct <= allocation_max_pct
    ),
    ADD CONSTRAINT chk_strategy_bucket_account_config_max_position_pct_of_bucket CHECK (
        max_position_pct_of_bucket IS NULL
        OR (max_position_pct_of_bucket > 0 AND max_position_pct_of_bucket <= 1)
    );
