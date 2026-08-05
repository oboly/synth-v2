-- Operator-invoked, exact-identity repair audit trail for
-- canonical_fib_zone_map_publication_v1.
--
-- Boundary: this table only records evidence of a completed repair. It grants
-- no privilege and is not read by any live selection/decision/execution path.
-- Repository migration only. Applying it is a separately authorized DB action.
--
-- Context: publish_publication is intentionally fail-closed -- an existing
-- (venue, quote_currency, interval_code, asof_ts_utc, map_version) identity
-- with a different content_digest raises CanonicalFibMapError and never
-- overwrites. That guard must remain the default path for ordinary
-- nondeterminism. This table exists only for the narrow, confirmed case of a
-- deterministic recomputation after a confirmed upstream data defect (e.g. a
-- feat_candle alignment bug fixed after the original publication), where an
-- operator explicitly authorizes replacing one exact, already-identified
-- invalid publication.

CREATE TABLE IF NOT EXISTS canonical_fib_zone_map_publication_repair_v1 (
    repair_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue           VARCHAR(32)  NOT NULL,
    quote_currency  VARCHAR(16)  NOT NULL,
    interval_code   VARCHAR(16)  NOT NULL,
    asof_ts_utc     DATETIME(6)  NOT NULL,
    map_version     VARCHAR(64)  NOT NULL,

    old_publication_id VARCHAR(64) NOT NULL,
    old_content_digest CHAR(64)    NOT NULL,
    new_publication_id VARCHAR(64) NOT NULL,
    new_content_digest CHAR(64)    NOT NULL,

    operator        VARCHAR(128) NOT NULL,
    reason          VARCHAR(512) NOT NULL,
    repaired_at_utc DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_canonical_fib_zone_map_publication_repair_scope (
        venue, quote_currency, interval_code, asof_ts_utc, map_version, old_content_digest
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Audit trail for operator-invoked canonical_fib_zone_map_publication_v1 identity repairs. Evidence only; grants no privilege.';
