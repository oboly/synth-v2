# Synth MVP Read-only Cockpit V1

## Goal

Render a read-only online cockpit for global account-agnostic pages. Account dashboards render separately through the per-profile account wrapper.

## Outputs

- /var/www/html/synth/index.html
- /var/www/html/synth/paper-advice.html
- /var/www/html/synth/entry-candidates.html
- /var/www/html/synth/about.html
- /var/www/html/synth/assets/brand/synth/favicon.svg
- /var/www/html/synth/assets/brand/synth/favicon-16x16.png
- /var/www/html/synth/assets/brand/synth/favicon-32x32.png
- /var/www/html/synth/assets/brand/synth/apple-touch-icon.png
- /var/www/html/synth/assets/brand/synth/favicon.ico
- /var/www/html/synth/assets/brand/synth-third-faction-triptych.png

## Runner

- scripts/odroid/run_mvp_readonly_pipeline_once.sh

## Safety boundary

Allowed: public market reads, private broker balance read, local DB snapshot writes, paper advice observation writes, static HTML writes.

Global cockpit render stays read-only:

- render `/var/www/html/synth/index.html`
- render `/var/www/html/synth/about.html`
- render `/var/www/html/synth/entry-candidates.html`
- copy `/var/www/html/synth/assets/brand/synth/favicon.svg`
- copy `/var/www/html/synth/assets/brand/synth/favicon-16x16.png`
- copy `/var/www/html/synth/assets/brand/synth/favicon-32x32.png`
- copy `/var/www/html/synth/assets/brand/synth/apple-touch-icon.png`
- copy `/var/www/html/synth/assets/brand/synth/favicon.ico`
- copy `/var/www/html/synth/assets/brand/synth-third-faction-triptych.png`
- keep public brand-asset hrefs separate from filesystem output paths, e.g.
  `/synth/assets/brand/synth-third-faction-triptych.png` vs
  `/var/www/html/synth/assets/brand/synth-third-faction-triptych.png`
- no broker writes, no order submission, no executor path
- no separate manual favicon copy step; the normal global render flow deploys favicon assets automatically

Forbidden: broker writes, order submission, execution_planner activation, executor activation, decision_gate permission changes, live trading.

## Runtime switch

- SYNTH_MVP_RUN_MARKET_CHAIN=0 skips the heavier 4h market chain by default.
- Set SYNTH_MVP_RUN_MARKET_CHAIN=1 only when intentionally refreshing the full market chain.

## Access

Do not expose publicly without authentication. Preferred MVP access: Tailscale/VPN or LAN-only.

## Global page isolation rules

`/synth/index.html` and `/synth/about.html` are strictly account-agnostic.

- `run_synth_about_page_v1.py` performs no linked-profile or account discovery.
  It does not call `discover_active_linked_profiles` or query any account table.
- Global pages contain no `href="/synth/accounts/<profile>/..."` links.
- `cockpit_nav(account_profile=None)` renders Cockpit and About links only.
  It must not include Wallet, Profit Plan, or Open Orders Monitor.
- Account navigation (Wallet, Profit Plan, Open Orders Monitor) is only emitted
  by account-scoped dashboard runners with an explicit `account_profile` argument.
- No default profile may be hardcoded in `run_synth_about_page_v1.py` or
  `dashboard_style_v1.py`. `DEFAULT_NAV_ACCOUNT_PROFILE` must not exist.
- Login landing and redirect behavior is handled by the session auth layer and
  is profile/account-aware. It is unaffected by global page rendering.
  See `docs/deployment/profile_session_authorization_v1.md`.

## Limitations

- The About page is global and account-agnostic. Do not duplicate it under
  `/synth/accounts/<profile>/`.
- Profit Plan and Open Orders Monitor are account-scoped pages. Render them only
  through `scripts/odroid/run_account_wallet_dashboard_render_once.sh <profile>`.
- The global MVP cockpit must not render account-aware rotation preview, Profit
  Plan, or Open Orders Monitor pages itself.
- Legacy pages such as Paper Advice and Entry Candidates may appear only in a
  clearly labeled `Legacy / Archive` section, not in primary navigation.
- The large third-faction triptych is reserved for the About page and explicit
  brand surfaces, not normal operational dashboards.
- Better candidates are heuristic review aids, not allocation instructions.
- A+ Table 2 / breath rhythm is parked.
