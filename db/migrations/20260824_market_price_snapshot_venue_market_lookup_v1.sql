-- Exact lookup path used by automatic-BUY canonical source resolution:
-- newest price for one venue/market, with deterministic row-id tie-break.
ALTER TABLE market_price_snapshot
    ADD INDEX IF NOT EXISTS ix_market_price_snapshot_venue_market_observed (
        venue,
        market,
        observed_ts_utc,
        market_price_snapshot_id
    );
