"""Tests for the canonical ETH/BTC leadership snapshot producer (#721, under
#305). Market-only, replay-safe: no account/execution coupling, no invented
freshness rule, no invented leadership band."""
from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.features.eth_btc_leadership_snapshot_v1 import (
    DATA_STATUS_AVAILABLE,
    DATA_STATUS_INSUFFICIENT,
    EFFECTIVE_HORIZON,
    FRESHNESS_FRESH,
    FRESHNESS_INSUFFICIENT_DATA,
    FRESHNESS_STALE,
    INPUT_INTERVAL,
    LOOKBACK_DELTA,
    LOOKBACK_HORIZON,
    MODEL_ID,
    MODEL_VERSION,
    BTC_SYMBOL,
    ETH_SYMBOL,
    EthBtcLeadershipInputError,
    ReasonCode,
    build_snapshot,
    resolve_unique_symbol_markets,
)

ASOF = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
LOOKBACK = ASOF - timedelta(hours=24)
EVALUATED = ASOF + timedelta(minutes=5)

VENUE = "bitvavo"
BTC_MARKET = "BTC-EUR"
ETH_MARKET = "ETH-EUR"


def _row(close_ts_utc, close_price, *, count=1):
    return {
        "latest_close_ts_utc": close_ts_utc,
        "expected_close_row_count": count,
        "expected_close_price": close_price,
    }


def _build(**overrides):
    kwargs = dict(
        btc_asof_row=_row(ASOF, "60000.00000000"),
        eth_asof_row=_row(ASOF, "3000.00000000"),
        btc_lookback_row=_row(LOOKBACK, "58000.00000000"),
        eth_lookback_row=_row(LOOKBACK, "2900.00000000"),
        asof_ts_utc=ASOF,
        lookback_ts_utc=LOOKBACK,
        evaluated_at=EVALUATED,
        venue=VENUE,
        interval_code=INPUT_INTERVAL,
        btc_market=BTC_MARKET,
        eth_market=ETH_MARKET,
    )
    kwargs.update(overrides)
    return build_snapshot(**kwargs)


def test_aligned_btc_eth_asof_computes_exact_raw_math():
    snap = _build()
    assert snap.freshness == FRESHNESS_FRESH
    assert snap.data_status == DATA_STATUS_AVAILABLE
    assert snap.model_id == MODEL_ID
    assert snap.model_version == MODEL_VERSION
    assert snap.input_interval == INPUT_INTERVAL
    assert snap.lookback_horizon == LOOKBACK_HORIZON
    assert snap.effective_horizon == EFFECTIVE_HORIZON
    assert snap.reason_codes == (ReasonCode.UNMAPPED_HORIZON,)

    btc_return = ((Decimal("60000.00000000") / Decimal("58000.00000000")) - 1) * 100
    eth_return = ((Decimal("3000.00000000") / Decimal("2900.00000000")) - 1) * 100
    assert snap.btc_return_pct == btc_return
    assert snap.eth_return_pct == eth_return
    assert snap.eth_minus_btc_return_pct == eth_return - btc_return

    ratio_start = Decimal("2900.00000000") / Decimal("58000.00000000")
    ratio_end = Decimal("3000.00000000") / Decimal("60000.00000000")
    assert snap.eth_btc_ratio_start == ratio_start
    assert snap.eth_btc_ratio_end == ratio_end
    assert snap.eth_btc_ratio_change_pct == ((ratio_end / ratio_start) - 1) * 100


def test_missing_btc_candle_fails_closed_insufficient_data():
    snap = _build(btc_asof_row=_row(None, None, count=0))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert snap.data_status == DATA_STATUS_INSUFFICIENT
    assert ReasonCode.MISSING_BTC_CANDLE in snap.reason_codes
    assert snap.btc_return_pct is None
    assert snap.eth_btc_ratio_end is None


def test_missing_eth_candle_fails_closed_insufficient_data():
    snap = _build(eth_asof_row=_row(None, None, count=0))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.MISSING_ETH_CANDLE in snap.reason_codes
    assert snap.eth_return_pct is None


def test_stale_btc_candle_yields_stale_state():
    stale_ts = ASOF - timedelta(days=1)
    snap = _build(btc_asof_row=_row(stale_ts, "59000.0", count=0))
    assert snap.freshness == FRESHNESS_STALE
    assert snap.data_status == DATA_STATUS_INSUFFICIENT
    assert ReasonCode.STALE_BTC_CANDLE in snap.reason_codes
    assert snap.btc_return_pct is None


def test_stale_eth_candle_yields_stale_state():
    stale_ts = ASOF - timedelta(days=1)
    snap = _build(eth_asof_row=_row(stale_ts, "2950.0", count=0))
    assert snap.freshness == FRESHNESS_STALE
    assert ReasonCode.STALE_ETH_CANDLE in snap.reason_codes


