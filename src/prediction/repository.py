from __future__ import annotations

from synth.prediction.models import PredictionDraft


class PredictionRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def store_prediction(self, draft: PredictionDraft) -> tuple[int, int]:
        run_id = self._insert_run(draft)
        pred_id = self._insert_item(run_id=run_id, draft=draft)

        for factor in draft.factors:
            self._insert_factor(pred_id=pred_id, factor=factor)

        return run_id, pred_id

    def _insert_run(self, draft: PredictionDraft) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO prediction_run (
                created_ts, source, strategy_name, timeframe_code, horizon_days, notes
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                draft.run.created_ts.replace(tzinfo=None),
                draft.run.source,
                draft.run.strategy_name,
                draft.run.timeframe_code,
                draft.run.horizon_days,
                draft.run.notes,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_item(self, *, run_id: int, draft: PredictionDraft) -> int:
        cursor = self._conn.cursor()
        item = draft.item
        cursor.execute(
            """
            INSERT INTO prediction_item (
                run_id, asset_code, created_ts, anchor_tf, horizon_end_ts,
                regime_call, direction_call, magnitude_call, timing_call,
                target_price, target_currency, invalidation_price,
                entry_zone_low, entry_zone_high, conviction_total,
                status, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                item.asset_code,
                item.created_ts.replace(tzinfo=None),
                item.anchor_tf,
                item.horizon_end_ts.replace(tzinfo=None),
                item.regime_call,
                item.direction_call,
                item.magnitude_call,
                item.timing_call,
                item.target_price,
                item.target_currency,
                item.invalidation_price,
                item.entry_zone_low,
                item.entry_zone_high,
                item.conviction_total,
                item.status,
                item.notes,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_factor(self, *, pred_id: int, factor) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO prediction_factor (
                pred_id, factor_type, factor_name,
                factor_value_text, factor_value_num,
                factor_score, factor_weight, evidence_json, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                pred_id,
                factor.factor_type,
                factor.factor_name,
                factor.factor_value_text,
                factor.factor_value_num,
                factor.factor_score,
                factor.factor_weight,
                factor.evidence_json,
                factor.notes,
            ),
        )
