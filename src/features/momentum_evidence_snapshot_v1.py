"""
SYNTH v2
Module: features.momentum_evidence_snapshot_v1
Purpose (#741, resolving #729's BUILD_MINIMAL_CANONICAL_OWNER decision):
    Minimal, deterministic, replay-safe canonical market-only MOMENTUM
    evidence producer. Computes raw MACD/signal/histogram primitives from
    canonical persisted candles and exposes them as versioned, point-in-time
    evidence -- no categorical states, no account/decision/execution
    coupling.

Canonical producer identity:
    MODEL_ID = "momentum_evidence_snapshot", MODEL_VERSION = "1.0".

Math (fixed per #729/#741 review; do not silently change periods):
    fast EMA period   = 12
    slow EMA period   = 26
    signal EMA period = 9
    MACD             = EMA12(close) - EMA26(close)
    signal           = EMA9(MACD)
    histogram        = MACD - signal
    histogram_delta  = histogram[t] - histogram[t-1]

Interval scope (v1):
    INPUT_INTERVAL = "4h" only. This is the interval already used by the
    other reviewed canonical snapshot producers on `obs_market_candle`
    (`ma_breadth_snapshot_v1`, native SHORT scope), so its ETL lookback and
    replay-boundary support is already exercised in production. 4h/1d/1w/2w
    are explicitly out of scope for v1 (see docs/architecture/
    momentum_evidence_producer_v1.md "Interval extensibility").

#243 horizon discipline:
    `input_interval` ("4h") != `lookback_horizon` (bar count description) !=
    `effective_horizon` != `observed_lifecycle`. No reviewed
    effective-horizon mapping exists for this producer, so
    `effective_horizon` is always `EffectiveHorizon.UNKNOWN` (never inferred
    from `input_interval`, per #243 12.3) and `observed_lifecycle` is always
    `UNMEASURED_LIFECYCLE` -- both reused unmodified from
    `features.evidence_contract_v1`. `freshness` is likewise reused
    unmodified from that module's `compute_freshness` (asof vs evaluated_at
    only); this producer does not invent a second #243 evidence-freshness
    rule. Because `compute_freshness` never returns FRESH, `status` is
    always `INSUFFICIENT_DATA` by design until an owner explicitly reviews
    and declares a #243 freshness rule for this producer -- this mirrors the
    existing precedent in `structure_evidence_contract_v1` and
    `relative_strength_evidence_contract_v1`. It does not gate whether the
    raw MACD/signal/histogram numbers themselves are computed; that is
    governed by the separate `data_quality` field below.

Source candle freshness (separate from #243 `status`/`freshness` above):
    This producer reuses the canonical persisted-candle boundary classifier
    `operations.persisted_market_candle_freshness_v1.classify_persisted_candle_boundary`
    against a point-in-time-bounded fetch (every row has `close_ts_utc <=
    asof_ts_utc`, so "latest" can never be a real wall-clock/live fallback)
    to decide whether the exact `asof_ts_utc` candle is actually persisted,
    or whether the source is gapped/missing at that boundary. This is the
    one existing canonical candle-freshness authority in the repository;
    this module does not invent a second one.

Warmup (explicit MINIMUM-history requirements; insufficient warmup must
never be treated as valid production evidence):
    EMA12                minimum 12 bars
    EMA26                minimum 26 bars
    MACD                 minimum 26 bars (bounded by EMA26)
    signal EMA9(MACD)    minimum 34 bars (26 + 9 - 1; pandas `ewm` with
                          `min_periods=9` only starts counting once MACD
                          itself becomes non-null at bar 26)
    histogram            minimum 34 bars (bounded by signal)
    histogram_delta      minimum 35 bars (needs two consecutive valid
                          histogram values: bars 34 and 35)
    `WARMUP_BARS = 35` below is a FLOOR (fewer bars than this ->
    `INSUFFICIENT_WARMUP`, all four raw fields `None`), not the computation
    window. See "Computation window" immediately below.

Computation window (canonical recursive EMA, not a rolling reset):
    `fetch_candles_for_asof` applies no lower time bound and no row LIMIT --
    it returns the complete persisted `obs_market_candle` history for the
    (venue, asset_id, interval) identity with `close_ts_utc <= asof_ts_utc`.
    `build_momentum_evidence` computes EMA12/EMA26/MACD/signal-EMA9 by
    recursion over that *entire* fetched series, not a fixed trailing slice
    of the most recent `WARMUP_BARS` rows. A fixed-N-bar trailing window
    would silently reseed the `adjust=False` recursion at the window's first
    row, so the result for the same `asof_ts_utc` would change depending on
    how far back the caller's window happened to start -- that is not a
    canonical (source-of-truth-independent) recursive EMA, only an
    approximation of one. "Complete contiguous pre-asof history" here means
    exactly: every row of the caller-provided/fetched series (there is no
    narrower window). `build_momentum_evidence` requires the WHOLE fetched
    series to be gap-free at the fixed `4h` cadence; a single gap anywhere
    in it -- even far in the past -- fails the entire evaluation closed
    (`data_quality = MALFORMED_SOURCE_CANDLE`,
    `NON_CONTIGUOUS_SOURCE_WINDOW`) rather than silently narrowing to the
    contiguous suffix after the gap ("do not stitch across missing
    candles"). `provenance["bar_count"]`/`window_start_ts_utc`/
    `window_end_ts_utc` always reflect the true number of rows actually
    used, never a hardcoded `WARMUP_BARS`.

Boundary:
    - market-only, account-agnostic; no balances/positions/orders/broker
      state; no selection/decision/execution coupling.
    - no categorical momentum states (no EARLY_UP/BULLISH/etc.); raw numeric
      primitives only.
    - no current/latest fallback: every call requires an explicit
      `asof_ts_utc` and `evaluated_at`; the source fetch is bounded to
      `close_ts_utc <= asof_ts_utc`.
    - future asof, missing/gapped/malformed source candles, non-finite
      computed values, and an unsupported `input_interval` all fail closed
      to `data_quality != OK` with `macd_value`/`signal_value`/
      `histogram_value`/`histogram_delta` left `None` -- never a partial or
      guessed value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

import pandas as pd

from src.features.evidence_contract_v1 import (
    EffectiveHorizon,
    ReasonCode,
    UNMEASURED_LIFECYCLE,
    compute_freshness,
    normalize_to_utc,
    resolve_status,
)
from src.operations.persisted_market_candle_freshness_v1 import (
    FUTURE as SOURCE_FUTURE,
    MALFORMED as SOURCE_MALFORMED,
    MISSING as SOURCE_MISSING,
    STALE as SOURCE_STALE,
    classify_persisted_candle_boundary,
)

MODEL_ID = "momentum_evidence_snapshot"
MODEL_VERSION = "1.0"

INPUT_INTERVAL = "4h"
_INTERVAL_DELTA = timedelta(hours=4)

FAST_EMA_PERIOD = 12
SLOW_EMA_PERIOD = 26
SIGNAL_EMA_PERIOD = 9

# Single required warmup floor covering EMA12/EMA26/signal-EMA9/histogram_delta
# simultaneously; see module docstring "Warmup" for the derivation.
WARMUP_BARS = SLOW_EMA_PERIOD + SIGNAL_EMA_PERIOD  # 35

# Describes a minimum-warmup floor, not a fixed computation window: the
# canonical recursive EMA/MACD/signal always consumes the full contiguous
# pre-asof history fetched by the caller (see "Computation window" below).
LOOKBACK_HORIZON = f"full contiguous pre-asof history (>={WARMUP_BARS} bars @ {INPUT_INTERVAL})"


class DataQuality:
    """Gates whether raw MACD/signal/histogram values are populated.

    Independent of the #243 `status`/`freshness` fields above, which reflect
    the (currently unresolved) evidence-contract freshness review, not
    whether the underlying math succeeded.
    """

    OK = "OK"
    FUTURE_ASOF = "FUTURE_ASOF"
    MISSING_SOURCE_CANDLE = "MISSING_SOURCE_CANDLE"
    STALE_SOURCE_CANDLE = "STALE_SOURCE_CANDLE"
    MALFORMED_SOURCE_CANDLE = "MALFORMED_SOURCE_CANDLE"
    INSUFFICIENT_WARMUP = "INSUFFICIENT_WARMUP"
    NON_FINITE_COMPUTED_VALUE = "NON_FINITE_COMPUTED_VALUE"
    UNSUPPORTED_INTERVAL = "UNSUPPORTED_INTERVAL"


# Momentum-specific reason codes. Shared #243 codes (MISSING_ASOF_TS,
# ASOF_AFTER_EVALUATION_TS, FRESHNESS_NOT_OWNER_DEFINED, UNMAPPED_HORIZON)
# are reused unmodified from `evidence_contract_v1.ReasonCode`.
class MomentumReasonCode:
    MISSING_SOURCE_CANDLE = "MISSING_SOURCE_CANDLE"
    STALE_SOURCE_CANDLE = "STALE_SOURCE_CANDLE"
    MALFORMED_SOURCE_CANDLE = "MALFORMED_SOURCE_CANDLE"
    NON_CONTIGUOUS_SOURCE_WINDOW = "NON_CONTIGUOUS_SOURCE_WINDOW"
    INSUFFICIENT_WARMUP = "INSUFFICIENT_WARMUP"
    NON_FINITE_COMPUTED_VALUE = "NON_FINITE_COMPUTED_VALUE"
    UNSUPPORTED_INTERVAL = "UNSUPPORTED_INTERVAL"


class MomentumEvidenceInputError(ValueError):
    """Raised for a caller-shape defect (missing columns, wrong asset/venue
    mix) that must never be silently coerced."""


@dataclass(frozen=True, slots=True)
class MomentumEvidenceSnapshot:
    venue: str
    market: str
    asset_id: int
    asof_ts: datetime | None
    input_interval: str
    lookback_horizon: str
    effective_horizon: str
    observed_lifecycle_status: str
    fast_ema_period: int
    slow_ema_period: int
    signal_ema_period: int
    macd_value: Decimal | None
    signal_value: Decimal | None
    histogram_value: Decimal | None
    histogram_delta: Decimal | None
    freshness: str
    data_quality: str
    model_id: str
    model_version: str
    status: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    provenance: dict[str, Any] = field(default_factory=dict)


def _to_decimal(value: float, scale: int = 10) -> Decimal:
    return Decimal(str(round(float(value), scale)))


def _is_finite(value: Any) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))  # noqa: PLR0124 (NaN check)


def _boundary_row(candles: pd.DataFrame, *, asof_ts_utc: datetime) -> Mapping[str, Any]:
    if candles.empty:
        return {"latest_close_ts_utc": None, "expected_close_row_count": 0}
    latest = candles["close_ts_utc"].max()
    exact_count = int((candles["close_ts_utc"] == pd.Timestamp(asof_ts_utc)).sum())
    return {
        "latest_close_ts_utc": latest.to_pydatetime() if hasattr(latest, "to_pydatetime") else latest,
        "expected_close_row_count": exact_count,
    }


def _source_data_quality(freshness_classification: str) -> tuple[str, tuple[str, ...]]:
    mapping = {
        SOURCE_MISSING: (
            DataQuality.MISSING_SOURCE_CANDLE,
            (MomentumReasonCode.MISSING_SOURCE_CANDLE,),
        ),
        SOURCE_STALE: (
            DataQuality.STALE_SOURCE_CANDLE,
            (MomentumReasonCode.STALE_SOURCE_CANDLE,),
        ),
        SOURCE_MALFORMED: (
            DataQuality.MALFORMED_SOURCE_CANDLE,
            (MomentumReasonCode.MALFORMED_SOURCE_CANDLE,),
        ),
        # FUTURE cannot occur given the point-in-time-bounded fetch this
        # module always performs (every row has close_ts_utc <= asof), but
        # is mapped defensively rather than left unhandled.
        SOURCE_FUTURE: (
            DataQuality.MALFORMED_SOURCE_CANDLE,
            (MomentumReasonCode.MALFORMED_SOURCE_CANDLE,),
        ),
    }
    return mapping.get(freshness_classification, (DataQuality.OK, ()))


def build_momentum_evidence(
    *,
    candles: pd.DataFrame,
    asof_ts_utc: datetime,
    evaluated_at: datetime,
    venue: str,
    asset_id: int,
    market: str,
    interval_code: str,
) -> MomentumEvidenceSnapshot:
    """Build one point-in-time MOMENTUM evidence row.

    `candles` must already be filtered by the caller to exactly one
    (venue, asset_id, interval_code) series with `close_ts_utc <=
    asof_ts_utc` -- this function performs no lookup of its own, so a
    replay caller can never receive a "latest" fallback for a historical
    asof. Required columns: `candle_id`, `close_ts_utc`, `close_price`.
    """
    asof = normalize_to_utc(asof_ts_utc)
    evaluated = normalize_to_utc(evaluated_at)

    if not candles.empty:
        required = {"candle_id", "close_ts_utc", "close_price"}
        missing_cols = required.difference(candles.columns)
        if missing_cols:
            raise MomentumEvidenceInputError(f"candle input missing columns: {sorted(missing_cols)}")

    normalized_asof_ts, freshness, freshness_reason_codes = compute_freshness(
        asof_ts=asof, evaluated_at=evaluated
    )

    reason_codes: tuple[str, ...] = freshness_reason_codes
    # effective_horizon is never declared by this producer today (#243
    # 12.3): fail closed rather than infer it from input_interval.
    reason_codes += (ReasonCode.UNMAPPED_HORIZON,)

    if ReasonCode.ASOF_AFTER_EVALUATION_TS in freshness_reason_codes:
        # A future-dated asof relative to evaluated_at is a data-integrity
        # contradiction, not a staleness judgement (see
        # evidence_contract_v1.compute_freshness). The snapshot must carry
        # no usable computed momentum evidence at all -- not merely a
        # rejected top-level status -- so this short-circuits before any
        # candle/interval/warmup handling that could otherwise populate a
        # raw value derived from a future-aware evaluation window.
        data_quality = DataQuality.FUTURE_ASOF
        status, reason_codes = resolve_status(freshness=freshness, extra_reason_codes=reason_codes)
        return MomentumEvidenceSnapshot(
            venue=venue,
            market=market,
            asset_id=asset_id,
            asof_ts=normalized_asof_ts,
            input_interval=interval_code,
            lookback_horizon=LOOKBACK_HORIZON,
            effective_horizon=EffectiveHorizon.UNKNOWN,
            observed_lifecycle_status=UNMEASURED_LIFECYCLE.status,
            fast_ema_period=FAST_EMA_PERIOD,
            slow_ema_period=SLOW_EMA_PERIOD,
            signal_ema_period=SIGNAL_EMA_PERIOD,
            macd_value=None,
            signal_value=None,
            histogram_value=None,
            histogram_delta=None,
            freshness=freshness,
            data_quality=data_quality,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            status=status,
            reason_codes=reason_codes,
            provenance={"venue": venue, "asset_id": asset_id, "market": market},
        )

    if interval_code != INPUT_INTERVAL:
        data_quality = DataQuality.UNSUPPORTED_INTERVAL
        reason_codes += (MomentumReasonCode.UNSUPPORTED_INTERVAL,)
        status, reason_codes = resolve_status(freshness=freshness, extra_reason_codes=reason_codes)
        return MomentumEvidenceSnapshot(
            venue=venue,
            market=market,
            asset_id=asset_id,
            asof_ts=normalized_asof_ts,
            input_interval=interval_code,
            lookback_horizon=LOOKBACK_HORIZON,
            effective_horizon=EffectiveHorizon.UNKNOWN,
            observed_lifecycle_status=UNMEASURED_LIFECYCLE.status,
            fast_ema_period=FAST_EMA_PERIOD,
            slow_ema_period=SLOW_EMA_PERIOD,
            signal_ema_period=SIGNAL_EMA_PERIOD,
            macd_value=None,
            signal_value=None,
            histogram_value=None,
            histogram_delta=None,
            freshness=freshness,
            data_quality=data_quality,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            status=status,
            reason_codes=reason_codes,
            provenance={"venue": venue, "asset_id": asset_id, "market": market},
        )

    working = candles.copy()
    if not working.empty:
        working["close_ts_utc"] = pd.to_datetime(working["close_ts_utc"], utc=True, errors="coerce")
        if working["close_ts_utc"].isna().any():
            raise MomentumEvidenceInputError("candle input has an unparseable close_ts_utc")
        if (working["close_ts_utc"] > pd.Timestamp(asof)).any():
            raise MomentumEvidenceInputError(
                "candle input contains rows after asof_ts_utc; caller must pre-filter"
            )
        working = working.sort_values("close_ts_utc").reset_index(drop=True)
        if working["close_ts_utc"].duplicated().any():
            raise MomentumEvidenceInputError("candle input has duplicate close_ts_utc rows")

    boundary = classify_persisted_candle_boundary(
        _boundary_row(working, asof_ts_utc=asof), expected_close_ts_utc=asof
    )
    data_quality, source_reason_codes = _source_data_quality(boundary.freshness_classification)
    reason_codes += source_reason_codes

    macd_value: Decimal | None = None
    signal_value: Decimal | None = None
    histogram_value: Decimal | None = None
    histogram_delta: Decimal | None = None
    provenance: dict[str, Any] = {
        "venue": venue,
        "asset_id": asset_id,
        "market": market,
        "source_table": "obs_market_candle",
        "bar_count": int(len(working)),
    }

    if data_quality == DataQuality.OK:
        # Canonical recursive EMA/MACD/signal consume the FULL contiguous
        # pre-asof history fetched by the caller (see module docstring
        # "Computation window" -- `fetch_candles_for_asof` applies no lower
        # bound and no row LIMIT). WARMUP_BARS is a minimum-history gate
        # only; it is never used to truncate/reset the computation window
        # to a fixed trailing slice. Discarding earlier contiguous history
        # would silently reseed the recursion, changing the result computed
        # for the same asof depending on how far back the caller happened
        # to fetch -- that is not a canonical recursive EMA.
        if len(working) < WARMUP_BARS:
            data_quality = DataQuality.INSUFFICIENT_WARMUP
            reason_codes += (MomentumReasonCode.INSUFFICIENT_WARMUP,)
        else:
            gaps = working["close_ts_utc"].diff().iloc[1:]
            if (gaps != _INTERVAL_DELTA).any():
                data_quality = DataQuality.MALFORMED_SOURCE_CANDLE
                reason_codes += (MomentumReasonCode.NON_CONTIGUOUS_SOURCE_WINDOW,)
            elif not working["close_price"].apply(_is_finite).all():
                data_quality = DataQuality.MALFORMED_SOURCE_CANDLE
                reason_codes += (MomentumReasonCode.MALFORMED_SOURCE_CANDLE,)
            else:
                close = working["close_price"].astype(float)
                ema_fast = close.ewm(span=FAST_EMA_PERIOD, adjust=False, min_periods=FAST_EMA_PERIOD).mean()
                ema_slow = close.ewm(span=SLOW_EMA_PERIOD, adjust=False, min_periods=SLOW_EMA_PERIOD).mean()
                macd = ema_fast - ema_slow
                signal = macd.ewm(span=SIGNAL_EMA_PERIOD, adjust=False, min_periods=SIGNAL_EMA_PERIOD).mean()
                histogram = macd - signal
                histogram_delta_series = histogram.diff()

                candidates = (
                    macd.iloc[-1],
                    signal.iloc[-1],
                    histogram.iloc[-1],
                    histogram_delta_series.iloc[-1],
                )
                if not all(_is_finite(v) for v in candidates):
                    data_quality = DataQuality.NON_FINITE_COMPUTED_VALUE
                    reason_codes += (MomentumReasonCode.NON_FINITE_COMPUTED_VALUE,)
                else:
                    macd_value = _to_decimal(macd.iloc[-1])
                    signal_value = _to_decimal(signal.iloc[-1])
                    histogram_value = _to_decimal(histogram.iloc[-1])
                    histogram_delta = _to_decimal(histogram_delta_series.iloc[-1])
                    asof_row = working.iloc[-1]
                    provenance["candle_id"] = int(asof_row["candle_id"])
                    provenance["window_start_ts_utc"] = working["close_ts_utc"].iloc[0].isoformat()
                    provenance["window_end_ts_utc"] = working["close_ts_utc"].iloc[-1].isoformat()

    status, reason_codes = resolve_status(freshness=freshness, extra_reason_codes=reason_codes)

    return MomentumEvidenceSnapshot(
        venue=venue,
        market=market,
        asset_id=asset_id,
        asof_ts=normalized_asof_ts,
        input_interval=interval_code,
        lookback_horizon=LOOKBACK_HORIZON,
        effective_horizon=EffectiveHorizon.UNKNOWN,
        observed_lifecycle_status=UNMEASURED_LIFECYCLE.status,
        fast_ema_period=FAST_EMA_PERIOD,
        slow_ema_period=SLOW_EMA_PERIOD,
        signal_ema_period=SIGNAL_EMA_PERIOD,
        macd_value=macd_value,
        signal_value=signal_value,
        histogram_value=histogram_value,
        histogram_delta=histogram_delta,
        freshness=freshness,
        data_quality=data_quality,
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        status=status,
        reason_codes=reason_codes,
        provenance=provenance,
    )


def fetch_candles_for_asof(
    conn: Any,
    *,
    asset_id: int,
    venue: str,
    asof_ts_utc: datetime,
) -> pd.DataFrame:
    """Exact point-in-time source window: every row has close_ts_utc <=
    asof_ts_utc. Never falls back to a current/latest row.

    Deliberately unbounded below and unlimited in row count: this fetches
    the complete persisted pre-asof history for this (venue, asset_id,
    interval) identity, not a fixed trailing slice. A canonical recursive
    EMA (`build_momentum_evidence`) requires the full contiguous history it
    was seeded on, not a caller-chosen row count -- truncating here (e.g.
    `ORDER BY close_ts_utc DESC LIMIT N`) would silently reseed the
    recursion and change the result for the same asof depending on the
    truncation point. `build_momentum_evidence`'s own contiguity/warmup
    checks are what decide whether this history is usable, not this fetch.
    """
    asof = normalize_to_utc(asof_ts_utc)
    sql = """
    SELECT candle_id, close_ts_utc, close_price
    FROM obs_market_candle
    WHERE asset_id = %s AND venue = %s AND interval_code = %s
      AND close_ts_utc <= %s
    ORDER BY close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                asset_id,
                venue,
                INPUT_INTERVAL,
                asof.replace(tzinfo=None),
            ),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["candle_id", "close_ts_utc", "close_price"])
    df = pd.DataFrame(rows)
    df["close_ts_utc"] = pd.to_datetime(df["close_ts_utc"], utc=True, errors="raise")
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    return df


