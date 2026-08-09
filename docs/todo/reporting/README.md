# Reporting TODOs

## GitHub Issue migration

Status: migrated

This file is navigation only. Executable child-file scope is owned by GitHub Issues as listed below.

Unmigrated executable scope:
- none

## Scope

Read-only dashboards, web views, inspection surfaces, evidence presentation, sorting, filtering, labels, and account-overlay contracts.

## Boundary

Reporting consumes accepted persisted or canonical state. It must not recompute market models, call brokers, grant account permission, create execution intent, handle orders, or submit orders.

## Index rule

This file is navigation only. This board is frozen; current status, priority, and execution order are owned by GitHub Issues (`docs/development/github_issues_workflow.md`).

## Canonical files

- `profit_plan_opportunity_presentation_v1.md`
- `ffg_rotation_radar_presentation_v1.md`
- `ma_volume_stoplight_dashboard_v1.md`

Other reporting-scoped TODOs (`sector_rotation_dashboard_v1.md`,
`ui_webview.md`, `signal_matrix_dashboard.md`,
`multi_horizon_fib_dashboard_backlog.md`, `position_rotation_preview.md`)
remain at their top-level `docs/todo/` paths. Status/priority for all of them
is owned by GitHub Issues (see `docs/todo/README.md`'s frozen lane index);
this board is frozen and no further physical file migration into this
folder is planned.
