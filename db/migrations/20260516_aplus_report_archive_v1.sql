-- A+ report archive and parsed Table 1 / Table 2 storage.
--
-- Boundary:
-- - Research/data archive only.
-- - No strategy, selection, advice, decision, execution, broker, or order logic.

CREATE TABLE IF NOT EXISTS aplus_report_file_archive (
    aplus_report_file_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_file_path VARCHAR(512) NOT NULL,
    content_hash_sha256 CHAR(64) NOT NULL,
    report_type VARCHAR(64) NOT NULL,
    prediction_ts_utc DATETIME(6) NULL,
    parse_status VARCHAR(64) NOT NULL,
    parse_reason TEXT NULL,
    byte_size BIGINT UNSIGNED NOT NULL,
    archived_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (aplus_report_file_id),
    UNIQUE KEY uq_aplus_report_file_path (source_file_path),
    KEY ix_aplus_report_file_hash (content_hash_sha256),
    KEY ix_aplus_report_file_type_ts (report_type, prediction_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS aplus_table1_report (
    aplus_table1_report_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    aplus_report_file_id BIGINT UNSIGNED NULL,
    source_file_path VARCHAR(512) NOT NULL,
    prediction_ts_utc DATETIME(6) NOT NULL,
    parser_version VARCHAR(32) NOT NULL,
    row_count INT UNSIGNED NOT NULL,
    expected_token_count INT UNSIGNED NOT NULL,
    missing_tokens_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL
        CHECK (JSON_VALID(missing_tokens_json)),
    duplicate_tokens_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL
        CHECK (JSON_VALID(duplicate_tokens_json)),
    same_snapshot_ts TINYINT(1) NULL,
    timestamp_mismatch_minutes DECIMAL(10,2) NULL,
    pair_reference_ts_utc DATETIME(6) NULL,
    paired_table2_report_id BIGINT UNSIGNED NULL,
    loaded_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (aplus_table1_report_id),
    UNIQUE KEY uq_aplus_table1_report_ts (prediction_ts_utc),
    KEY ix_aplus_table1_file (aplus_report_file_id),
    KEY ix_aplus_table1_pair (paired_table2_report_id),
    CONSTRAINT fk_aplus_table1_report_file
        FOREIGN KEY (aplus_report_file_id)
        REFERENCES aplus_report_file_archive (aplus_report_file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS aplus_table1_row (
    aplus_table1_row_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    aplus_table1_report_id BIGINT UNSIGNED NOT NULL,
    token VARCHAR(32) NOT NULL,
    phase VARCHAR(64) NULL,
    coherence VARCHAR(64) NULL,
    field VARCHAR(64) NULL,
    geometry VARCHAR(64) NULL,
    structural_role VARCHAR(64) NULL,
    expansion_quality VARCHAR(64) NULL,
    anchor_strength VARCHAR(64) NULL,
    strategic_bias VARCHAR(64) NULL,
    notes TEXT NULL,
    validation_status VARCHAR(64) NOT NULL DEFAULT 'VALID',
    PRIMARY KEY (aplus_table1_row_id),
    UNIQUE KEY uq_aplus_table1_row_report_token (aplus_table1_report_id, token),
    KEY ix_aplus_table1_row_token (token),
    CONSTRAINT fk_aplus_table1_row_report
        FOREIGN KEY (aplus_table1_report_id)
        REFERENCES aplus_table1_report (aplus_table1_report_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS aplus_table2_report (
    aplus_table2_report_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    aplus_report_file_id BIGINT UNSIGNED NULL,
    source_file_path VARCHAR(512) NOT NULL,
    prediction_ts_utc DATETIME(6) NOT NULL,
    parser_version VARCHAR(32) NOT NULL,
    row_count INT UNSIGNED NOT NULL,
    expected_token_count INT UNSIGNED NOT NULL,
    missing_tokens_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL
        CHECK (JSON_VALID(missing_tokens_json)),
    duplicate_tokens_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL
        CHECK (JSON_VALID(duplicate_tokens_json)),
    same_snapshot_ts TINYINT(1) NULL,
    timestamp_mismatch_minutes DECIMAL(10,2) NULL,
    pair_reference_ts_utc DATETIME(6) NULL,
    paired_table1_report_id BIGINT UNSIGNED NULL,
    loaded_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (aplus_table2_report_id),
    UNIQUE KEY uq_aplus_table2_report_ts (prediction_ts_utc),
    KEY ix_aplus_table2_file (aplus_report_file_id),
    KEY ix_aplus_table2_pair (paired_table1_report_id),
    CONSTRAINT fk_aplus_table2_report_file
        FOREIGN KEY (aplus_report_file_id)
        REFERENCES aplus_report_file_archive (aplus_report_file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS aplus_table2_row (
    aplus_table2_row_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    aplus_table2_report_id BIGINT UNSIGNED NOT NULL,
    token VARCHAR(32) NOT NULL,
    harmonic_phase VARCHAR(64) NULL,
    phase_state VARCHAR(64) NULL,
    offset_band VARCHAR(64) NULL,
    drift_direction VARCHAR(64) NULL,
    quality VARCHAR(64) NULL,
    extension_risk VARCHAR(64) NULL,
    notes TEXT NULL,
    validation_status VARCHAR(64) NOT NULL DEFAULT 'VALID',
    PRIMARY KEY (aplus_table2_row_id),
    UNIQUE KEY uq_aplus_table2_row_report_token (aplus_table2_report_id, token),
    KEY ix_aplus_table2_row_token (token),
    CONSTRAINT fk_aplus_table2_row_report
        FOREIGN KEY (aplus_table2_report_id)
        REFERENCES aplus_table2_report (aplus_table2_report_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