def persist_snapshot(conn: Any, snapshot: MomentumEvidenceSnapshot, *, authorization: Any) -> str:
    from src.operations.writer_capability_authorization_v1 import require_writer_mutation_authorization

    require_writer_mutation_authorization(authorization, "momentum_evidence_snapshot")

    import json

    sql = """
    INSERT INTO momentum_evidence_snapshot_v1 (
      asof_ts_utc, venue, asset_id, market, input_interval, lookback_horizon,
      effective_horizon, observed_lifecycle_status, fast_ema_period, slow_ema_period,
      signal_ema_period, macd_value, signal_value, histogram_value, histogram_delta,
      freshness, data_quality, model_id, model_version, status, reason_codes_json,
      provenance_payload
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE created_at = created_at
    """
    values = (
        None if snapshot.asof_ts is None else snapshot.asof_ts.replace(tzinfo=None),
        snapshot.venue,
        snapshot.asset_id,
        snapshot.market,
        snapshot.input_interval,
        snapshot.lookback_horizon,
        snapshot.effective_horizon,
        snapshot.observed_lifecycle_status,
        snapshot.fast_ema_period,
        snapshot.slow_ema_period,
        snapshot.signal_ema_period,
        None if snapshot.macd_value is None else str(snapshot.macd_value),
        None if snapshot.signal_value is None else str(snapshot.signal_value),
        None if snapshot.histogram_value is None else str(snapshot.histogram_value),
        None if snapshot.histogram_delta is None else str(snapshot.histogram_delta),
        snapshot.freshness,
        snapshot.data_quality,
        snapshot.model_id,
        snapshot.model_version,
        snapshot.status,
        json.dumps(list(snapshot.reason_codes), separators=(",", ":")),
        json.dumps(snapshot.provenance, sort_keys=True, separators=(",", ":"), default=str),
    )
    with conn.cursor() as cur:
        created = int(cur.execute(sql, values)) > 0
    conn.commit()
    return "CREATED" if created else "NOOP_ALREADY_EXISTS"
