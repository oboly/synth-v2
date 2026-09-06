-- Issue #752 Phase B1: config-driven percentage capital sleeves.
-- decision_gate-owned account policy only; no broker/order/LIVE authority.

ALTER TABLE strategy_bucket_account_config_v1
    ADD COLUMN allocation_target_pct DECIMAL(12,9) NULL AFTER source_provenance,
    ADD COLUMN allocation_max_pct DECIMAL(12,9) NULL AFTER allocation_target_pct,
    ADD CONSTRAINT chk_strategy_bucket_allocation_target_pct CHECK (
        allocation_target_pct IS NULL OR (allocation_target_pct >= 0 AND allocation_target_pct <= 1)
    ),
    ADD CONSTRAINT chk_strategy_bucket_allocation_max_pct CHECK (
        allocation_max_pct IS NULL OR (allocation_max_pct > 0 AND allocation_max_pct <= 1)
    ),
    ADD CONSTRAINT chk_strategy_bucket_allocation_target_lte_max CHECK (
        allocation_target_pct IS NULL OR allocation_max_pct IS NULL OR allocation_target_pct <= allocation_max_pct
    );
