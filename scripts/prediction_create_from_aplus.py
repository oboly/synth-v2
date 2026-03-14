from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from synth.aplus.factor_extractor import map_aplus_signal_to_prediction_factors
from synth.db.connection import get_connection
from synth.prediction.models import PredictionDraft, PredictionFactor, PredictionItem, PredictionRun
from synth.prediction.repository import PredictionRepository


def main() -> None:
    created_ts = datetime.now(timezone.utc)
    horizon_days = 30

    run = PredictionRun(
        created_ts=created_ts,
        source="aplus_bridge",
        strategy_name="invest_swing_30d",
        timeframe_code="1d",
        horizon_days=horizon_days,
        notes="Created from A+ signal bridge.",
    )

    item = PredictionItem(
        asset_code="XRP-EUR",
        created_ts=created_ts,
        anchor_tf="1d",
        horizon_end_ts=created_ts + timedelta(days=horizon_days),
        regime_call="expansion",
        direction_call="bullish",
        magnitude_call="strong",
        timing_call="mid_window",
        target_price=None,               # keep NULL until validated in your market model
        invalidation_price=None,
        entry_zone_low=None,
        entry_zone_high=None,
        conviction_total=Decimal("62.00"),
        notes="A+ phase supportive, target intentionally not promoted to hard forecast.",
    )

    factor_seeds = map_aplus_signal_to_prediction_factors(
        phase_label="expansion",
        direction_label="bullish",
        confidence_score=Decimal("62.00"),
        target_price=Decimal("1.80"),
        target_currency="USD",
    )

    factors = [
        PredictionFactor(
            factor_type=seed.factor_type,
            factor_name=seed.factor_name,
            factor_value_text=seed.factor_value_text,
            factor_value_num=seed.factor_value_num,
            factor_score=seed.factor_score,
            factor_weight=seed.factor_weight,
            notes=seed.notes,
        )
        for seed in factor_seeds
    ]

    draft = PredictionDraft(run=run, item=item, factors=factors)

    conn = get_connection()
    try:
        repo = PredictionRepository(conn)
        run_id, pred_id = repo.store_prediction(draft)
        conn.commit()
        print(f"Stored prediction run_id={run_id} pred_id={pred_id}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
