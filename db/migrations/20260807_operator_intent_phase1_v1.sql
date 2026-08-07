-- Migration: operator_intent_phase1_v1
-- Idempotent: safe to re-run.
-- Purpose: Phase 1 (Issue #262, parent #254) canonical persistence for
--          account-scoped operator intent: current-state table plus an
--          append-only revision/audit history table.
-- Boundary: persistence + command/read layer only. No decision_gate, no
--           execution_planner, no executor, no broker calls, no orders.
--           Operator intent expresses preference, never permission.
-- Prerequisite: 20260605_website_registration_foundation_v1.sql (app_user, app_profile)
--               20260607_app_profile_trading_account_link_v1.sql (trading_account link)
--               trading_account table (pre-existing, created outside db/migrations)
-- Concurrency note: the one-open-intent-per-scope invariant is enforced in
-- src.operator_intent.operator_intent_service_v1 via a read-then-check-then-
-- insert transaction (MariaDbOperatorIntentRepository.find_open_intent_for_scope
-- uses SELECT ... FOR UPDATE). This has only been exercised against
-- sequential SQLite test transactions. True concurrent-create behavior
-- (two overlapping transactions racing to create the first open intent for
-- the same scope) MUST be verified against real MariaDB locking semantics
-- before this migration is applied to any database.

-- ---------------------------------------------------------------------------
-- 1. operator_intent
-- Current-state row per intent. Multiple rows may exist over time for the
-- same (trading_account_id, venue, canonical_market, intent_type) scope
-- (e.g. one CANCELLED and one later ACTIVE); the service layer enforces that
-- at most one OPEN-status row exists per scope at a time (not a DB
-- constraint here, matching the existing execution_ladder_leg convention of
-- resolver-enforced rather than DB-enforced cross-row invariants).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS operator_intent (
    operator_intent_id       BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,

    trading_account_id       BIGINT UNSIGNED  NOT NULL,
    venue                    VARCHAR(32)      NOT NULL,
    canonical_market         VARCHAR(32)      NOT NULL,
    intent_type              VARCHAR(32)      NOT NULL
        COMMENT 'BUY_PRIORITY | REENTRY_WATCH | BUY_LADDER_REQUESTED | SELL_LADDER_REQUESTED | HOLD_ONLY | DO_NOT_ADD | MANUAL_REVIEW_PRIORITY',

    priority                 INT              NOT NULL DEFAULT 0,
    status                   VARCHAR(32)      NOT NULL
        COMMENT 'ACTIVE | WAITING_FOR_MARKET_CONTEXT | WAITING_FOR_PERMISSION | READY_FOR_PLANNING | PLANNED_PREVIEW_AVAILABLE | BLOCKED | EXPIRED | CANCELLED | SUPERSEDED',
    reason                   VARCHAR(512)              DEFAULT NULL,
    source                   VARCHAR(64)      NOT NULL DEFAULT 'OPERATOR_MANUAL',

    created_by_app_user_id    BIGINT UNSIGNED NOT NULL,
    created_by_app_profile_id BIGINT UNSIGNED NOT NULL
        COMMENT 'Authorized profile context (not just user) that created this row. See app_user_profile_access.',
    created_ts_utc            DATETIME(6)     NOT NULL,
    updated_by_app_user_id    BIGINT UNSIGNED NOT NULL,
    updated_by_app_profile_id BIGINT UNSIGNED NOT NULL
        COMMENT 'Authorized profile context (not just user) that performed the most recent mutation.',
    updated_ts_utc            DATETIME(6)     NOT NULL,
    expires_ts_utc            DATETIME(6)              DEFAULT NULL,

    version                  INT              NOT NULL DEFAULT 1
        COMMENT 'Optimistic concurrency token. Callers must pass the version they read; mismatch fails the write.',

    supersedes_intent_id     BIGINT UNSIGNED           DEFAULT NULL
        COMMENT 'Set when this row was created by an explicit supersede command.',
    superseded_by_intent_id  BIGINT UNSIGNED           DEFAULT NULL
        COMMENT 'Set on the old row once a supersede command creates its replacement.',

    PRIMARY KEY (operator_intent_id),

    INDEX idx_operator_intent_scope (
        trading_account_id, venue, canonical_market, intent_type, status
    ),

    INDEX idx_operator_intent_account (
        trading_account_id, status
    ),

    INDEX idx_operator_intent_expiry (
        status, expires_ts_utc
    ),

    CONSTRAINT fk_operator_intent_trading_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_operator_intent_created_by
        FOREIGN KEY (created_by_app_user_id) REFERENCES app_user (app_user_id),

    CONSTRAINT fk_operator_intent_created_by_profile
        FOREIGN KEY (created_by_app_profile_id) REFERENCES app_profile (app_profile_id),

    CONSTRAINT fk_operator_intent_updated_by
        FOREIGN KEY (updated_by_app_user_id) REFERENCES app_user (app_user_id),

    CONSTRAINT fk_operator_intent_updated_by_profile
        FOREIGN KEY (updated_by_app_profile_id) REFERENCES app_profile (app_profile_id),

    CONSTRAINT fk_operator_intent_supersedes
        FOREIGN KEY (supersedes_intent_id) REFERENCES operator_intent (operator_intent_id),

    CONSTRAINT fk_operator_intent_superseded_by
        FOREIGN KEY (superseded_by_intent_id) REFERENCES operator_intent (operator_intent_id),

    CONSTRAINT chk_operator_intent_type CHECK (intent_type IN (
        'BUY_PRIORITY', 'REENTRY_WATCH', 'BUY_LADDER_REQUESTED', 'SELL_LADDER_REQUESTED',
        'HOLD_ONLY', 'DO_NOT_ADD', 'MANUAL_REVIEW_PRIORITY'
    )),

    CONSTRAINT chk_operator_intent_status CHECK (status IN (
        'ACTIVE', 'WAITING_FOR_MARKET_CONTEXT', 'WAITING_FOR_PERMISSION', 'READY_FOR_PLANNING',
        'PLANNED_PREVIEW_AVAILABLE', 'BLOCKED', 'EXPIRED', 'CANCELLED', 'SUPERSEDED'
    ))

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase 1 (#262/#254) current-state account-scoped operator intent. Preference only; grants no trading permission.';


-- ---------------------------------------------------------------------------
-- 2. operator_intent_revision
-- Append-only audit/revision history. One row per create/update/cancel/
-- supersede/expire event, capturing the full post-mutation snapshot —
-- including supersession lineage (supersedes_intent_id /
-- superseded_by_intent_id), so lineage is never left unaudited.
-- Never updated or deleted.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS operator_intent_revision (
    operator_intent_revision_id  BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,

    operator_intent_id           BIGINT UNSIGNED  NOT NULL,
    revision_version             INT              NOT NULL
        COMMENT 'The operator_intent.version produced by this event.',
    event_type                   VARCHAR(32)      NOT NULL
        COMMENT 'CREATED | UPDATED | CANCELLED | SUPERSEDED | EXPIRED',

    trading_account_id           BIGINT UNSIGNED  NOT NULL,
    venue                        VARCHAR(32)      NOT NULL,
    canonical_market              VARCHAR(32)     NOT NULL,
    intent_type                  VARCHAR(32)      NOT NULL,

    priority                     INT              NOT NULL,
    status                       VARCHAR(32)      NOT NULL,
    reason                       VARCHAR(512)              DEFAULT NULL,
    source                       VARCHAR(64)      NOT NULL,

    actor_app_user_id            BIGINT UNSIGNED  NOT NULL,
    actor_app_profile_id         BIGINT UNSIGNED  NOT NULL
        COMMENT 'Authorized profile context (not just user) that performed this event.',
    event_ts_utc                  DATETIME(6)     NOT NULL,
    expires_ts_utc                DATETIME(6)              DEFAULT NULL,

    supersedes_intent_id          BIGINT UNSIGNED          DEFAULT NULL
        COMMENT 'Snapshot of operator_intent.supersedes_intent_id at this event (constant for the life of the row).',
    superseded_by_intent_id       BIGINT UNSIGNED          DEFAULT NULL
        COMMENT 'Snapshot of operator_intent.superseded_by_intent_id at this event; set from the SUPERSEDED event onward.',

    PRIMARY KEY (operator_intent_revision_id),

    UNIQUE KEY uq_operator_intent_revision_version (operator_intent_id, revision_version),

    INDEX idx_operator_intent_revision_intent (
        operator_intent_id, event_ts_utc
    ),

    INDEX idx_operator_intent_revision_account (
        trading_account_id, event_ts_utc
    ),

    CONSTRAINT fk_operator_intent_revision_intent
        FOREIGN KEY (operator_intent_id) REFERENCES operator_intent (operator_intent_id),

    CONSTRAINT fk_operator_intent_revision_trading_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_operator_intent_revision_actor
        FOREIGN KEY (actor_app_user_id) REFERENCES app_user (app_user_id),

    CONSTRAINT fk_operator_intent_revision_actor_profile
        FOREIGN KEY (actor_app_profile_id) REFERENCES app_profile (app_profile_id),

    CONSTRAINT fk_operator_intent_revision_supersedes
        FOREIGN KEY (supersedes_intent_id) REFERENCES operator_intent (operator_intent_id),

    CONSTRAINT fk_operator_intent_revision_superseded_by
        FOREIGN KEY (superseded_by_intent_id) REFERENCES operator_intent (operator_intent_id),

    CONSTRAINT chk_operator_intent_revision_event_type CHECK (event_type IN (
        'CREATED', 'UPDATED', 'CANCELLED', 'SUPERSEDED', 'EXPIRED'
    ))

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Append-only revision/audit history for operator_intent. Never updated or deleted; does not grant permission or place orders.';
