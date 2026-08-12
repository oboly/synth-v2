-- #375 Phase B: deterministic data backfill only. Run only after the additive
-- migration and under separately authorized production change control.
-- Does not read or modify account_asset.is_portfolio_member.
UPDATE asset
SET is_publication_cohort = is_portfolio
WHERE NOT (is_publication_cohort <=> is_portfolio);
