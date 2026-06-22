-- Migration: ffg_flow_snapshot_ingest
-- Boundary: research-only · market-only · append-only flow history
--           no asset/account/order/broker/runtime writes
--
-- Purpose:
--   1. Preserve raw FFG HTML/TEXT artifacts by content hash.
--   2. Store append-only structured flow snapshots per artifact and list scope.
--   3. Store per-symbol flow observations per parsed snapshot.
--
-- Notes:
--   - Exact artifact re-upload is idempotent via (source_name, content_sha256).
--   - Different content hashes create new append-only history rows.
--   - Count mismatches between reported and visible rows are warnings, not failures.
--   - Existing ffg_external_signal_snapshot_v1 remains unchanged and is not reused here.

CREATE TABLE IF NOT EXISTS external_research_artifact (
    artifact_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    source_name VARCHAR(32) NOT NULL COMMENT 'Fixed FFG for this ingest lane',
    artifact_kind VARCHAR(16) NOT NULL COMMENT 'HTML | TEXT',
    original_filename VARCHAR(255) NOT NULL DEFAULT '',
    content_sha256 CHAR(64) NOT NULL,
    raw_content LONGTEXT NOT NULL COMMENT 'Preserved raw HTML or text content',

    source_observed_label VARCHAR(255) DEFAULT NULL COMMENT 'Optional source-side label preserved as text only',
    source_observed_at_utc DATETIME(6) DEFAULT NULL COMMENT 'Only when explicitly supplied by operator',
    ingested_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    parser_version VARCHAR(64) NOT NULL,
    parse_status VARCHAR(32) NOT NULL COMMENT 'PARSED_OK | PARSED_WITH_WARNINGS',
    parse_warning_json JSON DEFAULT NULL COMMENT 'Structured warning list for mismatches and unresolved identities',

    UNIQUE KEY uq_external_research_artifact_sha (source_name, content_sha256),
    KEY idx_external_research_artifact_ingested (source_name, ingested_at_utc),

    CONSTRAINT chk_external_research_artifact_source
        CHECK (source_name = 'FFG'),
    CONSTRAINT chk_external_research_artifact_kind
        CHECK (artifact_kind IN ('HTML', 'TEXT')),
    CONSTRAINT chk_external_research_artifact_status
        CHECK (parse_status IN ('PARSED_OK', 'PARSED_WITH_WARNINGS'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Preserved raw external FFG research artifacts keyed by content hash. Research-only.';


CREATE TABLE IF NOT EXISTS external_research_flow_snapshot (
    snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    artifact_id BIGINT UNSIGNED NOT NULL,
    source_name VARCHAR(32) NOT NULL COMMENT 'Fixed FFG for this ingest lane',
    universe_key VARCHAR(64) DEFAULT NULL COMMENT 'FFG_RESEARCH_UNIVERSE_V1 for FFG_LIST, NULL otherwise',
    list_scope VARCHAR(32) NOT NULL COMMENT 'FFG_LIST | OUTSIDE_FFG_RADAR',
    normalized_timeframe VARCHAR(64) NOT NULL DEFAULT 'UNVERIFIED_BETA',
    source_confidence VARCHAR(16) NOT NULL DEFAULT 'low',
    source_status VARCHAR(32) NOT NULL DEFAULT 'BETA_UNVERIFIED',

    reported_inflow_count INT DEFAULT NULL,
    parsed_inflow_count INT NOT NULL DEFAULT 0,
    reported_outflow_count INT DEFAULT NULL,
    parsed_outflow_count INT NOT NULL DEFAULT 0,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_external_research_flow_snapshot (artifact_id, list_scope),
    KEY idx_external_research_flow_snapshot_scope (source_name, list_scope, created_at_utc),
    KEY idx_external_research_flow_snapshot_universe (universe_key),

    CONSTRAINT fk_external_research_flow_snapshot_artifact
        FOREIGN KEY (artifact_id) REFERENCES external_research_artifact (artifact_id),
    CONSTRAINT chk_external_research_flow_snapshot_source
        CHECK (source_name = 'FFG'),
    CONSTRAINT chk_external_research_flow_snapshot_scope
        CHECK (list_scope IN ('FFG_LIST', 'OUTSIDE_FFG_RADAR')),
    CONSTRAINT chk_external_research_flow_snapshot_timeframe
        CHECK (normalized_timeframe = 'UNVERIFIED_BETA'),
    CONSTRAINT chk_external_research_flow_snapshot_confidence
        CHECK (source_confidence = 'low'),
    CONSTRAINT chk_external_research_flow_snapshot_status
        CHECK (source_status = 'BETA_UNVERIFIED')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only external FFG flow snapshots per artifact and list scope.';


CREATE TABLE IF NOT EXISTS external_research_flow_observation (
    observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    snapshot_id BIGINT UNSIGNED NOT NULL,
    source_symbol VARCHAR(32) NOT NULL,
    raw_display_name VARCHAR(255) DEFAULT NULL,
    direction VARCHAR(16) NOT NULL COMMENT 'INFLOW | OUTFLOW',
    change_pct DECIMAL(12,4) DEFAULT NULL,
    reported_flow_usd DECIMAL(20,4) DEFAULT NULL,
    rank_in_section INT NOT NULL,
    peak_flag TINYINT(1) NOT NULL DEFAULT 0,
    active_alert_flag TINYINT(1) NOT NULL DEFAULT 0,
    identity_status VARCHAR(32) NOT NULL
        COMMENT 'FFG_UNIVERSE_RESOLVED | OUTSIDE_RADAR_UNRESOLVED | AMBIGUOUS | UNRESOLVED',
    ffg_universe_member_id BIGINT UNSIGNED DEFAULT NULL,
    asset_id INT(11) DEFAULT NULL,

    created_at_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    UNIQUE KEY uq_external_research_flow_observation (snapshot_id, source_symbol),
    KEY idx_external_research_flow_observation_direction (snapshot_id, direction, rank_in_section),
    KEY idx_external_research_flow_observation_identity (identity_status, source_symbol),
    KEY idx_external_research_flow_observation_member (ffg_universe_member_id),
    KEY idx_external_research_flow_observation_asset (asset_id),

    CONSTRAINT fk_external_research_flow_observation_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES external_research_flow_snapshot (snapshot_id),
    CONSTRAINT chk_external_research_flow_observation_direction
        CHECK (direction IN ('INFLOW', 'OUTFLOW')),
    CONSTRAINT chk_external_research_flow_observation_identity
        CHECK (identity_status IN (
            'FFG_UNIVERSE_RESOLVED',
            'OUTSIDE_RADAR_UNRESOLVED',
            'AMBIGUOUS',
            'UNRESOLVED'
        ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Per-symbol append-only FFG flow observations. Exact artifact replay reuses the artifact and creates no duplicate observations.';
