from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import math
import pandas as pd
import pytest

from src.features.momentum_evidence_snapshot_v1 import (
    DataQuality,
    FAST_EMA_PERIOD,
    INPUT_INTERVAL,
    MODEL_ID,
    MODEL_VERSION,
    MomentumEvidenceInputError,
    MomentumReasonCode,
    SIGNAL_EMA_PERIOD,
    SLOW_EMA_PERIOD,
    WARMUP_BARS,
    build_momentum_evidence,
    fetch_candles_for_asof,
)

ASOF = datetime(2026, 9, 1, tzinfo=UTC)
VENUE = "bitvavo"
ASSET_ID = 1
MARKET = "BTC-EUR"


def _closes(n: int, *, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * i for i in range(n)]


def _candles(closes: list[float], *, end_ts: datetime = ASOF, candle_id_start: int = 1) -> pd.DataFrame:
    n = len(closes)
    rows = [
        {
            "candle_id": candle_id_start + i,
            "close_ts_utc": end_ts - timedelta(hours=4 * (n - i - 1)),
            "close_price": closes[i],
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def _reference_ema(values: list[float], period: int) -> list[float | None]:
    """Independent (non-pandas) EMA reference matching pandas' `ewm(...,
    adjust=False, min_periods=period)` semantics exactly: the recursion
    y_0=x_0, y_t=alpha*x_t+(1-alpha)*y_{t-1} runs from the very first
    sample; `min_periods` only masks the first `period-1` outputs to None,
    it does not reseed the recursion with a simple average."""
    if len(values) < period:
        return [None] * len(values)
    alpha = 2.0 / (period + 1)
    out: list[float | None] = [None] * len(values)
    prev = values[0]
    for i in range(1, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        if i >= period - 1:
            out[i] = prev
    return out


def _reference_macd_signal_histogram(closes: list[float]) -> tuple[float, float, float, float]:
    ema_fast = _reference_ema(closes, FAST_EMA_PERIOD)
    ema_slow = _reference_ema(closes, SLOW_EMA_PERIOD)
    macd = [None if (a is None or b is None) else a - b for a, b in zip(ema_fast, ema_slow)]
    macd_values_only = [m for m in macd if m is not None]
    signal_only = _reference_ema(macd_values_only, SIGNAL_EMA_PERIOD)
    # Map signal back onto the full-length series (offset by SLOW_EMA_PERIOD-1 Nones).
    offset = SLOW_EMA_PERIOD - 1
    signal = [None] * len(closes)
    for i, v in enumerate(signal_only):
        signal[offset + i] = v
    histogram = [None if (m is None or s is None) else m - s for m, s in zip(macd, signal)]
    return macd[-1], signal[-1], histogram[-1], histogram[-1] - histogram[-2]


def test_exact_ema12_arithmetic_matches_reference():
    closes = _closes(WARMUP_BARS)
    ema_fast_ref = _reference_ema(closes, FAST_EMA_PERIOD)[-1]
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    # macd_value = ema12 - ema26; recover ema12 to prove the fast leg exactly.
    ema_slow_ref = _reference_ema(closes, SLOW_EMA_PERIOD)[-1]
    assert result.macd_value is not None
    assert float(result.macd_value) == pytest.approx(ema_fast_ref - ema_slow_ref, abs=1e-8)


def test_exact_ema26_and_macd_arithmetic():
    closes = _closes(WARMUP_BARS)
    macd_ref, _, _, _ = _reference_macd_signal_histogram(closes)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert float(result.macd_value) == pytest.approx(macd_ref, abs=1e-8)


def test_exact_signal_ema9_over_macd_arithmetic():
    closes = _closes(WARMUP_BARS)
    _, signal_ref, _, _ = _reference_macd_signal_histogram(closes)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert float(result.signal_value) == pytest.approx(signal_ref, abs=1e-8)


def test_exact_histogram_arithmetic():
    closes = _closes(WARMUP_BARS)
    _, _, histogram_ref, _ = _reference_macd_signal_histogram(closes)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert float(result.histogram_value) == pytest.approx(histogram_ref, abs=1e-8)
    # Each field is independently rounded to 10 decimal places, so this can
    # differ from macd_value - signal_value by at most one rounding ulp.
    assert float(result.histogram_value) == pytest.approx(
        float(result.macd_value) - float(result.signal_value), abs=1e-9
    )


def test_exact_histogram_delta_arithmetic():
    closes = _closes(WARMUP_BARS)
    _, _, _, delta_ref = _reference_macd_signal_histogram(closes)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert float(result.histogram_delta) == pytest.approx(delta_ref, abs=1e-8)


def test_canonical_recursive_ema_reflects_prepended_pre_asof_history():
    """A canonical recursive EMA/MACD must consume the FULL contiguous
    pre-asof history, not a fixed trailing N-bar window that silently
    reseeds the recursion. Build a valid 35-bar suffix (result A), then
    prepend additional valid contiguous history before it and recompute for
    the exact same asof/tail prices (result B); B must differ from A."""
    tail = _closes(WARMUP_BARS)
    prepended = [1.0] * 25 + tail

    result_a = build_momentum_evidence(
        candles=_candles(tail), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    result_b = build_momentum_evidence(
        candles=_candles(prepended), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )

    assert result_a.data_quality == DataQuality.OK
    assert result_b.data_quality == DataQuality.OK
    assert result_b.provenance["bar_count"] == len(prepended)
    assert result_a.provenance["bar_count"] == len(tail)
    # Same trailing close prices, same asof -- only the amount of pre-asof
    # history differs. A fixed-window (bug) implementation would return the
    # same macd_value for both; the canonical recursive implementation must
    # not.
    assert result_a.macd_value != result_b.macd_value
    assert result_a.signal_value != result_b.signal_value
    assert result_a.histogram_value != result_b.histogram_value
    reference_full_macd, reference_full_signal, reference_full_histogram, reference_full_delta = (
        _reference_macd_signal_histogram(prepended)
    )
    assert float(result_b.macd_value) == pytest.approx(reference_full_macd, abs=1e-8)
    assert float(result_b.signal_value) == pytest.approx(reference_full_signal, abs=1e-8)
    assert float(result_b.histogram_value) == pytest.approx(reference_full_histogram, abs=1e-8)
    assert float(result_b.histogram_delta) == pytest.approx(reference_full_delta, abs=1e-8)


def test_gap_far_before_warmup_floor_still_fails_closed():
    """A gap anywhere in the fetched pre-asof series fails the whole
    evaluation closed -- even one well before the 35-bar warmup floor, on a
    longer overall series. The producer must never silently narrow to the
    contiguous suffix after the gap ("no stitching")."""
    closes = _closes(50)
    candles = _candles(closes)
    # Shift a row far back in history (position 5 of 50) off the 4h grid.
    candles.loc[candles.index[5], "close_ts_utc"] = (
        candles.loc[candles.index[5], "close_ts_utc"] - timedelta(hours=1)
    )
    result = build_momentum_evidence(
        candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MALFORMED_SOURCE_CANDLE
    assert MomentumReasonCode.NON_CONTIGUOUS_SOURCE_WINDOW in result.reason_codes
    assert result.macd_value is None
    assert result.signal_value is None
    assert result.histogram_value is None
    assert result.histogram_delta is None


def test_fetch_candles_for_asof_has_no_lower_bound_or_row_limit():
    """The source fetch must not truncate history with a fixed row count or
    a fixed lookback lower bound (e.g. `LIMIT 35` / `close_ts_utc >=
    asof - N*interval`); it must return the complete pre-asof history so
    `build_momentum_evidence` can run a canonical recursive EMA over it."""
    import inspect

    source = inspect.getsource(fetch_candles_for_asof)
    sql_body = source.split('sql = """', 1)[1].split('"""', 1)[0]
    assert "LIMIT" not in sql_body.upper()
    assert "close_ts_utc >=" not in sql_body


def test_deterministic_identical_input_output():
    closes = _closes(WARMUP_BARS)
    a = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    b = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert a == b


def test_insufficient_warmup_fails_closed():
    closes = _closes(WARMUP_BARS - 1)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.INSUFFICIENT_WARMUP
    assert result.macd_value is None and result.histogram_delta is None


def test_missing_candle_at_exact_asof_fails_closed():
    closes = _closes(WARMUP_BARS)
    # Shift the whole series one interval earlier so nothing lands exactly on ASOF.
    result = build_momentum_evidence(
        candles=_candles(closes, end_ts=ASOF - timedelta(hours=4)),
        asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE, asset_id=ASSET_ID,
        market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.STALE_SOURCE_CANDLE
    assert result.macd_value is None


def test_completely_missing_source_fails_closed():
    result = build_momentum_evidence(
        candles=pd.DataFrame(columns=["candle_id", "close_ts_utc", "close_price"]),
        asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE, asset_id=ASSET_ID,
        market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MISSING_SOURCE_CANDLE
    assert result.macd_value is None


def test_stale_candle_source_fails_closed():
    closes = _closes(WARMUP_BARS)
    stale_end = ASOF - timedelta(hours=8)
    result = build_momentum_evidence(
        candles=_candles(closes, end_ts=stale_end), asof_ts_utc=ASOF, evaluated_at=ASOF,
        venue=VENUE, asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.STALE_SOURCE_CANDLE
    assert result.macd_value is None


def test_future_asof_fails_closed():
    closes = _closes(WARMUP_BARS)
    evaluated_at = ASOF - timedelta(hours=4)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=evaluated_at, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.status == "INSUFFICIENT_DATA"
    assert "ASOF_AFTER_EVALUATION_TS" in result.reason_codes
    # A future-dated asof must never carry any usable computed momentum
    # primitive -- not merely a rejected top-level status.
    assert result.data_quality != DataQuality.OK
    assert result.data_quality == DataQuality.FUTURE_ASOF
    assert result.macd_value is None
    assert result.signal_value is None
    assert result.histogram_value is None
    assert result.histogram_delta is None


def test_future_asof_with_fully_valid_warmup_data_still_fails_closed():
    """Even when the supplied candle window is otherwise perfectly valid
    (full warmup, contiguous, finite), a future asof alone must still null
    every raw field -- proving the guard is not merely reachable only on
    already-broken input."""
    closes = _closes(WARMUP_BARS)
    evaluated_at = ASOF - timedelta(hours=4)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=evaluated_at, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.FUTURE_ASOF
    assert (
        result.macd_value,
        result.signal_value,
        result.histogram_value,
        result.histogram_delta,
    ) == (None, None, None, None)


def test_future_asof_snapshot_satisfies_persistence_raw_pairing_invariant():
    """Mirrors the DB `chk_momentum_evidence_raw_pairing` CHECK constraint
    (all four raw fields NULL together, or all four non-NULL together) so a
    future-asof snapshot can never persist a partial/usable raw row."""
    closes = _closes(WARMUP_BARS)
    evaluated_at = ASOF - timedelta(hours=4)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=evaluated_at, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    raw_fields = (result.macd_value, result.signal_value, result.histogram_value, result.histogram_delta)
    assert all(value is None for value in raw_fields)


def test_future_asof_persist_writes_null_raw_fields(monkeypatch):
    """Proves the write path itself, not just the in-memory dataclass,
    cannot leak a usable future-derived raw value into the persisted row."""
    from src.features.momentum_evidence_snapshot_v1 import persist_snapshot
    import src.operations.writer_capability_authorization_v1 as auth_module

    monkeypatch.setattr(
        auth_module,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )

    class _Cursor:
        def __init__(self):
            self.values = None

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, _sql, values):
            self.values = values
            return 1

    class _Conn:
        def __init__(self):
            self.cur = _Cursor()
            self.committed = False

        def cursor(self):
            return self.cur

        def commit(self):
            self.committed = True

    closes = _closes(WARMUP_BARS)
    evaluated_at = ASOF - timedelta(hours=4)
    snapshot = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=evaluated_at, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert snapshot.data_quality == DataQuality.FUTURE_ASOF

    conn = _Conn()
    persist_snapshot(conn, snapshot, authorization=object())

    # Positional values match the INSERT column order:
    # ..., macd_value, signal_value, histogram_value, histogram_delta, ...
    macd_idx = 11
    values = conn.cur.values
    assert values[macd_idx:macd_idx + 4] == (None, None, None, None)


def test_misaligned_replay_boundary_gap_fails_closed():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    # Introduce a mid-window gap by shifting one row's timestamp off the
    # fixed 4h grid; the window is no longer exactly contiguous.
    candles.loc[candles.index[5], "close_ts_utc"] = candles.loc[candles.index[5], "close_ts_utc"] - timedelta(hours=1)
    result = build_momentum_evidence(
        candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MALFORMED_SOURCE_CANDLE
    assert result.macd_value is None


def test_caller_supplied_rows_after_asof_fail_closed_as_input_defect():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    extra = _candles([closes[-1] + 1.0], end_ts=ASOF + timedelta(hours=4), candle_id_start=999)
    candles = pd.concat([candles, extra], ignore_index=True)
    with pytest.raises(MomentumEvidenceInputError, match="after asof_ts_utc"):
        build_momentum_evidence(
            candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
            asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
        )


def test_duplicate_close_ts_rows_fail_closed_as_input_defect():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    duplicate_row = candles.iloc[[-1]].copy()
    candles = pd.concat([candles, duplicate_row], ignore_index=True)
    with pytest.raises(MomentumEvidenceInputError, match="duplicate"):
        build_momentum_evidence(
            candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
            asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
        )


def test_malformed_numeric_candle_fails_closed():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    candles["close_price"] = candles["close_price"].astype(object)
    candles.loc[candles.index[-1], "close_price"] = "not-a-number"
    result = build_momentum_evidence(
        candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MALFORMED_SOURCE_CANDLE
    assert result.macd_value is None


def test_nan_close_price_fails_closed():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    candles.loc[candles.index[3], "close_price"] = math.nan
    result = build_momentum_evidence(
        candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MALFORMED_SOURCE_CANDLE
    assert result.macd_value is None


def test_positive_infinity_close_price_fails_closed():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    candles.loc[candles.index[-1], "close_price"] = math.inf
    result = build_momentum_evidence(
        candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MALFORMED_SOURCE_CANDLE
    assert result.macd_value is None


def test_negative_infinity_close_price_fails_closed():
    closes = _closes(WARMUP_BARS)
    candles = _candles(closes)
    candles.loc[candles.index[-1], "close_price"] = -math.inf
    result = build_momentum_evidence(
        candles=candles, asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.data_quality == DataQuality.MALFORMED_SOURCE_CANDLE
    assert result.macd_value is None


def test_unsupported_interval_fails_closed():
    closes = _closes(WARMUP_BARS)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code="1h",
    )
    assert result.data_quality == DataQuality.UNSUPPORTED_INTERVAL
    assert result.macd_value is None


def test_deterministic_model_id_and_version():
    closes = _closes(WARMUP_BARS)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert (result.model_id, result.model_version) == (MODEL_ID, MODEL_VERSION)


def test_deterministic_provenance_on_valid_row():
    closes = _closes(WARMUP_BARS)
    result = build_momentum_evidence(
        candles=_candles(closes), asof_ts_utc=ASOF, evaluated_at=ASOF, venue=VENUE,
        asset_id=ASSET_ID, market=MARKET, interval_code=INPUT_INTERVAL,
    )
    assert result.provenance["candle_id"] == WARMUP_BARS  # last candle_id (1-indexed start)
    assert result.provenance["venue"] == VENUE
    assert result.provenance["asset_id"] == ASSET_ID
    assert result.provenance["market"] == MARKET
    assert result.provenance["bar_count"] == WARMUP_BARS


def test_no_latest_fallback_fetch_bounds_to_asof():
    class _Cursor:
        def __init__(self):
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params):
            self.params = params

        def fetchall(self):
            return []

    class _Conn:
        def __init__(self):
            self.cur = _Cursor()

        def cursor(self):
            return self.cur

    conn = _Conn()
    fetch_candles_for_asof(conn, asset_id=ASSET_ID, venue=VENUE, asof_ts_utc=ASOF)
    # The upper bound parameter must equal asof exactly; there is no
    # "current time" or "latest row" parameter anywhere in the call.
    assert conn.cur.params[-1] == ASOF.replace(tzinfo=None)


def test_no_account_decision_planning_execution_imports():
    import ast
    from pathlib import Path

    source = Path("src/features/momentum_evidence_snapshot_v1.py").read_text()
    tree = ast.parse(source)
    forbidden = ("decision_gate", "execution_planner", "executor", "broker")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            names = [alias.name for alias in node.names]
            joined = module + " " + " ".join(names)
            assert not any(term in joined for term in forbidden), joined


def _code_body_excluding_module_docstring() -> str:
    """Source with the leading module docstring stripped, so prose that
    documents non-goals (e.g. "no rsi", "no BULLISH state") does not trip a
    naive substring check against the actual implementation below it."""
    import ast
    from pathlib import Path

    source = Path("src/features/momentum_evidence_snapshot_v1.py").read_text()
    tree = ast.parse(source)
    docstring_node = tree.body[0]
    lines = source.splitlines(keepends=True)
    return "".join(lines[docstring_node.end_lineno:])


def test_no_415_rsi_divergence_or_449_rotation_flip_duplication():
    import re

    body = _code_body_excluding_module_docstring().lower()
    assert re.search(r"\brsi\b", body) is None
    assert "divergence" not in body
    assert "rotation" not in body


def test_no_categorical_momentum_states_invented():
    body = _code_body_excluding_module_docstring()
    forbidden_states = (
        "EARLY_UP", "MOMENTUM_REVERSAL", "EXTENDED", "DEEP_NEGATIVE",
        "CROSS_PENDING", "BULLISH", "BEARISH",
    )
    for state in forbidden_states:
        assert state not in body
