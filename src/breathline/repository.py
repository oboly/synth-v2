from __future__ import annotations

from datetime import datetime

from src.breathline.models import BreathlineConsistencyRow, BreathlineRunCreate, BreathlineTokenSnapshotCreate


class BreathlineRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def insert_aplus_run(self, run: BreathlineRunCreate) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO aplus_run (
                created_ts,
                source_name,
                source_session_ref,
                model_variant,
                prompt_label,
                notes
            ) VALUES (%s, %s, NULL, %s, %s, NULL)
            """,
            (
                run.prediction_ts_utc.replace(tzinfo=None),
                run.source_name,
                "breathline_consistency_table",
                f"prompt_version={run.prompt_version};run_label={run.run_label}",
            ),
        )
        return int(cursor.lastrowid)

    def insert_aplus_raw_text(self, *, aplus_run_id: int, raw_text: str) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO aplus_raw_text (
                aplus_run_id,
                body_text,
                body_hash_sha256
            ) VALUES (
                %s,
                %s,
                SHA2(%s, 256)
            )
            """,
            (
                aplus_run_id,
                raw_text,
                raw_text,
            ),
        )

    def insert_token_snapshot_rows(self, rows: list[BreathlineTokenSnapshotCreate]) -> None:
        if not rows:
            return

        payload = [
            (
                row.aplus_run_id,
                row.asset_id,
                row.prediction_ts_utc.replace(tzinfo=None),
                row.momentum,
                row.stability,
                row.alignment,
                row.volatility,
                row.pressure,
                row.shift,
                row.aplus_initial_class,
                row.aplus_final_class,
                row.aplus_correction_flag,
                row.aplus_correction_reason,
                row.source_name,
                row.prompt_version,
                row.run_label,
            )
            for row in rows
        ]

        cursor = self._conn.cursor()
        cursor.executemany(
            """
            INSERT INTO breathline_token_snapshot (
                aplus_run_id,
                asset_id,
                prediction_ts_utc,
                momentum,
                stability,
                alignment,
                volatility,
                pressure,
                shift,
                aplus_initial_class,
                aplus_final_class,
                aplus_correction_flag,
                aplus_correction_reason,
                source_name,
                prompt_version,
                run_label
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            payload,
        )

    def replace_token_consistency_rows(
        self,
        *,
        prediction_ts_utc: datetime,
        rows: list[BreathlineConsistencyRow],
    ) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "DELETE FROM breathline_token_consistency WHERE prediction_ts_utc = %s",
            (prediction_ts_utc.replace(tzinfo=None),),
        )

        if not rows:
            return

        payload = [
            (
                row.prediction_ts_utc.replace(tzinfo=None),
                row.asset_id,
                row.run_count,
                row.momentum_consistency,
                row.stability_consistency,
                row.alignment_consistency,
                row.volatility_consistency,
                row.pressure_consistency,
                row.shift_consistency,
                row.token_consistency_score,
                row.aplus_initial_class,
                row.aplus_final_class,
                row.aplus_correction_flag,
                row.aplus_correction_reason,
            )
            for row in rows
        ]

        cursor.executemany(
            """
            INSERT INTO breathline_token_consistency (
                prediction_ts_utc,
                asset_id,
                run_count,
                momentum_consistency,
                stability_consistency,
                alignment_consistency,
                volatility_consistency,
                pressure_consistency,
                shift_consistency,
                token_consistency_score,
                aplus_initial_class,
                aplus_final_class,
                aplus_correction_flag,
                aplus_correction_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            payload,
        )

    def load_asset_map(self) -> dict[str, int]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT asset_id, symbol FROM asset WHERE is_enabled = 1")
        rows = cursor.fetchall()

        asset_map: dict[str, int] = {}
        for row in rows:
            if isinstance(row, dict):
                asset_map[str(row["symbol"]).upper()] = int(row["asset_id"])
            else:
                asset_id, symbol = row
                asset_map[str(symbol).upper()] = int(asset_id)
        return asset_map

    def commit(self) -> None:
        self._conn.commit()
