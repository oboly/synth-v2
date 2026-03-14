from __future__ import annotations

import hashlib
from collections.abc import Sequence

from synth.aplus.models import ParsedAPlusDocument


class APlusRepository:
    """
    Minimal repository skeleton.

    Replace `conn.execute(...)` with your project's DB adapter.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def store_document(self, doc: ParsedAPlusDocument) -> int:
        run_id = self._insert_run(doc)
        self._insert_raw_text(run_id=run_id, raw_text=doc.raw_text)

        for asset in doc.assets:
            signal_id = self._insert_signal(run_id=run_id, asset=asset)
            for factor in asset.factors:
                self._insert_factor(signal_id=signal_id, factor=factor)

        return run_id

    def _insert_run(self, doc: ParsedAPlusDocument) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO aplus_run (
                created_ts, source_name, source_session_ref, model_variant, prompt_label, notes
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                doc.run.created_ts.replace(tzinfo=None),
                doc.run.source_name,
                doc.run.source_session_ref,
                doc.run.model_variant,
                doc.run.prompt_label,
                doc.run.notes,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_raw_text(self, *, run_id: int, raw_text: str) -> None:
        body_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT IGNORE INTO aplus_raw_text (
                aplus_run_id, body_text, body_hash_sha256
            ) VALUES (%s, %s, %s)
            """,
            (run_id, raw_text, body_hash),
        )

    def _insert_signal(self, *, run_id: int, asset) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO aplus_asset_signal (
                aplus_run_id, asset_code, created_ts, horizon_label, horizon_end_ts,
                phase_label, direction_label, magnitude_label,
                confidence_label, confidence_score,
                target_price, target_currency,
                raw_excerpt, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                asset.signal.asset_code,
                asset.signal.created_ts.replace(tzinfo=None),
                asset.signal.horizon_label,
                asset.signal.horizon_end_ts.replace(tzinfo=None) if asset.signal.horizon_end_ts else None,
                asset.signal.phase_label.value if asset.signal.phase_label else None,
                asset.signal.direction_label.value if asset.signal.direction_label else None,
                asset.signal.magnitude_label.value if asset.signal.magnitude_label else None,
                asset.signal.confidence_label.value if asset.signal.confidence_label else None,
                asset.signal.confidence_score,
                asset.signal.target_price,
                asset.signal.target_currency,
                asset.signal.raw_excerpt,
                asset.signal.notes,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_factor(self, *, signal_id: int, factor) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO aplus_factor (
                aplus_signal_id, factor_name, factor_value_text, factor_value_num, factor_unit, notes
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                signal_id,
                factor.factor_name,
                factor.factor_value_text,
                factor.factor_value_num,
                factor.factor_unit,
                factor.notes,
            ),
        )
