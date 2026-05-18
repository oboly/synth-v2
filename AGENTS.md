# Repository Guidelines

## Project Structure & Module Organization

Synth v2 is a Python trading-system repository with strict layer separation. Core implementation lives under `src/`, grouped by responsibility: `selection/`, `advice/`, `decision_gate/`, `execution_planner/`, `executor/`, `etl/`, `features/`, `signal_engine/`, `trade_setup_filter/`, `reporting/`, and `research/`. Apps and lightweight UIs live in `apps/`. Operational helpers are in `scripts/`, including Odroid runner scripts. Documentation is canonical in `docs/`; TODO coordination is under `docs/todo/`. Database assets are in `db/`, with schema snapshots under `docs/database/`. Research outputs belong under `data/research/`. Tests currently live in `tests/`.

## Build, Test, and Development Commands

Create or activate a virtualenv, then install dependencies:

    python -m pip install -r requirements.txt

Common checks:

    python -m py_compile path/to/file.py
    python -m pytest tests  # when pytest is available
    git diff --check

Use module execution for runners, for example:

    python -m src.reporting.run_paper_advice_static_dashboard_v1 --help

The Makefile currently provides `make schema-snapshot`, which dumps DB schema metadata using `.env` database settings.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, type hints where practical, and clear module-level constants for defaults. Prefer deterministic, explicit behavior over hidden side effects. File names use lowercase snake_case, usually with version suffixes for research and runner scripts, e.g. `run_trade_setup_rank_cap_correction_preview_v1.py`. Keep DB reads/writes and external API calls in appropriate repository, ETL, or runner layers; renderers should render assembled view models.

## Testing Guidelines

Add focused tests under `tests/` when behavior is reusable or safety-critical. For narrow runner changes, at minimum run `py_compile` on changed Python files and `git diff --check`. If a command reads the DB or external services, document the exact manual command and keep safety markers explicit.

## Commit & Pull Request Guidelines

Recent commits use concise imperative messages, for example `Add rank cap correction preview` or `Clarify paper advice lifecycle freshness header`. Commit only intended files and leave unrelated local data untouched. PRs should state scope, safety boundaries, tests run, manual commands used, and any runtime or DB impact. Include screenshots or generated HTML paths for UI/dashboard changes.

## Security & Architecture Boundaries

Do not commit secrets or `.env`. Respect layer boundaries from `README.md`: selection is account-agnostic, decision gate is account-aware, execution planner produces intent, and executor/order code handles orders. Never bypass decision/execution boundaries from research, reporting, dashboard, or preview code. Research and dashboards must not create orders, reserve capital, or enable live/paper execution paths unless explicitly promoted through the proper architecture.