def test_mismatched_timestamps_fail_closed():
    # BTC's persisted boundary lags the requested asof by one interval (the
    # exact-boundary count is 0), so a naive "closest available" comparison
    # against ETH's exact-asof row would silently compare misaligned
    # timestamps. This must fail closed instead of comparing them.
    mismatched_ts = ASOF - timedelta(days=1)
    snap = _build(btc_asof_row=_row(mismatched_ts, "59500.0", count=0))
    assert snap.freshness in (FRESHNESS_STALE, FRESHNESS_INSUFFICIENT_DATA)
    assert snap.data_status == DATA_STATUS_INSUFFICIENT
    assert snap.btc_return_pct is None
    assert snap.eth_btc_ratio_change_pct is None


def test_future_asof_fails_closed():
    snap = _build(evaluated_at=ASOF - timedelta(minutes=1))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.ASOF_AFTER_EVALUATION_TS in snap.reason_codes
    assert snap.btc_return_pct is None


def test_insufficient_lookback_history_fails_closed():
    snap = _build(
        btc_lookback_row=_row(None, None, count=0),
        eth_lookback_row=_row(None, None, count=0),
    )
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.MISSING_BTC_LOOKBACK_CANDLE in snap.reason_codes
    assert ReasonCode.MISSING_ETH_LOOKBACK_CANDLE in snap.reason_codes
    assert snap.eth_btc_ratio_start is None


def test_raw_return_math_exact():
    snap = _build(btc_asof_row=_row(ASOF, "70000"), btc_lookback_row=_row(LOOKBACK, "70000"))
    assert snap.btc_return_pct == Decimal("0")


def test_eth_btc_ratio_math_exact():
    snap = _build(
        btc_asof_row=_row(ASOF, "50000"),
        eth_asof_row=_row(ASOF, "2500"),
        btc_lookback_row=_row(LOOKBACK, "40000"),
        eth_lookback_row=_row(LOOKBACK, "2000"),
    )
    assert snap.eth_btc_ratio_start == Decimal("0.05")
    assert snap.eth_btc_ratio_end == Decimal("0.05")
    assert snap.eth_btc_ratio_change_pct == Decimal("0")


def test_deterministic_model_and_provenance_across_identical_inputs():
    snap1 = _build()
    snap2 = _build()
    assert snap1.model_id == snap2.model_id == MODEL_ID
    assert snap1.model_version == snap2.model_version == MODEL_VERSION
    assert snap1.provenance == snap2.provenance
    assert snap1.btc_return_pct == snap2.btc_return_pct
    assert snap1.eth_btc_ratio_change_pct == snap2.eth_btc_ratio_change_pct


def test_model_identity_is_fixed_not_inferred_from_row_data():
    # No upstream model_version is persisted/consumed by this producer (the
    # candle series carries none), so model identity is a fixed, reviewed
    # constant rather than something an input row could override.
    snap = _build()
    assert snap.model_id == "eth_btc_leadership_snapshot"
    assert snap.model_version == "1.0"


def test_historical_replay_never_falls_back_to_latest_row():
    # The table's newest close is *after* the historical asof being replayed,
    # but no row exists at the exact asof itself (count=0). A latest-row
    # fallback would wrongly treat this as fresh; this must fail closed.
    later_latest = ASOF + timedelta(days=1)
    snap = _build(btc_asof_row=_row(later_latest, None, count=0))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.FUTURE_CANDLE_BOUNDARY in snap.reason_codes
    assert snap.btc_return_pct is None


def test_unsupported_input_interval_raises():
    with pytest.raises(EthBtcLeadershipInputError):
        _build(interval_code="4h")


def test_lookback_horizon_alignment_is_enforced():
    assert LOOKBACK_DELTA == timedelta(hours=24)
    misaligned_lookback = ASOF - timedelta(hours=23)
    snap = _build(lookback_ts_utc=misaligned_lookback)
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert snap.data_status == DATA_STATUS_INSUFFICIENT
    assert ReasonCode.LOOKBACK_HORIZON_MISALIGNED in snap.reason_codes
    assert snap.lookback_horizon == LOOKBACK_HORIZON
    assert snap.btc_return_pct is None
    assert snap.eth_btc_ratio_start is None


def test_lookback_horizon_alignment_rejects_longer_gap():
    misaligned_lookback = ASOF - timedelta(hours=25)
    snap = _build(lookback_ts_utc=misaligned_lookback)
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.LOOKBACK_HORIZON_MISALIGNED in snap.reason_codes


def test_exact_24h_lookback_is_accepted():
    snap = _build(lookback_ts_utc=ASOF - LOOKBACK_DELTA)
    assert snap.freshness == FRESHNESS_FRESH
    assert ReasonCode.LOOKBACK_HORIZON_MISALIGNED not in snap.reason_codes


