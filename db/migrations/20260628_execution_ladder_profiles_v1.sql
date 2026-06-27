-- Migration: execution_ladder_profiles_v1
-- Boundary: schema + reference seeds only · no broker writes · no order submission
--           · no decision_gate · no execution_planner · no executor
-- Purpose:  Four tables for ladder profile configuration.
--           Seeded with execution_sizing_variable_ref vocabulary (six v1 variables).
--           Per-account profiles and legs are seeded by the separate seed runner.
-- Non-goals: no manual_execution_request table · no plan snapshot · no UI tray
--            · no gate changes · no planner changes · no live execution

-- ---------------------------------------------------------------------------
-- 1. execution_sizing_variable_ref
-- Reference vocabulary for permitted sizing variables.
-- Defines allowed variable_key values only. No live balances, no calculation logic.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_sizing_variable_ref (
    variable_key    VARCHAR(64)  NOT NULL,
    display_label   VARCHAR(128) NOT NULL,
    description     TEXT         NOT NULL,
    value_unit      VARCHAR(32)  NOT NULL    COMMENT 'QUOTE_AMOUNT | BASE_QUANTITY | PERCENT',
    allowed_side    VARCHAR(8)   NOT NULL    COMMENT 'BUY | SELL | BOTH',
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    display_order   INT          NOT NULL DEFAULT 0,
    created_at      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    retired_at      DATETIME(6)           DEFAULT NULL,

    PRIMARY KEY (variable_key),

    INDEX idx_execution_sizing_variable_ref_active (is_active, display_order)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Reference vocabulary for permitted sizing variable keys. Content defines meaning only; evaluation logic is code-owned.';


-- ---------------------------------------------------------------------------
-- 2. execution_sizing_rule
-- Deterministic default quote-sizing rule, scoped per trading account.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_sizing_rule (
    sizing_rule_id      BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
    trading_account_id  BIGINT UNSIGNED  NOT NULL,
    rule_code           VARCHAR(64)      NOT NULL,
    display_label       VARCHAR(128)     NOT NULL,
    description         TEXT             NOT NULL,
    rule_type           VARCHAR(32)      NOT NULL    COMMENT 'MANUAL_ONLY | FIXED_QUOTE | PCT_OF_VARIABLE',
    source_variable_key VARCHAR(64)               DEFAULT NULL,
    multiplier_bps      INT                       DEFAULT NULL,
    fixed_quote_amount  DECIMAL(28, 10)           DEFAULT NULL,
    floor_quote_amount  DECIMAL(28, 10)           DEFAULT NULL,
    cap_quote_amount    DECIMAL(28, 10)           DEFAULT NULL,
    is_enabled          TINYINT(1)       NOT NULL DEFAULT 1,
    version             INT              NOT NULL DEFAULT 1,
    created_at          DATETIME(6)      NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    retired_at          DATETIME(6)               DEFAULT NULL,

    PRIMARY KEY (sizing_rule_id),

    UNIQUE KEY uq_execution_sizing_rule_account_code (trading_account_id, rule_code),

    INDEX idx_execution_sizing_rule_account (trading_account_id, is_enabled),

    CONSTRAINT fk_execution_sizing_rule_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_execution_sizing_rule_variable
        FOREIGN KEY (source_variable_key) REFERENCES execution_sizing_variable_ref (variable_key)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-account deterministic quote sizing rules. rule_type drives resolution; no free-text formulas.';


-- ---------------------------------------------------------------------------
-- 3. execution_ladder_profile
-- Versioned account-selectable profile identity.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_ladder_profile (
    ladder_profile_id       BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
    trading_account_id      BIGINT UNSIGNED  NOT NULL,
    profile_code            VARCHAR(64)      NOT NULL,
    display_label           VARCHAR(128)     NOT NULL,
    description             TEXT             NOT NULL,
    side                    VARCHAR(8)       NOT NULL    COMMENT 'BUY | SELL',
    anchor_type             VARCHAR(64)      NOT NULL    COMMENT 'NATIVE_SHORT_ANCHOR_HIGH (v1 only)',
    default_sizing_rule_id  BIGINT UNSIGNED           DEFAULT NULL,
    is_enabled              TINYINT(1)       NOT NULL DEFAULT 1,
    current_version         INT              NOT NULL DEFAULT 1,
    created_at              DATETIME(6)      NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    retired_at              DATETIME(6)               DEFAULT NULL,

    PRIMARY KEY (ladder_profile_id),

    UNIQUE KEY uq_execution_ladder_profile_account_code (trading_account_id, profile_code),

    INDEX idx_execution_ladder_profile_account (trading_account_id, side, is_enabled),

    CONSTRAINT fk_execution_ladder_profile_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_execution_ladder_profile_sizing_rule
        FOREIGN KEY (default_sizing_rule_id) REFERENCES execution_sizing_rule (sizing_rule_id)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Versioned ladder profile identity per account. anchor_type is code-validated; only NATIVE_SHORT_ANCHOR_HIGH is permitted in v1.';


-- ---------------------------------------------------------------------------
-- 4. execution_ladder_leg
-- Versioned ladder legs. Active leg count defines order count.
-- allocation_bps cross-row sum (must equal 10000) is enforced by the resolver,
-- not a DB constraint. Single-row invariants are checked here.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_ladder_leg (
    ladder_leg_id       BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
    ladder_profile_id   BIGINT UNSIGNED  NOT NULL,
    profile_version     INT              NOT NULL,
    leg_number          INT              NOT NULL,
    price_offset_bps    INT              NOT NULL    COMMENT 'Signed offset from anchor in basis points',
    allocation_bps      INT              NOT NULL    COMMENT 'Quote-notional share of final trade amount; active legs must sum to 10000',
    order_type          VARCHAR(16)      NOT NULL DEFAULT 'LIMIT'   COMMENT 'LIMIT only in v1',
    time_in_force       VARCHAR(16)      NOT NULL DEFAULT 'GTC',
    is_enabled          TINYINT(1)       NOT NULL DEFAULT 1,
    created_at          DATETIME(6)      NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (ladder_leg_id),

    UNIQUE KEY uq_execution_ladder_leg_version_number (ladder_profile_id, profile_version, leg_number),

    INDEX idx_execution_ladder_leg_profile_version (ladder_profile_id, profile_version, is_enabled),

    CONSTRAINT fk_execution_ladder_leg_profile
        FOREIGN KEY (ladder_profile_id) REFERENCES execution_ladder_profile (ladder_profile_id),

    CONSTRAINT chk_execution_ladder_leg_number_positive
        CHECK (leg_number > 0),

    CONSTRAINT chk_execution_ladder_leg_allocation_positive
        CHECK (allocation_bps > 0),

    CONSTRAINT chk_execution_ladder_leg_order_type_limit
        CHECK (order_type = 'LIMIT')

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Versioned ladder legs. Active leg count defines the order count; derive it from active leg rows, do not store it. Cross-row allocation_bps sum is enforced by the resolver.';


-- ---------------------------------------------------------------------------
-- Seeds: execution_sizing_variable_ref (six v1 variables)
-- Idempotent: ON DUPLICATE KEY UPDATE touches only display fields, not variable_key.
-- ---------------------------------------------------------------------------

INSERT INTO execution_sizing_variable_ref (
    variable_key,
    display_label,
    description,
    value_unit,
    allowed_side,
    is_active,
    display_order
) VALUES
    (
        'MANUAL_QUOTE_AMOUNT',
        'Manual trade amount',
        'Quote amount explicitly entered or confirmed by the user for this request. It is the final requested trade amount unless a hard safety gate blocks or rejects it.',
        'QUOTE_AMOUNT',
        'BOTH',
        1,
        10
    ),
    (
        'FIXED_QUOTE_AMOUNT',
        'Fixed trade amount',
        'Fixed configured quote amount supplied by a sizing rule as a suggested default. The user may override it before processing.',
        'QUOTE_AMOUNT',
        'BOTH',
        1,
        20
    ),
    (
        'FREE_QUOTE_BALANCE',
        'Free quote balance',
        'Quote-currency balance available for new buy orders after open-order reservations and exchange-available-balance rules.',
        'QUOTE_AMOUNT',
        'BUY',
        1,
        30
    ),
    (
        'TOTAL_WALLET_QUOTE_VALUE',
        'Total wallet value',
        'Total account wallet value resolved in the account quote currency using the defined valuation source and timestamp. This is a suggestion input, not a spendable-balance guarantee.',
        'QUOTE_AMOUNT',
        'BOTH',
        1,
        40
    ),
    (
        'COIN_POSITION_QUOTE_VALUE',
        'Coin position value',
        'Current quote-currency value of the selected asset position, using free plus reserved base quantity where defined by the valuation policy. This is a sell-sizing suggestion input, not a free-quantity guarantee.',
        'QUOTE_AMOUNT',
        'SELL',
        1,
        50
    ),
    (
        'FREE_BASE_QUANTITY',
        'Free asset quantity',
        'Base-asset quantity available for new sell orders after active sell reservations and exchange-available-balance rules. This is a hard sell-cap constraint, not a quote sizing amount.',
        'BASE_QUANTITY',
        'SELL',
        1,
        60
    )
ON DUPLICATE KEY UPDATE
    display_label = VALUES(display_label),
    description   = VALUES(description),
    value_unit    = VALUES(value_unit),
    allowed_side  = VALUES(allowed_side),
    display_order = VALUES(display_order);
