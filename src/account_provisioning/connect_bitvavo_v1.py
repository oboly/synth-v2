"""
connect_bitvavo_v1 — post-provisioning activation handler.

Orchestrates: provision → load credential → snapshot → activation render.

Activation render creates all three required account pages:
  accounts/<profile>/wallet.html + wallet.json
  accounts/<profile>/open-orders-monitor.html + open-orders-monitor.json
  accounts/<profile>/profit-plan.html + profit-plan.json
  accounts/<profile>/index.html

All published files are written with mode 0644.

On ACCOUNT_ALREADY_CONNECTED: retries snapshot + render without
resubmitting credentials (safe retry path).

refresh_pending=False only when ALL three pages and their JSON
counterparts are created successfully.

Safety:
  broker_private_calls=1 (read-only: credential validation + snapshot)
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.account_provisioning.account_credential_loader_v1 import load_account_credential
from src.account_provisioning.account_provisioning_service_v1 import (
    AccountProvisioningService,
    AuthenticatedProfileIdentity,
    ProvisioningResult,
)
from src.account_provisioning.account_snapshot_service_v1 import take_first_snapshot

_BITVAVO_VENUE = "bitvavo"
_ACCOUNT_CONNECTION_READ_ONLY = "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")

# Required page stems — all three must exist for refresh_pending=False.
_REQUIRED_PAGE_STEMS = ("wallet", "open-orders-monitor", "profit-plan")


def _try_render_activation(
    *,
    profile_code: str,
    venue: str,
    output_root: Path,
    activation_renderer: Callable[..., Any],
) -> bool:
    try:
        activation_renderer(profile_code=profile_code, venue=venue, output_root=output_root)
        return True
    except Exception:
        return False


def _run_activation(
    *,
    prov: ProvisioningResult,
    conn_factory: Callable[[], Any],
    master_key_bytes: bytes,
    cred_repo_factory: Callable[[Any], Any],
    bitvavo_client_factory: Callable[[str, str], Any],
    activation_renderer: Callable[..., Any],
    venue: str,
    output_root: Path,
    now_utc: datetime,
) -> ProvisioningResult:
    """
    Load stored credential → take snapshot → render all three account pages.
    Returns updated ProvisioningResult with refresh_pending reflecting success.
    refresh_pending=False only when snapshot AND all required pages succeed.
    """
    trading_account_id = prov.trading_account_id
    assert trading_account_id is not None

    try:
        conn = conn_factory()
        try:
            plain = load_account_credential(
                conn,
                trading_account_id=trading_account_id,
                venue=venue,
                master_key_bytes=master_key_bytes,
                cred_repo_factory=cred_repo_factory,
            )
        finally:
            conn.close()
    except Exception:
        return dataclasses.replace(prov, refresh_pending=True, refresh_error_code="CREDENTIAL_LOAD_FAILED")

    try:
        client = bitvavo_client_factory(plain.api_key, plain.api_secret)
        snap_conn = conn_factory()
        try:
            snap = take_first_snapshot(
                snap_conn,
                trading_account_id=trading_account_id,
                venue=venue,
                bitvavo_client=client,
                now_utc=now_utc,
            )
        finally:
            snap_conn.close()
    except Exception:
        return dataclasses.replace(prov, refresh_pending=True, refresh_error_code="SNAPSHOT_FAILED")

    if not snap.ok:
        return dataclasses.replace(
            prov,
            refresh_pending=True,
            refresh_error_code=snap.error_code or "INITIAL_REFRESH_FAILED",
        )

    render_ok = _try_render_activation(
        profile_code=prov.profile_code or "",
        venue=venue,
        output_root=output_root,
        activation_renderer=activation_renderer,
    )
    return dataclasses.replace(
        prov,
        refresh_pending=not render_ok,
        refresh_error_code=None if render_ok else "ACTIVATION_RENDER_FAILED",
    )


def build_connect_bitvavo(
    *,
    provisioning_service: AccountProvisioningService,
    conn_factory: Callable[[], Any],
    master_key_bytes: bytes,
    cred_repo_factory: Callable[[Any], Any],
    bitvavo_client_factory: Callable[[str, str], Any],
    activation_renderer: Callable[..., Any] | None = None,
    output_root: Path | str | None = None,
    venue: str = _BITVAVO_VENUE,
) -> Callable[[AuthenticatedProfileIdentity, str, str, bool, datetime], ProvisioningResult]:
    """
    Build the connect_bitvavo callable for the WSGI runner.

    bitvavo_client_factory: called with (api_key, api_secret) → returns broker client.
    activation_renderer: called with (profile_code, venue, output_root) keyword args.
        Must write wallet.html, open-orders-monitor.html, and profit-plan.html
        (plus their JSON counterparts) to output_root/accounts/<profile>/.
        All files must be created with mode 0644.
        Defaults to the production three-page renderer.
        Pass a mock in tests — must not make real broker calls.
    output_root: where rendered HTML is written. Defaults to /var/www/html/synth.
    """
    effective_root = Path(output_root) if output_root is not None else DEFAULT_OUTPUT_ROOT
    effective_renderer = activation_renderer if activation_renderer is not None else _default_activation_renderer

    def connect(
        identity: AuthenticatedProfileIdentity,
        api_key: str,
        api_secret: str,
        confirmed: bool,
        now_utc: datetime,
    ) -> ProvisioningResult:
        prov = provisioning_service.provision_bitvavo_account(
            identity=identity,
            api_key=api_key,
            api_secret=api_secret,
            withdrawal_disabled_confirmed=confirmed,
            conn_factory=conn_factory,
            now_utc=now_utc,
        )

        if prov.ok and prov.trading_account_id is not None:
            return _run_activation(
                prov=prov,
                conn_factory=conn_factory,
                master_key_bytes=master_key_bytes,
                cred_repo_factory=cred_repo_factory,
                bitvavo_client_factory=bitvavo_client_factory,
                activation_renderer=effective_renderer,
                venue=venue,
                output_root=effective_root,
                now_utc=now_utc,
            )

        # Safe retry: account already connected → attempt snapshot + render with stored credential.
        # Does not resubmit credentials; uses the encrypted credential already in the DB.
        if (
            not prov.ok
            and prov.error_code == "ACCOUNT_ALREADY_CONNECTED"
            and prov.trading_account_id is not None
        ):
            retry_base = ProvisioningResult(
                ok=True,
                profile_code=prov.profile_code,
                account_connection_state=_ACCOUNT_CONNECTION_READ_ONLY,
                landing_path=prov.landing_path,
                refresh_pending=True,
                trading_account_id=prov.trading_account_id,
            )
            return _run_activation(
                prov=retry_base,
                conn_factory=conn_factory,
                master_key_bytes=master_key_bytes,
                cred_repo_factory=cred_repo_factory,
                bitvavo_client_factory=bitvavo_client_factory,
                activation_renderer=effective_renderer,
                venue=venue,
                output_root=effective_root,
                now_utc=now_utc,
            )

        return prov

    return connect


def _default_activation_renderer(*, profile_code: str, venue: str, output_root: Path) -> None:
    """
    Production activation renderer.

    Creates all required pages under output_root/accounts/<profile>/:
      wallet.html + wallet.json
      open-orders-monitor.html + open-orders-monitor.json
      profit-plan.html + profit-plan.json
      index.html

    All files are written with mode 0644.
    Uses its own DB connections (get_connection from src.common.db).
    Handles missing fib/zone data gracefully — renders empty-state pages.
    """
    import json
    import uuid

    from src.market_data.native_short_fib_context_v1 import DEFAULT_ROWS_CSV as _NATIVE_SHORT_ROWS
    from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access
    from src.reporting.account_profile_home_v1 import write_account_profile_home
    from src.reporting.account_scoped_short_trader_dashboard_v1 import (
        classify_market_prices_by_market,
        default_page_paths,
        load_account_scoped_short_dashboard_context,
        public_page_href,
    )
    from src.reporting.account_wallet_dashboard_v1 import load_and_write_wallet_dashboard
    from src.reporting.dashboard_style_v1 import cockpit_nav
    from src.reporting.manual_short_trader_dashboard_v1 import (
        build_all_sections,
        build_json_snapshot as oom_build_json,
        render_full_html as oom_render_html,
    )
    from src.reporting.manual_short_trader_profit_plan_v1 import (
        build_json_snapshot as pp_build_json,
        render_full_html as pp_render_html,
    )
    from src.reporting.run_manual_short_trader_profit_plan_v1 import (
        DEFAULT_FIB_MAP_ROWS,
        build_cards,
        fetch_market_target_history_by_symbol,
        load_zone_contexts,
    )

    access = resolve_dashboard_profile_access(account_profile=profile_code, venue=venue)
    account_code = access.trading_account_stable_ref
    display_timezone = access.display_timezone

    # 1. Wallet dashboard (wallet.html + wallet.json)
    _, wallet_html, wallet_json = load_and_write_wallet_dashboard(
        profile=profile_code,
        account_code=account_code,
        venue=venue,
        display_timezone=display_timezone,
        output_root=output_root,
    )
    wallet_html.chmod(0o644)
    wallet_json.chmod(0o644)

    # 2. Profile home (index.html)
    index_html = write_account_profile_home(
        profile_code=profile_code,
        venue=venue,
        account_code=account_code,
        display_timezone=display_timezone,
        output_root=output_root,
    )
    index_html.chmod(0o644)

    # Load account scope once — shared between open-orders-monitor and profit-plan.
    context = load_account_scoped_short_dashboard_context(
        profile=profile_code,
        account_code=account_code,
        venue=venue,
    )
    price_display = classify_market_prices_by_market(context=context)
    prices = {m: d.safe_price for m, d in price_display.items() if d.safe_price is not None}
    price_status = {m: d.status for m, d in price_display.items()}
    price_age_min = {m: d.age_min for m, d in price_display.items()}
    nav_html = cockpit_nav(account_profile=profile_code).strip()

    sections = build_all_sections(
        list(context.orders),
        list(context.balances),
        prices,
        price_status_by_market=price_status,
        price_age_min_by_market=price_age_min,
    )

    # 3. Open-orders-monitor (open-orders-monitor.html + open-orders-monitor.json)
    oom_html, oom_json = default_page_paths(
        output_root=output_root, profile=profile_code, page_stem="open-orders-monitor"
    )
    oom_html.parent.mkdir(parents=True, exist_ok=True)
    oom_html.write_text(
        oom_render_html(sections, broker_mode="db_snapshot", nav_html=nav_html),
        encoding="utf-8",
    )
    oom_html.chmod(0o644)
    oom_json.write_text(
        json.dumps(oom_build_json(sections, broker_mode="db_snapshot"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    oom_json.chmod(0o644)

    # 4. Profit plan (profit-plan.html + profit-plan.json)
    render_id = str(uuid.uuid4())
    writer_id = str(uuid.uuid4())

    zone_contexts = load_zone_contexts(
        markets=list(context.markets),
        prices=prices,
        swing_anchors={},
        recent_lows={},
        native_short_rows_path=Path(_NATIVE_SHORT_ROWS),
        fib_map_rows_path=DEFAULT_FIB_MAP_ROWS,
    )
    history = fetch_market_target_history_by_symbol(
        venue=venue,
        activation_ts_by_symbol=zone_contexts.activation_ts_by_symbol,
    )
    orders_by_symbol = {
        section.symbol: (section.buy_orders, section.sell_orders)
        for section in sections
    }
    cards = build_cards(
        list(context.markets),
        prices,
        price_status,
        price_age_min,
        zone_contexts.input_status_by_symbol,
        zone_contexts.coverage_status_by_symbol,
        zone_contexts.display_state_by_symbol,
        zone_contexts.fib_ext_by_symbol,
        zone_contexts.reentry_by_symbol,
        history,
        orders_by_symbol,
    )

    pp_html, pp_json = default_page_paths(
        output_root=output_root, profile=profile_code, page_stem="profit-plan"
    )
    pp_html.parent.mkdir(parents=True, exist_ok=True)
    pp_html.write_text(
        pp_render_html(
            cards,
            broker_mode="db_snapshot",
            monitor_link=public_page_href(profile=profile_code, page_stem="open-orders-monitor"),
            nav_html=nav_html,
            storage_scope=profile_code,
            render_id=render_id,
            writer_instance_id=writer_id,
        ),
        encoding="utf-8",
    )
    pp_html.chmod(0o644)
    pp_json.write_text(
        json.dumps(
            pp_build_json(
                cards,
                broker_mode="db_snapshot",
                writer_instance_id=writer_id,
                render_id=render_id,
            ),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pp_json.chmod(0o644)
