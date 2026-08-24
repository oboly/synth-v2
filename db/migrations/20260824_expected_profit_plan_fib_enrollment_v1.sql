-- Issue #505: enroll the audited canonical Profit Plan/Fib cohort.
-- Boundary: market-only canonical publication scope; no account, reporting,
-- decision, execution, broker, or runtime mutation authority.
--
-- AERO, ARB, CHIP, PENDLE, and TIA are canonical Fib participants. BILL and
-- POL are deliberately absent: this migration does not widen the cohort.
-- The legacy mirror remains aligned during the publication-cohort cutover.
UPDATE asset AS a
JOIN venue_market AS vm
  ON vm.base_asset_id = a.asset_id
SET a.is_publication_cohort = 1,
    a.is_portfolio = 1
WHERE a.symbol IN ('AERO', 'ARB', 'CHIP', 'PENDLE', 'TIA')
  AND a.is_enabled = 1
  AND COALESCE(a.is_tradeable, 0) = 1
  AND vm.venue = 'bitvavo'
  AND vm.quote_currency = 'EUR'
  AND vm.is_tradeable = 1;
