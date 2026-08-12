-- #375 Phase A: additive schema only. Repository migration; do not apply
-- without separately authorized production change control.
-- Deliberately retains asset.is_portfolio for old-code compatibility.
ALTER TABLE asset
    ADD COLUMN is_publication_cohort TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Global account-agnostic canonical market publication cohort';

CREATE INDEX idx_asset_publication_cohort
    ON asset (is_publication_cohort);
