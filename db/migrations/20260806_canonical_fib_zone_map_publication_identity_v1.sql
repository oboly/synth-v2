-- Migration: canonical_fib_zone_map_v1 child-row identity repair.
-- Repository migration only. Applying it is a separately authorized DB action.
--
-- Root cause of the 20:00Z publication IntegrityError (1062, duplicate entry
-- on uq_canonical_fib_zone_map_v1): canonical_fib_zone_map_v1.asof_ts_utc was
-- written as the row's own source-candle timestamp
-- (input_latest_candle_ts_utc) rather than the publication's asof_ts_utc, and
-- the unique key did not include publication_id. A symbol whose source
-- candle stays stale across two consecutive, legitimate publication cohorts
-- (e.g. NOT still sourced from 16:00 data at the 20:00 publication) then
-- produced the exact same (venue, symbol, interval_code, asof_ts_utc,
-- map_version) tuple as its own row from the prior cohort.
--
-- Intended identity model (confirmed against canonical_fib_zone_map_latest_v1,
-- which already selects "current" by publication_id/publication asof, never
-- by row-level asof_ts_utc): each publication is an immutable cohort with
-- exactly one row per symbol.
--   - row.asof_ts_utc            = publication build asof (this migration's
--                                   companion code fix in
--                                   insert_publication_cohort now enforces this)
--   - row.input_latest_candle_ts_utc = source candle freshness, unchanged
--   - row.publication_id         = the owning cohort
--
-- This migration makes that identity explicit at the schema level: child-row
-- uniqueness is (venue, symbol, interval_code, publication_id, map_version)
-- instead of keying on asof_ts_utc directly. This does not merely rely on the
-- cross-table invariant that publication_id 1:1-maps to a unique
-- (venue, quote_currency, interval_code, asof_ts_utc, map_version) in
-- canonical_fib_zone_map_publication_v1 (enforced by
-- uq_canonical_fib_zone_map_publication_scope) -- it states the child-row
-- identity directly, so two different publication cohorts for the same
-- symbol can never collide regardless of what asof_ts_utc value either one
-- carries.
--
-- Pre-migration validation (run manually, expect zero rows before applying):
--   SELECT venue, symbol, interval_code, publication_id, map_version, COUNT(*)
--   FROM canonical_fib_zone_map_v1
--   GROUP BY venue, symbol, interval_code, publication_id, map_version
--   HAVING COUNT(*) > 1;
--
-- Rollback (reverts to the pre-migration key; only safe if no rows have been
-- inserted since that would violate the old, looser key):
--   ALTER TABLE canonical_fib_zone_map_v1
--       DROP INDEX uq_canonical_fib_zone_map_v1,
--       ADD UNIQUE KEY uq_canonical_fib_zone_map_v1 (
--           venue, symbol, interval_code, asof_ts_utc, map_version
--       );

ALTER TABLE canonical_fib_zone_map_v1
    DROP INDEX uq_canonical_fib_zone_map_v1,
    ADD UNIQUE KEY uq_canonical_fib_zone_map_v1 (
        venue, symbol, interval_code, publication_id, map_version
    );
