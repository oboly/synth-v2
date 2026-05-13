CREATE OR REPLACE VIEW vw_paper_advice_execution_zone_context_v1 AS
SELECT
    asset_id,
    venue,
    interval_code,
    asof_ts_utc,

    CASE
        WHEN notes LIKE 'leg_direction=%'
            THEN SUBSTRING_INDEX(SUBSTRING_INDEX(notes, 'leg_direction=', -1), ';', 1)
        ELSE NULL
    END AS leg_direction,

    expected_entry_zone_low AS entry_zone_low,
    expected_entry_zone_high AS entry_zone_high,
    expected_entry_zone_type AS entry_zone_type,

    expected_take_profit_zone_low AS tp_zone_low,
    expected_take_profit_zone_high AS tp_zone_high,
    expected_take_profit_zone_type AS tp_zone_type,

    invalidation_price,
    zone_confidence_score,
    zone_alignment_score
FROM execution_zone_context;
