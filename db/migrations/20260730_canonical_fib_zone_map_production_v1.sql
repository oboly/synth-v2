-- Production publication contract for canonical_fib_zone_map_v1.
-- Repository migration only. Applying it is a separately authorized DB action.

CREATE TABLE IF NOT EXISTS canonical_fib_zone_map_publication_v1 (
    publication_id VARCHAR(64) NOT NULL PRIMARY KEY,
    venue VARCHAR(32) NOT NULL,
    quote_currency VARCHAR(16) NOT NULL,
    interval_code VARCHAR(16) NOT NULL,
    asof_ts_utc DATETIME(6) NOT NULL,
    map_version VARCHAR(64) NOT NULL,
    content_digest CHAR(64) NOT NULL,
    row_count INT UNSIGNED NOT NULL,
    available_count INT UNSIGNED NOT NULL,
    producer_name VARCHAR(96) NOT NULL,
    producer_version VARCHAR(32) NOT NULL,
    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_canonical_fib_zone_map_publication_scope (
        venue, quote_currency, interval_code, asof_ts_utc, map_version
    ),
    UNIQUE KEY uq_canonical_fib_zone_map_publication_digest (
        venue, quote_currency, interval_code, content_digest
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Atomic publication cohorts for canonical market-only FibNavigationMap rows.';

ALTER TABLE canonical_fib_zone_map_v1
    ADD COLUMN IF NOT EXISTS publication_id VARCHAR(64) NULL AFTER map_id,
    ADD COLUMN IF NOT EXISTS reference_price DECIMAL(30,12) NULL AFTER source_created_at_utc,
    ADD INDEX IF NOT EXISTS idx_canonical_fib_zone_map_publication (publication_id),
    ADD CONSTRAINT fk_canonical_fib_zone_map_publication
        FOREIGN KEY (publication_id)
        REFERENCES canonical_fib_zone_map_publication_v1 (publication_id);

CREATE OR REPLACE VIEW canonical_fib_zone_map_latest_v1 AS
SELECT m.*, p.quote_currency, p.content_digest,
       p.created_at_utc AS publication_ts_utc
FROM canonical_fib_zone_map_v1 m
JOIN canonical_fib_zone_map_publication_v1 p
  ON p.publication_id = m.publication_id
JOIN (
    SELECT venue, quote_currency, interval_code, map_version, MAX(asof_ts_utc) AS max_asof_ts_utc
    FROM canonical_fib_zone_map_publication_v1
    GROUP BY venue, quote_currency, interval_code, map_version
) latest
  ON latest.venue = p.venue
 AND latest.quote_currency = p.quote_currency
 AND latest.interval_code = p.interval_code
 AND latest.map_version = p.map_version
 AND latest.max_asof_ts_utc = p.asof_ts_utc;
