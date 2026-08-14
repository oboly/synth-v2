-- Issue #375 Phase B only: deterministic backfill after the additive step.
-- Manual production apply requires separate explicit authorization.
UPDATE asset
SET is_publication_cohort = is_portfolio;
