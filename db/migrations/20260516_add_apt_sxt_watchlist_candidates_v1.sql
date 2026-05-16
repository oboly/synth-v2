-- Synth v2 research/watchlist candidates.
--
-- Boundary:
-- - Metadata only.
-- - No selection score changes.
-- - No advice / decision_gate / execution_planner / executor changes.
-- - No broker writes or order submission.
--
-- Venue support:
-- - No local obs_market_candle / obs_venue_ticker_24h evidence was found for
--   APT, SXT, or BILL at migration authoring time.
-- - APT and SXT are therefore inserted as research candidates only:
--   is_enabled=0 prevents ETL/signal runtime participation.
--   is_tradeable=0 prevents trading-decision eligibility.
-- - BILL is intentionally not inserted because the ticker/project/venue market
--   is ambiguous and requires manual disambiguation first.

INSERT INTO asset (
    symbol,
    name,
    sector,
    is_enabled,
    is_portfolio,
    is_tradeable,
    quote_asset,
    asset_class
) VALUES
    ('APT', 'Aptos', 'L1', 0, 0, 0, 'EUR', 'LARGE_ALT'),
    ('SXT', 'Space and Time', 'Other', 0, 0, 0, 'EUR', 'MID_ALT')
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    sector = VALUES(sector),
    quote_asset = VALUES(quote_asset),
    asset_class = VALUES(asset_class),
    updated_ts = CURRENT_TIMESTAMP;
