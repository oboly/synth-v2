-- PR24: include XPL and XLM as market-watch rotation assets in the Profit Plan.
--
-- is_core_sensor=1 gates inclusion via _fetch_selected_asset_market_rows
-- (is_portfolio=1 OR is_core_sensor=1). is_portfolio stays 0.
--
-- For new rows: is_enabled=1, is_tradeable=1 are required by the universe query
-- (WHERE a.is_enabled=1 AND COALESCE(a.is_tradeable,0)=1).
-- For existing rows: only is_core_sensor is updated; is_enabled and is_tradeable
-- are deliberately left untouched to preserve existing operational policy.
-- A pre-existing disabled or untradeable asset remains excluded by the universe
-- query. Any activation must be a separate explicit operational migration or
-- admin action.
--
-- Boundary:
-- - Metadata only. No selection score, decision_gate, execution_planner, or
--   executor changes. No broker writes or order submission.
-- - Follow-up only: the legacy global asset.is_portfolio model remains unchanged
--   in this PR and is not repurposed here.
--
-- Acceptance: XPL and XLM appear in the Profit Plan as WATCH_ONLY_ROTATION cards
-- with market zones visible and no account-order overlay.

INSERT INTO asset (symbol, name, sector, is_enabled, is_tradeable, is_portfolio, is_core_sensor)
VALUES
    ('XPL', 'Explosive',  'Other', 1, 1, 0, 1),
    ('XLM', 'Stellar',    'L1',    1, 1, 0, 1)
ON DUPLICATE KEY UPDATE
    is_core_sensor = 1;
