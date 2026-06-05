# Synth MVP Read-only Cockpit V1

## Goal

Render a read-only online cockpit for paper advice, A+ Table 1 DB context, fresh account positions, and position rotation preview.

## Outputs

- /var/www/html/synth/index.html
- /var/www/html/synth/paper-advice.html
- /var/www/html/synth/rotation-preview.html
- /var/www/html/synth/open-orders-monitor.html
- /var/www/html/synth/open-orders-monitor.json
- /var/www/html/synth/profit-plan.html
- /var/www/html/synth/profit-plan.json
- /var/www/html/synth/about.html
- /var/www/html/synth/assets/brand/synth-third-faction-triptych.png

## Runner

- scripts/odroid/run_mvp_readonly_pipeline_once.sh

## Safety boundary

Allowed: public market reads, private broker balance read, local DB snapshot writes, paper advice observation writes, static HTML writes.

Profit Plan integration stays read-only:

- render `/var/www/html/synth/open-orders-monitor.html`
- render `/var/www/html/synth/open-orders-monitor.json`
- refresh canonical `fibo_target_map_v1` before Profit Plan render
- render `/var/www/html/synth/profit-plan.html`
- render `/var/www/html/synth/profit-plan.json`
- render `/var/www/html/synth/about.html`
- copy `/var/www/html/synth/assets/brand/synth-third-faction-triptych.png`
- keep public browser hrefs separate from filesystem output paths, e.g.
  `/synth/open-orders-monitor.html` vs `/var/www/html/synth/open-orders-monitor.html`
- keep public brand-asset hrefs separate from filesystem output paths, e.g.
  `/synth/assets/brand/synth-third-faction-triptych.png` vs
  `/var/www/html/synth/assets/brand/synth-third-faction-triptych.png`
- no broker writes, no order submission, no executor path

Forbidden: broker writes, order submission, execution_planner activation, executor activation, decision_gate permission changes, live trading.

## Runtime switch

- SYNTH_MVP_RUN_MARKET_CHAIN=0 skips the heavier 4h market chain by default.
- Set SYNTH_MVP_RUN_MARKET_CHAIN=1 only when intentionally refreshing the full market chain.

## Access

Do not expose publicly without authentication. Preferred MVP access: Tailscale/VPN or LAN-only.

## Limitations

- The About page is global and account-agnostic. Do not duplicate it under
  `/synth/accounts/<profile>/`.
- The large third-faction triptych is reserved for the About page and explicit
  brand surfaces, not normal operational dashboards.
- Better candidates are heuristic review aids, not allocation instructions.
- Rotation preview is not an executor and does not create orders.
- A+ Table 2 / breath rhythm is parked.
