from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from src.research.run_momentum_flow_exhaustion_phase_c_v1 import ReplayConfig, build_replay_rows, build_summary


def _candles(count: int = 40, *, market: str = "BTC-EUR", direction: int = 1) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC); rows=[]
    for i in range(count):
        t=start+timedelta(hours=4*i); close=100.0+direction*i*0.5; op=close-direction*0.35
        rows.append({"market":market,"interval":"4h","start_ts":t,"end_ts":t+timedelta(hours=4),
                     "open":op,"high":max(op,close)+0.15,"low":min(op,close)-0.15,
                     "close":close,"volume":1000.0,"is_final":True})
    return pd.DataFrame(rows)


def _inject_buyer_exhaustion(df: pd.DataFrame, index: int) -> pd.DataFrame:
    out=df.copy(); prev=float(out.iloc[index-1]["close"])
    out.loc[index,["open","high","low","close","volume"]]=[prev+0.05,prev+1.4,prev-0.15,prev+0.08,5000.0]
    return out


def test_replay_separates_feature_asof_from_forward_outcomes() -> None:
    df=_inject_buyer_exhaustion(_candles(),24)
    cfg=ReplayConfig(interval="4h",horizon_bars=(1,3,6),sample_every_n=1)
    rows=build_replay_rows(df,cfg)
    target=[r for r in rows if r["asof_ts_utc"]==pd.Timestamp(df.iloc[24]["end_ts"]).isoformat()][0]
    assert target["buyer_exhaustion_score"] >= 70.0
    assert target["complete_6b"] is True
    assert target["return_1b_pct"] is not None


def test_buyer_side_return_is_negative_of_raw_return() -> None:
    df=_inject_buyer_exhaustion(_candles(),24)
    rows=build_replay_rows(df,ReplayConfig(horizon_bars=(1,),sample_every_n=1))
    target=[r for r in rows if r["asof_ts_utc"]==pd.Timestamp(df.iloc[24]["end_ts"]).isoformat()][0]
    assert target["exhaustion_side"] == "BUYER"
    assert target["side_return_1b_pct"] == -target["return_1b_pct"]


def test_seller_side_return_matches_raw_return() -> None:
    df=_candles(direction=-1); index=24; prev=float(df.iloc[index-1]["close"])
    df.loc[index,["open","high","low","close","volume"]]=[prev-0.05,prev+0.15,prev-1.4,prev-0.08,5000.0]
    rows=build_replay_rows(df,ReplayConfig(horizon_bars=(1,),sample_every_n=1))
    target=[r for r in rows if r["asof_ts_utc"]==pd.Timestamp(df.iloc[index]["end_ts"]).isoformat()][0]
    assert target["exhaustion_side"] == "SELLER"
    assert target["side_return_1b_pct"] == target["return_1b_pct"]


def test_future_price_mutation_changes_outcome_not_candidate() -> None:
    df=_inject_buyer_exhaustion(_candles(),24); cfg=ReplayConfig(horizon_bars=(1,),sample_every_n=1)
    before=build_replay_rows(df,cfg); ts=pd.Timestamp(df.iloc[24]["end_ts"]).isoformat()
    row_before=[r for r in before if r["asof_ts_utc"]==ts][0]
    mutated=df.copy(); mutated.loc[25,["open","high","low","close"]]=[200.0,210.0,190.0,205.0]
    after=build_replay_rows(mutated,cfg); row_after=[r for r in after if r["asof_ts_utc"]==ts][0]
    assert row_after["buyer_exhaustion_score"] == row_before["buyer_exhaustion_score"]
    assert row_after["return_1b_pct"] != row_before["return_1b_pct"]


def test_incomplete_forward_window_is_fail_closed() -> None:
    rows=build_replay_rows(_candles(26),ReplayConfig(horizon_bars=(1,6),sample_every_n=1))
    assert rows
    assert all(r["complete_6b"] for r in rows)  # replay excludes as-ofs lacking max horizon


def test_summary_groups_score_bucket_state_and_side() -> None:
    df=_inject_buyer_exhaustion(_candles(),24); cfg=ReplayConfig(horizon_bars=(1,3),sample_every_n=1)
    rows=build_replay_rows(df,cfg); summary=build_summary(rows,cfg)
    assert summary["row_count"] == len(rows)
    assert "70_100" in summary["cohorts"]["score_bucket"]
    assert "BUYER" in summary["cohorts"]["exhaustion_side"] or "NONE" in summary["cohorts"]["exhaustion_side"]


def test_low_score_baselines_still_have_side_specific_reversal_outcomes() -> None:
    rows=build_replay_rows(_candles(),ReplayConfig(horizon_bars=(1,),sample_every_n=1))
    low=[r for r in rows if r["buyer_exhaustion_score"] < 25.0][0]
    assert low["exhaustion_side"] == "NONE"
    assert low["buyer_reversal_return_1b_pct"] == -low["return_1b_pct"]
    assert low["seller_reversal_return_1b_pct"] == low["return_1b_pct"]


def test_summary_has_independent_buyer_and_seller_score_calibration_cohorts() -> None:
    df=_inject_buyer_exhaustion(_candles(),24); cfg=ReplayConfig(horizon_bars=(1,),sample_every_n=1)
    summary=build_summary(build_replay_rows(df,cfg),cfg)
    assert "buyer_score_bucket" in summary["cohorts"]
    assert "seller_score_bucket" in summary["cohorts"]
    assert "avg_reversal_return_1b_pct" in summary["cohorts"]["buyer_score_bucket"]["70_100"]
