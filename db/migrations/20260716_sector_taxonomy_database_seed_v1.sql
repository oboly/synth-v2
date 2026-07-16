-- Migration: sector_taxonomy_database_seed_v1
-- Boundary: research/data metadata only; market-only; account-agnostic.
-- No selection, decision, planning, execution, order, or broker behavior.
--
-- asset.sector remains the canonical primary narrative sector for local assets.
-- asset_profile_snapshot.sector_group_code remains reserved for empirical
-- co-movement clusters and is intentionally not referenced here.

CREATE TABLE IF NOT EXISTS sector_definition (
    sector_code         VARCHAR(64)  NOT NULL,
    display_name        VARCHAR(128) NOT NULL,
    description         TEXT         NOT NULL,
    parent_sector_code  VARCHAR(64)  NULL,
    is_active           TINYINT(1)   NOT NULL DEFAULT 1,
    sort_order          INT          NOT NULL,
    seed_schema_version VARCHAR(64)  NOT NULL,
    created_ts_utc      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                         ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (sector_code),
    KEY ix_sector_definition_active_sort (is_active, sort_order, sector_code),
    CONSTRAINT fk_sector_definition_parent
        FOREIGN KEY (parent_sector_code) REFERENCES sector_definition (sector_code),
    CONSTRAINT chk_sector_definition_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Canonical narrative sector and cross-cluster definitions. Metadata only.';

CREATE TABLE IF NOT EXISTS liquidity_market_cap_definition (
    liquidity_market_cap_code VARCHAR(32)  NOT NULL,
    display_name              VARCHAR(128) NOT NULL,
    description               TEXT         NOT NULL,
    is_active                 TINYINT(1)   NOT NULL DEFAULT 1,
    sort_order                INT          NOT NULL,
    seed_schema_version       VARCHAR(64)  NOT NULL,
    created_ts_utc            DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc            DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                               ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (liquidity_market_cap_code),
    KEY ix_liquidity_market_cap_active_sort
        (is_active, sort_order, liquidity_market_cap_code),
    CONSTRAINT chk_liquidity_market_cap_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Static reviewed liquidity/market-cap dimension; never a sector taxonomy.';

CREATE TABLE IF NOT EXISTS asset_taxonomy_profile (
    asset_symbol                VARCHAR(32) NOT NULL,
    asset_id                    INT(11)     NULL,
    liquidity_market_cap_code   VARCHAR(32) NOT NULL,
    is_enabled_universe         TINYINT(1)  NOT NULL DEFAULT 0,
    is_research_universe        TINYINT(1)  NOT NULL DEFAULT 0,
    source_symbols_json         JSON        NOT NULL,
    provenance                  VARCHAR(255) NOT NULL,
    reviewer_notes              TEXT         NULL,
    seed_schema_version         VARCHAR(64)  NOT NULL,
    updated_ts_utc              DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                 ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (asset_symbol),
    UNIQUE KEY uq_asset_taxonomy_profile_asset (asset_id),
    UNIQUE KEY uq_asset_taxonomy_profile_symbol_asset (asset_symbol, asset_id),
    KEY ix_asset_taxonomy_profile_scope
        (is_enabled_universe, is_research_universe, asset_symbol),
    KEY ix_asset_taxonomy_profile_liquidity (liquidity_market_cap_code),
    CONSTRAINT fk_asset_taxonomy_profile_asset
        FOREIGN KEY (asset_id) REFERENCES asset (asset_id),
    CONSTRAINT fk_asset_taxonomy_profile_liquidity
        FOREIGN KEY (liquidity_market_cap_code)
        REFERENCES liquidity_market_cap_definition (liquidity_market_cap_code),
    CONSTRAINT chk_asset_taxonomy_profile_enabled CHECK (is_enabled_universe IN (0, 1)),
    CONSTRAINT chk_asset_taxonomy_profile_research CHECK (is_research_universe IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='One canonical taxonomy profile per asset identity; nullable asset_id preserves research-only symbols.';

CREATE TABLE IF NOT EXISTS asset_cluster_membership (
    asset_cluster_membership_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    asset_symbol                VARCHAR(32)     NOT NULL,
    asset_id                    INT(11)         NULL,
    sector_code                 VARCHAR(64)     NOT NULL,
    membership_weight           DECIMAL(10,8)   NOT NULL,
    membership_type             VARCHAR(16)     NOT NULL,
    confidence                  DECIMAL(10,8)   NOT NULL,
    provenance                  VARCHAR(255)    NOT NULL,
    valid_from_ts_utc           DATETIME(6)     NOT NULL,
    valid_to_ts_utc             DATETIME(6)     NULL,
    reviewer_notes              TEXT            NULL,
    seed_schema_version         VARCHAR(64)     NOT NULL,

    active_membership_key VARCHAR(97)
        GENERATED ALWAYS AS (
            CASE
                WHEN valid_to_ts_utc IS NULL THEN CONCAT(asset_symbol, '|', sector_code)
                ELSE NULL
            END
        ) STORED,
    active_primary_key VARCHAR(32)
        GENERATED ALWAYS AS (
            CASE
                WHEN valid_to_ts_utc IS NULL AND membership_type = 'PRIMARY' THEN asset_symbol
                ELSE NULL
            END
        ) STORED,

    PRIMARY KEY (asset_cluster_membership_id),
    UNIQUE KEY uq_asset_cluster_membership_interval
        (asset_symbol, sector_code, valid_from_ts_utc),
    UNIQUE KEY uq_asset_cluster_membership_active (active_membership_key),
    UNIQUE KEY uq_asset_cluster_primary_active (active_primary_key),
    KEY ix_asset_cluster_membership_asset (asset_id, valid_to_ts_utc),
    KEY ix_asset_cluster_membership_sector (sector_code, valid_to_ts_utc, asset_symbol),
    CONSTRAINT fk_asset_cluster_membership_profile
        FOREIGN KEY (asset_symbol) REFERENCES asset_taxonomy_profile (asset_symbol),
    CONSTRAINT fk_asset_cluster_membership_profile_asset
        FOREIGN KEY (asset_symbol, asset_id)
        REFERENCES asset_taxonomy_profile (asset_symbol, asset_id),
    CONSTRAINT fk_asset_cluster_membership_asset
        FOREIGN KEY (asset_id) REFERENCES asset (asset_id),
    CONSTRAINT fk_asset_cluster_membership_sector
        FOREIGN KEY (sector_code) REFERENCES sector_definition (sector_code),
    CONSTRAINT chk_asset_cluster_membership_type
        CHECK (membership_type IN ('PRIMARY', 'SECONDARY')),
    CONSTRAINT chk_asset_cluster_membership_weight
        CHECK (membership_weight >= 0 AND membership_weight <= 1),
    CONSTRAINT chk_asset_cluster_membership_confidence
        CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_asset_cluster_membership_interval
        CHECK (valid_to_ts_utc IS NULL OR valid_to_ts_utc > valid_from_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Versioned primary-sector and multi-cluster memberships. Research/data metadata only.';