def test_zero_eth_lookback_price_fails_closed_no_exception():
    snap = _build(eth_lookback_row=_row(LOOKBACK, "0"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert snap.data_status == DATA_STATUS_INSUFFICIENT
    assert ReasonCode.NONPOSITIVE_CANDLE_PRICE in snap.reason_codes
    assert snap.eth_return_pct is None
    assert snap.eth_btc_ratio_start is None


def test_negative_eth_asof_price_fails_closed_no_exception():
    snap = _build(eth_asof_row=_row(ASOF, "-1"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.NONPOSITIVE_CANDLE_PRICE in snap.reason_codes
    assert snap.eth_return_pct is None


def test_zero_btc_lookback_price_fails_closed_no_exception():
    snap = _build(btc_lookback_row=_row(LOOKBACK, "0"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.NONPOSITIVE_CANDLE_PRICE in snap.reason_codes
    assert snap.btc_return_pct is None
    assert snap.eth_btc_ratio_start is None


def test_negative_btc_asof_price_fails_closed_no_exception():
    snap = _build(btc_asof_row=_row(ASOF, "-100"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.NONPOSITIVE_CANDLE_PRICE in snap.reason_codes
    assert snap.btc_return_pct is None


def test_resolve_unique_symbol_markets_accepts_canonical_btc_eur_eth_eur():
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-EUR"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-EUR"},
    ]
    resolved = resolve_unique_symbol_markets(rows, venue="bitvavo")
    assert resolved[BTC_SYMBOL]["market"] == "BTC-EUR"
    assert resolved[ETH_SYMBOL]["market"] == "ETH-EUR"


def test_resolve_unique_symbol_markets_fails_closed_on_zero_eligible_rows():
    rows = [{"symbol": "ETH", "asset_id": 2, "market": "ETH-EUR"}]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="bitvavo")


def test_resolve_unique_symbol_markets_rejects_non_bitvavo_venue():
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-EUR"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-EUR"},
    ]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="kraken")


def test_resolve_unique_symbol_markets_rejects_non_eur_btc_market():
    # A tradeable BTC-USD market must never substitute for canonical BTC-EUR.
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-USD"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-EUR"},
    ]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="bitvavo")


def test_resolve_unique_symbol_markets_rejects_non_eur_eth_market():
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-EUR"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-USDT"},
    ]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="bitvavo")


def test_resolve_unique_symbol_markets_rejects_mismatched_quote_pair():
    # Neither leg is canonical EUR-quoted -- both must be rejected, not
    # accepted merely because a BTC row and an ETH row both exist.
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-USDT"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-USD"},
    ]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="bitvavo")


def test_resolve_unique_symbol_markets_fails_closed_on_ambiguous_canonical_btc_rows():
    # Two distinct eligible rows both quoting the exact canonical BTC-EUR
    # market -- must never pick an arbitrary first/last row.
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-EUR"},
        {"symbol": "BTC", "asset_id": 3, "market": "BTC-EUR"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-EUR"},
    ]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="bitvavo")


def test_resolve_unique_symbol_markets_fails_closed_on_ambiguous_canonical_eth_rows():
    rows = [
        {"symbol": "BTC", "asset_id": 1, "market": "BTC-EUR"},
        {"symbol": "ETH", "asset_id": 2, "market": "ETH-EUR"},
        {"symbol": "ETH", "asset_id": 4, "market": "ETH-EUR"},
    ]
    with pytest.raises(EthBtcLeadershipInputError):
        resolve_unique_symbol_markets(rows, venue="bitvavo")


def test_fetch_btc_eth_markets_rejects_non_bitvavo_venue_before_any_query():
    from src.features.eth_btc_leadership_snapshot_v1 import fetch_btc_eth_markets

    with pytest.raises(EthBtcLeadershipInputError):
        fetch_btc_eth_markets(conn=None, venue="kraken")


def test_malformed_eth_lookback_price_fails_closed_no_exception():
    snap = _build(eth_lookback_row=_row(LOOKBACK, "not-a-number"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.MALFORMED_CANDLE_BOUNDARY in snap.reason_codes
    assert snap.eth_return_pct is None


def test_nan_btc_asof_price_fails_closed_no_exception():
    snap = _build(btc_asof_row=_row(ASOF, "NaN"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.MALFORMED_CANDLE_BOUNDARY in snap.reason_codes
    assert snap.btc_return_pct is None


def test_infinity_eth_asof_price_fails_closed_no_exception():
    snap = _build(eth_asof_row=_row(ASOF, "Infinity"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.MALFORMED_CANDLE_BOUNDARY in snap.reason_codes
    assert snap.eth_return_pct is None


def test_negative_infinity_btc_lookback_price_fails_closed_no_exception():
    snap = _build(btc_lookback_row=_row(LOOKBACK, "-Infinity"))
    assert snap.freshness == FRESHNESS_INSUFFICIENT_DATA
    assert ReasonCode.MALFORMED_CANDLE_BOUNDARY in snap.reason_codes
    assert snap.btc_return_pct is None


def test_no_account_or_execution_imports():
    import ast

    import src.features.eth_btc_leadership_snapshot_v1 as mod

    tree = ast.parse(inspect.getsource(mod))
    imported_modules = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        if isinstance(node, ast.Import)
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    for forbidden in ("decision_gate", "execution_planner", "executor", "broker", "selection_engine"):
        assert not any(forbidden in imported for imported in imported_modules)
