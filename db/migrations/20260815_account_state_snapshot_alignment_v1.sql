-- Phase 4B prerequisite: one append-only aligned account-state evidence run.
-- COMPLETE is emitted only after the wallet producer has persisted position,
-- balance, and COMPLETE open-order evidence for this exact account/venue/refresh.

CREATE TABLE IF NOT EXISTS account_state_snapshot_run_v1 (
    account_state_snapshot_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trading_account_id BIGINT UNSIGNED NOT NULL,
    venue VARCHAR(32) NOT NULL,
    source_name VARCHAR(96) NOT NULL,
    refresh_started_ts_utc DATETIME(6) NOT NULL,
    snapshot_ts_utc DATETIME(6) NOT NULL,
    completed_ts_utc DATETIME(6) NOT NULL,
    run_state VARCHAR(32) NOT NULL,
    position_source_name VARCHAR(96) NOT NULL,
    position_snapshot_count INT UNSIGNED NOT NULL,
    balance_source_name VARCHAR(96) NOT NULL,
    balance_snapshot_count INT UNSIGNED NOT NULL,
    account_open_order_snapshot_run_id BIGINT UNSIGNED NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (account_state_snapshot_run_id),
    UNIQUE KEY uq_account_state_snapshot_run_identity (
        trading_account_id, venue, source_name, snapshot_ts_utc
    ),
    KEY ix_account_state_snapshot_run_latest (
        trading_account_id, venue, snapshot_ts_utc
    ),
    CONSTRAINT fk_account_state_snapshot_run_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT fk_account_state_snapshot_run_open_order
        FOREIGN KEY (account_open_order_snapshot_run_id)
        REFERENCES account_open_order_snapshot_run_v1 (account_open_order_snapshot_run_id),
    CONSTRAINT chk_account_state_snapshot_run_complete
        CHECK (run_state = 'COMPLETE'),
    CONSTRAINT chk_account_state_snapshot_run_counts
        CHECK (position_snapshot_count >= 0 AND balance_snapshot_count >= 0),
    CONSTRAINT chk_account_state_snapshot_run_timestamps
        CHECK (completed_ts_utc >= refresh_started_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only aligned account evidence. COMPLETE requires exact same-refresh position, balance, and COMPLETE open-order components; automatic exit consumes COMPLETE only.';
