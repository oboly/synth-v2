# Paper Advice Static Dashboard v1

## Purpose

paper_advice_static_dashboard_v1 renders the latest paper_advice_observation snapshot to a static HTML dashboard.

This is a reporting surface only.

## Boundaries

This dashboard:

- reads market/account-agnostic paper advice observations
- renders static HTML
- does not call broker APIs
- does not write orders
- does not invoke decision_gate
- does not invoke execution_planner
- does not invoke executor

Safety expectation:

    broker_calls=0
    broker_writes=0
    order_submission=0
    live_orders=0

## Runtime

Manual render example:

    export SYNTH_EXECUTION_MODE=paper
    export SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED
    export SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED

    python -m src.reporting.run_paper_advice_static_dashboard_v1 \
      --venue bitvavo \
      --interval 4h \
      --output-html /var/www/html/synth/paper-advice.html \
      --output table

## 4h chain integration

scripts/run_chain_4h.sh regenerates the dashboard only when this environment variable is set:

    SYNTH_PAPER_ADVICE_DASHBOARD_HTML=/var/www/html/synth/paper-advice.html

If the variable is unset, the 4h chain runs normally without dashboard output.

## Deployment

Recommended private/LAN path:

    /var/www/html/synth/paper-advice.html

Recommended browser URL:

    http://<odroid-ip>/synth/paper-advice.html

Keep the page private/LAN-only unless authentication is added.
