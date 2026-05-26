## Live-Like Shadow Heartbeat V1

`run_live_like_shadow_heartbeat_once.sh` is an Odroid-oriented one-shot wrapper that runs the live-like shadow chain and renders the static shadow dashboard plus the shadow heartbeat history dashboard.

This lane is ops/read-only only.

Safety boundary:

- no DB writes
- no broker private calls
- no broker writes
- no order submission
- no executor calls
- no live permission
- no decision_gate changes
- no execution_planner runtime changes
- `executor=none`
- `no_order_submitted=true`

The runner does not enable any timer automatically.

Dashboard paths:

```text
/var/www/html/synth/live-like-shadow-chain.html
/var/www/html/synth/live-like-shadow-history.html
```

The history page measures state stability only across recent shadow heartbeat runs.

It is not performance validation.

It is not executor enablement.

## One-shot command

```bash
cd /home/theone/projects/synth-v2
bash scripts/odroid/run_live_like_shadow_heartbeat_once.sh
```

The wrapper runs:

```bash
python -m src.research.run_live_like_shadow_chain_v1 --market NEAR-EUR --symbol NEAR --write-files
python -m src.reporting.run_live_like_shadow_chain_static_dashboard_v1 \
  --chain-run-dir "$LATEST" \
  --output-html /var/www/html/synth/live-like-shadow-chain.html \
  --output table
python -m src.reporting.run_live_like_shadow_heartbeat_history_v1 \
  --chain-root data/research/live_like_shadow_chain_v1 \
  --max-runs 100 \
  --output-html /var/www/html/synth/live-like-shadow-history.html \
  --output table
```

## Systemd user timer install

Copy or symlink the unit files into the user systemd directory, then reload and enable manually:

```bash
mkdir -p ~/.config/systemd/user
cp /home/theone/projects/synth-v2/scripts/odroid/systemd/synth-live-like-shadow-heartbeat.service ~/.config/systemd/user/
cp /home/theone/projects/synth-v2/scripts/odroid/systemd/synth-live-like-shadow-heartbeat.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now synth-live-like-shadow-heartbeat.timer
```

## Status and journal commands

```bash
systemctl --user status synth-live-like-shadow-heartbeat.service
systemctl --user status synth-live-like-shadow-heartbeat.timer
journalctl --user -u synth-live-like-shadow-heartbeat.service -n 100 --no-pager
journalctl --user -u synth-live-like-shadow-heartbeat.timer -n 50 --no-pager
```

## Disable commands

```bash
systemctl --user disable --now synth-live-like-shadow-heartbeat.timer
systemctl --user stop synth-live-like-shadow-heartbeat.service
```

## Expected terminal safety markers

```text
broker_writes=0
order_submission=0
executor=none
no_order_submitted=true
```

This heartbeat is shadow preview only. It is not paper trading, not live trading, and does not create an executor path.
