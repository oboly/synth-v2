"""
run_exact_account_state_refresh_v1 — Exact-account private-read account-state refresh.

Dedicated seam for LIVE-capable trading accounts. Identity is resolved by
exact `trading_account_id` + `venue` only — never by app-profile primary
link. `linked_account_resolver_v1.resolve_primary_linked_account` fails
closed on `account_mode='live'` (`LIVE_TRADING_ENABLED`) because it is the
profile-primary dashboard-refresh path
(`run_account_wallet_refresh_v1.py`), which must remain read-only-only
identity space. This runner is the separate, explicitly bounded path for an
operator who already knows the exact `trading_account_id` of a LIVE-capable
account and wants private-read account-state evidence without going through
a profile link at all.

`linked_account_resolver_v1` is not imported here and is not modified by
this module. `resolve_private_read_credential`/`resolve_account_identity`
(`src/account/private_read_credential_resolver_v1.py`) already resolve pure
`trading_account_id` identity without any `account_mode`/`live_trading_enabled`
restriction — this module relies on that existing, unmodified contract
rather than adding a new one.

Credential source: canonical encrypted DB credential only, resolved for the
same exact `trading_account_id` + `venue`, requiring an ACTIVE, validated
`READ_ONLY_PRIVATE` binding with `allowed_private_read=1`. No inference of
private-read permission from any other field. No legacy profile/global env
credential fallback.

Persistence reuses the same canonical snapshot machinery as
`run_account_wallet_refresh_v1.py`: balance snapshot rows, derived position
rows, the open-order snapshot header, and the single-transaction
`account_state_snapshot_run_v1` COMPLETE bundle. No persistence logic is
duplicated here.

Safety:
  broker_private_calls=2 (get_balance + get_open_orders)
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import argparse
import sys

from src.account.account_snapshot_models_v1 import ExactAccountStateRefreshResult
from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_private_read_bitvavo_client_from_env,
)
from src.account.run_account_wallet_refresh_v1 import (
    discover_account_assets,
    normalize_balance_rows,
    normalize_order_rows,
    utc_now_naive,
    write_aligned_account_state_snapshot,
)
from src.common.db import get_db_connection

RUNNER_NAME = "exact_account_state_refresh_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exact-account private-read account-state refresh for LIVE-capable "
            "trading accounts. Identity is exact trading_account_id + venue "
            "only; no app-profile fallback. Private read-only; no broker "
            "writes; no order submission."
        )
    )
    parser.add_argument(
        "--trading-account-id",
        required=True,
        type=int,
        metavar="ID",
        help="Exact trading_account_id. No profile/app-code fallback.",
    )
    parser.add_argument("--venue", required=True, metavar="VENUE")
    parser.add_argument(
        "--write-db",
        action="store_true",
        default=False,
        help="Persist snapshots to DB. Dry-run if omitted.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument(
        "--output",
        choices=("summary", "none"),
        default="summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    conn = get_db_connection()
    try:
        try:
            resolved = resolve_private_read_bitvavo_client_from_env(
                conn,
                trading_account_id=args.trading_account_id,
                venue=args.venue,
                timeout_seconds=args.timeout_seconds,
            )
        except PrivateReadCredentialResolutionError as exc:
            print(f"[error] credential resolution: {exc}", file=sys.stderr)
            return 1

        identity = resolved.identity
        if identity.trading_account_id != args.trading_account_id:
            print("[error] ACCOUNT_IDENTITY_MISMATCH", file=sys.stderr)
            return 1
        if identity.venue != args.venue:
            print("[error] ACCOUNT_VENUE_MISMATCH", file=sys.stderr)
            return 1

        client = resolved.client
        trading_account_id = identity.trading_account_id
        account_code = identity.account_code
        venue = identity.venue

        print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"trading_account_id={trading_account_id} account_code={account_code}")
        print(f"venue={venue} account_mode={identity.account_mode}")
        print(f"credential_source={resolved.profile.credential_source}")
        print(f"credential_profile_id={resolved.profile.trading_account_credential_id}")
        print(f"permission_scope={resolved.profile.permission_scope}")
        print(f"validation_state={resolved.profile.validation_state}")
        print("[INFO] private read-only; no broker writes; no order submission")

        refresh_started_ts_utc = utc_now_naive()
        try:
            raw_balances = client.get_balance()
        except PermissionError as exc:
            print(f"[error] private read gate: {exc}", file=sys.stderr)
            return 1

        try:
            raw_orders = client.get_open_orders()
        except PermissionError as exc:
            print(f"[error] private read gate: {exc}", file=sys.stderr)
            return 1

        balances = normalize_balance_rows(raw_balances)
        orders = normalize_order_rows(raw_orders)
        snapshot_ts_utc = utc_now_naive()

        aa_inserted = 0
        aa_existing = 0
        position_count: int | None = None
        account_state_run_id: int | None = None

        if args.write_db:
            try:
                aa_inserted, aa_existing = discover_account_assets(
                    conn,
                    trading_account_id=trading_account_id,
                    venue=venue,
                    balances=balances,
                    orders=orders,
                )
                account_state_run = write_aligned_account_state_snapshot(
                    conn,
                    trading_account_id=trading_account_id,
                    account_code=account_code,
                    venue=venue,
                    balances=balances,
                    orders=orders,
                    refresh_started_ts_utc=refresh_started_ts_utc,
                    snapshot_ts_utc=snapshot_ts_utc,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            position_count = account_state_run.position_snapshot_count
            account_state_run_id = account_state_run.account_state_snapshot_run_id

        result = ExactAccountStateRefreshResult(
            trading_account_id=trading_account_id,
            account_code=account_code,
            venue=venue,
            account_mode=identity.account_mode,
            snapshot_ts_utc=snapshot_ts_utc,
            balance_count=len(balances),
            order_count=len(orders),
            position_count=position_count,
            account_asset_inserted=aa_inserted,
            account_asset_existing=aa_existing,
        )

        if args.output == "summary":
            print(f"snapshot_ts_utc={result.snapshot_ts_utc.isoformat(sep=' ')}")
            print(f"balance_count={result.balance_count}")
            print(f"order_count={result.order_count}")
            if args.write_db:
                assert account_state_run_id is not None
                print(f"position_count={result.position_count}")
                print(f"account_asset_inserted={result.account_asset_inserted}")
                print(f"account_asset_existing={result.account_asset_existing}")
                print(f"account_state_snapshot_run_id={account_state_run_id}")
            else:
                print("[DRY_RUN] --write-db not set; no DB writes performed")
            print("broker_private_calls=2")
            print("broker_writes=0")
            print("order_submission=0")
            print("live_orders=0")
            print("decision_gate=none")
            print("execution_planner=none")
            print("executor=none")

        return 0

    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
