-- Migration: manual_execution_ladder_p0_safety_v1
-- Boundary: schema only · additive only · no broker writes · no order submission
--           · no mutation of existing tables · no decision_gate/execution_planner
--           runtime change · no executor · no live execution enablement
-- Purpose:  P0 safety remediation from
--           docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
--           and docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md
--           (P0 items 3-5). Three additive tables:
--             venue_execution_constraint    (F4 / F5)
--             execution_sell_reservation    (F9)
--             execution_research_provenance (F7 / F17)
-- Non-goals: no manual_execution_request table (P1 backlog item 7, not P0) ·
--            no portfolio_sleeve change — the sleeve-dependency question is
--            resolved by non-dependency: neither new table below references
--            account_id, sleeve_code, or portfolio_sleeve at all; both key
--            exclusively on trading_account_id. See the audit doc's "Sleeve
--            dependency" resolution section for the reasoning. ·
--            no live execution enablement

-- ---------------------------------------------------------------------------
-- 1. venue_execution_constraint
-- Canonical venue/market execution metadata contract. DB-first with no
-- per-asset hardcoding in decision_gate or execution_planner; missing or
-- stale rows fail closed (see src/market_rules/venue_execution_constraints_v1.py).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS venue_execution_constraint (
    venue_execution_constraint_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    venue                     VARCHAR(32)    NOT NULL,
    market                    VARCHAR(32)    NOT NULL,

    tick_size                 DECIMAL(30,12) NOT NULL,
    qty_step_size             DECIMAL(30,12) NOT NULL,
    min_base_quantity         DECIMAL(30,12) NOT NULL,
    min_quote_notional        DECIMAL(20,10) NOT NULL,
    supported_order_types     VARCHAR(256)   NOT NULL COMMENT 'comma-separated, e.g. market,limit',
    supported_time_in_force   VARCHAR(64)    NOT NULL COMMENT 'comma-separated, e.g. GTC,IOC,FOK',

    source_provenance         VARCHAR(64)    NOT NULL,
    metadata_synced_ts_utc    DATETIME(6)    NOT NULL,

    created_ts_utc            DATETIME(6)    NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc            DATETIME(6)    NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (venue_execution_constraint_id),
    UNIQUE KEY uq_venue_execution_constraint_market (venue, market)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Canonical venue/market execution metadata contract: tick size, qty step, min qty/notional, supported order types/TIF, freshness, provenance. Missing/stale rows fail closed at the resolver, not here.';


-- ---------------------------------------------------------------------------
-- 2. execution_sell_reservation
-- Single canonical SELL-side base-quantity reservation truth (F9). Each
-- quantity reserved once and only once; idempotency_key prevents duplicate
-- reservation on retry. reservation_state transitions are owned exclusively
-- by reconciliation (src/decision_gate/sell_reservation_v1.py
-- reconcile_reservation_state) — no other module writes this column.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_sell_reservation (
    reservation_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    trading_account_id   BIGINT UNSIGNED NOT NULL,
    venue                VARCHAR(32)     NOT NULL,
    asset_id             INT(11)         NOT NULL,
    symbol               VARCHAR(32)     NOT NULL,

    idempotency_key       VARCHAR(128)   NOT NULL,
    quantity_base         DECIMAL(30,12) NOT NULL,
    reservation_state     VARCHAR(40)    NOT NULL DEFAULT 'APPROVED_NOT_SUBMITTED',

    manual_execution_request_id BIGINT UNSIGNED DEFAULT NULL
        COMMENT 'forward-compatible reference; manual_execution_request table not yet implemented (P1 backlog item 7) — intentionally no FK constraint yet',
    execution_plan_id     BIGINT UNSIGNED DEFAULT NULL,
    leg_number            INT             DEFAULT NULL,
    broker_order_id       VARCHAR(64)     DEFAULT NULL,

    notes                 TEXT,

    created_ts_utc        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    terminal_ts_utc        DATETIME(6) DEFAULT NULL,

    PRIMARY KEY (reservation_id),
    UNIQUE KEY uq_execution_sell_reservation_idempotency (idempotency_key),
    KEY idx_execution_sell_reservation_account_asset_state (trading_account_id, venue, asset_id, reservation_state),

    CONSTRAINT fk_execution_sell_reservation_account
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),

    CONSTRAINT fk_execution_sell_reservation_asset
        FOREIGN KEY (asset_id) REFERENCES asset (asset_id),

    CONSTRAINT chk_execution_sell_reservation_quantity_positive
        CHECK (quantity_base > 0),

    CONSTRAINT chk_execution_sell_reservation_state
        CHECK (reservation_state IN (
            'APPROVED_NOT_SUBMITTED', 'SUBMITTED_AWAITING_RECONCILIATION',
            'OPEN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED'
        ))

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Single canonical SELL-side base-quantity reservation truth. Do not create a parallel reservation path.';


-- ---------------------------------------------------------------------------
-- 3. execution_research_provenance
-- Canonical provenance/override child record for research-derived execution
-- inputs (F7 / F17). selection_weight, decision_weight, and live_permission
-- are DB-enforced (CHECK constraints), not just Python-enforced, so this is
-- a research-override record only — never a promotion path into
-- selection_engine or decision_gate scoring.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_research_provenance (
    provenance_id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    source_classification     VARCHAR(64)   NOT NULL,
    source_path_or_identifier VARCHAR(512)  NOT NULL,
    source_sha256             CHAR(64)      NOT NULL,
    source_ts_utc             DATETIME(6)   NOT NULL,
    ingestion_status          VARCHAR(32)   NOT NULL,

    selection_weight          DECIMAL(10,6) NOT NULL DEFAULT 0,
    decision_weight           DECIMAL(10,6) NOT NULL DEFAULT 0,

    override_scope            VARCHAR(64)   NOT NULL,
    approving_user            VARCHAR(128)  NOT NULL,
    approval_ts_utc           DATETIME(6)   NOT NULL,

    allowed_assets_json       TEXT          NOT NULL,
    allowed_side              VARCHAR(8)    NOT NULL,
    preview_permission         TINYINT(1)   NOT NULL DEFAULT 1,
    live_permission            TINYINT(1)   NOT NULL DEFAULT 0,

    expires_ts_utc            DATETIME(6)   DEFAULT NULL,
    single_use                 TINYINT(1)   NOT NULL DEFAULT 1,
    consumed_ts_utc           DATETIME(6)   DEFAULT NULL,

    created_ts_utc            DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (provenance_id),
    KEY idx_execution_research_provenance_source (source_sha256),

    CONSTRAINT chk_execution_research_provenance_weights_zero
        CHECK (selection_weight = 0 AND decision_weight = 0),

    CONSTRAINT chk_execution_research_provenance_live_permission_off
        CHECK (live_permission = 0),

    CONSTRAINT chk_execution_research_provenance_side
        CHECK (allowed_side IN ('BUY', 'SELL', 'BOTH'))

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Canonical provenance/override child record for research-derived execution inputs. selection_weight=0, decision_weight=0, and live_permission=0 are DB-enforced. Research-override record only, not a promotion path.';


-- ---------------------------------------------------------------------------
-- Seed: venue_execution_constraint for the 8 A+ Week-1 assets.
--
-- Source: Bitvavo public /v2/markets endpoint (no credentials required),
-- fetched live during this implementation session at 2026-07-25T19:43:17Z.
-- All 8 markets returned status=trading.
--
-- Important discovered discrepancy: Bitvavo's `pricePrecision` field is
-- deprecated and returns null as of this fetch. The previously used static
-- fallback table (src/market_rules/price_tick_normalization_v1.py,
-- _BITVAVO_EUR_STATIC_PRECISION) was built from that now-deprecated field
-- and is confirmed stale for at least BTC-EUR: it implies a 0.1 EUR tick
-- (pricePrecision=1) but the exchange's current explicit `tickSize` field is
-- "1.00" (a 1 EUR tick) — an order of magnitude difference. This seed uses
-- the current explicit fields (tickSize, quantityDecimals,
-- minOrderInBaseAsset, minOrderInQuoteAsset) instead, and is not a
-- hardcoded guess — it reflects values this session observed live via the
-- public endpoint. See the audit doc update for the full discrepancy note.
-- ---------------------------------------------------------------------------

INSERT INTO venue_execution_constraint (
    venue, market, tick_size, qty_step_size, min_base_quantity, min_quote_notional,
    supported_order_types, supported_time_in_force, source_provenance, metadata_synced_ts_utc
) VALUES
    ('bitvavo', 'DEEP-EUR', 0.00000100,  0.00000001, 328.18903132, 5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'RED-EUR',  0.0000100,   0.00000001, 58.33696571,  5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'NEAR-EUR', 0.000100,    0.00000001, 3.07148361,   5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'NOT-EUR',  0.000000010, 0.001,      15841.648,    5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'TAO-EUR',  0.0100,      0.00000001, 0.02889021,   5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'POL-EUR',  0.0000010,   0.00000001, 75.27700538,  5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'LDO-EUR',  0.0000100,   0.00000001, 15.00183796,  5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000'),
    ('bitvavo', 'BTC-EUR',  1.00,        0.00000001, 0.00008817,   5.00, 'market,limit,stopLoss,stopLossLimit,takeProfit,takeProfitLimit', 'GTC,IOC,FOK', 'BITVAVO_PUBLIC_MARKETS_API_V2', '2026-07-25 19:43:17.000000')
ON DUPLICATE KEY UPDATE
    tick_size = VALUES(tick_size),
    qty_step_size = VALUES(qty_step_size),
    min_base_quantity = VALUES(min_base_quantity),
    min_quote_notional = VALUES(min_quote_notional),
    supported_order_types = VALUES(supported_order_types),
    supported_time_in_force = VALUES(supported_time_in_force),
    source_provenance = VALUES(source_provenance),
    metadata_synced_ts_utc = VALUES(metadata_synced_ts_utc);
