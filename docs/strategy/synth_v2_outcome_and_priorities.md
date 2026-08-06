# Synth v2 — Outcome and Priorities

This is a product-direction anchor, not a new governance framework. It exists
to keep the project aligned with its actual end goal and to stop technically
useful work from quietly becoming the goal itself. For tactical execution
order at any given time, see GitHub Issues and
`docs/development/github_issues_workflow.md`. For layer contracts, see
`docs/architecture/module_architecture.md` and
`docs/architecture/pipeline_contracts.md`.

## North star

Synth v2 manages Joost's crypto portfolio largely autonomously by combining:

- market-only selection;
- account-aware permission and portfolio decisions;
- explicit execution planning;
- controlled order execution.

The practical goal is to improve risk-adjusted portfolio decisions while
reducing daily manual work.

The end state is not merely a dashboard or a signal generator. Synth must be
able to decide when buying, selling, holding, or rotating is appropriate,
translate that decision into concrete limit-order plans, and execute those
plans through the designated executor layer.

## Core product capabilities

### 1. Research, backtest, and promotion

Joost can develop and test new algorithms or strategy variants in an isolated
backtest/replay lane. New algorithms must first be evaluated against explicit
acceptance criteria; only deliberately promoted versions may influence the
live lane. Promotion must be explicit and reproducible, but pragmatic for a
personal single-user system — this is not an enterprise approval workflow.

### 2. Modular architecture

Synth v2 is modular so that algorithms, decision rules, planning logic, and
execution behavior can be extended or replaced independently. Canonical
responsibility split:

- **`selection_engine`** — market-only; account-agnostic; produces market
  selection, rankings, signals, and opportunity context.
- **`decision_gate`** — account-aware permission layer; evaluates holdings,
  budget, exposure, risk, cooldowns, and account rules; decides whether a
  proposed action is permitted for a specific account.
- **`execution_planner`** — converts an allowed action into execution
  intent; defines buy/sell side, size, limit prices, order legs, timing, and
  conditions; does not place orders.
- **`executor` / execution agents** — place, amend, cancel, and reconcile
  orders; do not invent strategy decisions.

No layer may bypass another. Full contracts live in
`docs/architecture/module_architecture.md` and
`docs/architecture/pipeline_contracts.md`; this document does not duplicate
them.

### 3. Autonomous portfolio decisions

Synth should ultimately determine what to buy, sell, hold, or rotate, how
much, at which limit prices, and under which conditions orders remain valid,
change, or cancel. This autonomy is distributed across the canonical layers
above — it is not one monolithic decision function.

### 4. Live operator experience

The primary operator experience should provide: current portfolio state,
market opportunities, an actionable Profit Plan, planned buy and sell limits,
reasons and confidence, current order state, and a clear distinction between
planned, permitted, submitted, filled, cancelled, and expired actions.

## Current primary outcome

Deliver a reliable live dashboard and Profit Plan for Joost's portfolio that
shows what to hold, buy, sell, or rotate using current market data and
reproducible strategy output. This should progress toward autonomous order
planning and execution, not stop at visual reporting.

## Priority order

1. Reliable market data and runtime chains
2. Correct market selection and strategy output
3. Backtest/replay lane and explicit live promotion
4. Actionable Profit Plan and live dashboard
5. Account-aware decision gate
6. Execution planning with concrete buy/sell limit orders
7. Controlled executor integration
8. Broader automation and multi-account expansion

Temporary infrastructure work is justified only when it unlocks or protects
one of these outcomes.

## Decision rule for new work

A task should materially improve at least one of: signal or strategy
quality; backtest confidence; safe promotion to live; portfolio decision
quality; dashboard/action clarity; reliability of an active production
pipeline; execution quality; reduction of manual work.

Otherwise: place it in `docs/todo/`, defer it, or remove it.

## Explicit non-goals

Synth v2 is not currently trying to become:

- an enterprise compliance platform;
- a generic multi-tenant trading SaaS;
- an infrastructure-security research project;
- a maximally abstract framework;
- a collection of dashboards without execution capability;
- an architecture-perfection exercise that delays usable trading outcomes.

## Design principles

- test before live;
- explicit promotion;
- market logic remains account-agnostic;
- account permission remains in `decision_gate`;
- execution intent remains in `execution_planner`;
- order handling remains in executor/agents;
- modular and replaceable components;
- deterministic and observable behavior;
- robustness over cleverness;
- personal-system pragmatism over enterprise overbuild.
