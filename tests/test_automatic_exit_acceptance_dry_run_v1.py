from datetime import timedelta
from decimal import Decimal

from src.exit_policy.automatic_exit_acceptance_dry_run_v1 import run_automatic_exit_acceptance_dry_run_v1
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    build_runtime_item_v1, load_eligible_trading_accounts,
    load_latest_complete_account_state_bundle, load_positive_positions,
)
from tests.automatic_exit_runtime_fixtures_v1 import FakeConnection, TS, insert_market_price, seed_happy_path


def test_acceptance_dry_run_uses_canonical_phase4b_staged_plan() -> None:
    now = TS + timedelta(minutes=5)
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    account = load_eligible_trading_accounts(conn, venue="bitvavo")[0]
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=now)
    item = build_runtime_item_v1(conn, account=account, bundle=bundle, position=load_positive_positions(conn, bundle=bundle)[0], now=now)
    result = run_automatic_exit_acceptance_dry_run_v1(conn, item=item, evaluation_ts_utc=now)
    assert result.acceptance_state == "PASS"
    assert result.planner_state == "STAGED"
    assert result.plan_hash is not None
    assert "executor_calls=0" in result.safety_markers
