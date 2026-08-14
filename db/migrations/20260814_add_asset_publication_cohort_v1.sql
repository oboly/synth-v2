-- Issue #375 Phase A only: additive schema compatibility step.
-- Manual production apply requires separate explicit authorization.
ALTER TABLE asset
    ADD COLUMN is_publication_cohort TINYINT(1) NOT NULL DEFAULT 0
    COMMENT 'Global account-agnostic canonical market publication cohort';
