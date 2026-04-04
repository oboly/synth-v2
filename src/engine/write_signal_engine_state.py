from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from decimal import Decimal


@dataclass(frozen=True)
class SignalEngineStateRow:
    asset_id: int
    venue: str
    interval_code: str
    signal_ts_utc: datetime

    trend_signal: Optional[str] = None
    volume_signal: Optional[str] = None
    phase_signal: Optional[str] = None
    compass_signal: Optional[str] = None
    rotation_signal: Optional[str] = None
    relative_signal: Optional[str] = None
    setup_signal: Optional[str] = None
    risk_signal: Optional[str] = None

    expansion_delay_state: int = 0
    expansion_delay_score: Optional[Decimal] = None
    rotation_trigger_state: int = 0
    rotation_trigger_score: Optional[Decimal] = None

    trend_score: Optional[Decimal] = None
    volume_score: Optional[Decimal] = None
    phase_score: Optional[Decimal] = None
    compass_score: Optional[Decimal] = None
    rotation_score: Optional[Decimal] = None
    relative_score: Optional[Decimal] = None
    setup_score: Optional[Decimal] = None
    risk_score: Optional[Decimal] = None

    signal_confidence: Optional[Decimal] = None
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None

    created_ts_utc: Optional[datetime] = None


def upsert_signal_engine_state(conn, rows: List[SignalEngineStateRow]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO signal_engine_state (
        asset_id,
        venue,
        interval_code,
        signal_ts_utc,

        trend_signal,
        volume_signal,
        phase_signal,
        compass_signal,
        rotation_signal,
        relative_signal,
        setup_signal,
        risk_signal,

        expansion_delay_state,
        expansion_delay_score,
        rotation_trigger_state,
        rotation_trigger_score,

        trend_score,
        volume_score,
        phase_score,
        compass_score,
        rotation_score,
        relative_score,
        setup_score,
        risk_score,

        signal_confidence,
        reason_code,
        reason_text,
        created_ts_utc
    ) VALUES (
        %s,%s,%s,%s,
        %s,%s,%s,%s,%s,%s,%s,%s,
        %s,%s,%s,%s,
        %s,%s,%s,%s,%s,%s,%s,%s,
        %s,%s,%s,%s
    )
    ON DUPLICATE KEY UPDATE

        trend_signal = VALUES(trend_signal),
        volume_signal = VALUES(volume_signal),
        phase_signal = VALUES(phase_signal),
        compass_signal = VALUES(compass_signal),
        rotation_signal = VALUES(rotation_signal),
        relative_signal = VALUES(relative_signal),
        setup_signal = VALUES(setup_signal),
        risk_signal = VALUES(risk_signal),

        expansion_delay_state = VALUES(expansion_delay_state),
        expansion_delay_score = VALUES(expansion_delay_score),
        rotation_trigger_state = VALUES(rotation_trigger_state),
        rotation_trigger_score = VALUES(rotation_trigger_score),

        trend_score = VALUES(trend_score),
        volume_score = VALUES(volume_score),
        phase_score = VALUES(phase_score),
        compass_score = VALUES(compass_score),
        rotation_score = VALUES(rotation_score),
        relative_score = VALUES(relative_score),
        setup_score = VALUES(setup_score),
        risk_score = VALUES(risk_score),

        signal_confidence = VALUES(signal_confidence),
        reason_code = VALUES(reason_code),
        reason_text = VALUES(reason_text),
        created_ts_utc = VALUES(created_ts_utc)
    """

    data = [
        (
            row.asset_id,
            row.venue,
            row.interval_code,
            row.signal_ts_utc.replace(tzinfo=None),

            row.trend_signal,
            row.volume_signal,
            row.phase_signal,
            row.compass_signal,
            row.rotation_signal,
            row.relative_signal,
            row.setup_signal,
            row.risk_signal,

            row.expansion_delay_state,
            None if row.expansion_delay_score is None else str(row.expansion_delay_score),
            row.rotation_trigger_state,
            None if row.rotation_trigger_score is None else str(row.rotation_trigger_score),

            None if row.trend_score is None else str(row.trend_score),
            None if row.volume_score is None else str(row.volume_score),
            None if row.phase_score is None else str(row.phase_score),
            None if row.compass_score is None else str(row.compass_score),
            None if row.rotation_score is None else str(row.rotation_score),
            None if row.relative_score is None else str(row.relative_score),
            None if row.setup_score is None else str(row.setup_score),
            None if row.risk_score is None else str(row.risk_score),

            None if row.signal_confidence is None else str(row.signal_confidence),
            row.reason_code,
            row.reason_text,
            (row.created_ts_utc or datetime.utcnow())
        )
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, data)

    conn.commit()
    return len(rows)
