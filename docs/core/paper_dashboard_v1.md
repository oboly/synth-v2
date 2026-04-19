# Paper Dashboard v1

## Doel

`run_paper_dashboard_v1.py` geeft een compacte momentopname van de paper engine.

Het is bedoeld voor live meekijken tijdens paper runtime.

---

## Wat het toont

### Summary

- `eligible`
- `active_plans`
- `open_positions`
- `reserved`
- `deployed`
- `available`
- `realized_pnl_total`
- `last_event`
- `last_symbol`

### Detailsecties

- latest selection top
- execution plans
- open positions
- closed positions
- latest execution events

---

## Waarom dit nuttig is

De dashboard-runner maakt het mogelijk om snel te zien:

- wil de markt iets?
- probeert de engine iets?
- zit er al kapitaal vast?
- staat er een positie open?
- wat was de laatste actie?

---

## Gebruik

Voorbeeld:

    python -m src.reporting.run_paper_dashboard_v1 \
      --account-id 1 \
      --sleeve-code SWING_STRUCTURAL \
      --venue bitvavo

---

## v1 scope

Geïmplementeerd:

- terminal dashboard
- fixed decimal formatting
- closed positions zichtbaar
- realized pnl totaal zichtbaar

Nog niet gedaan:

- grafische UI
- websockets
- browser dashboard
- chart overlays
