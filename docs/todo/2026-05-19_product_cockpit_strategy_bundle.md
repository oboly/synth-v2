# 2026-05-19 Product, Cockpit, Strategy TODO Bundle

Status: TODO bundle  
Priority: mixed  
Scope: dashboard semantics, strategy validation, user-ready website, multi-user cockpit, ops

## Current priority

Focus first on making Synth work for Joost.

Immediate priority order:

1. Dashboard semantics must be clear and correct.
2. Existing-position rotation preview must not imply automatic sell/buy.
3. Buy/setup candidates need their own view separate from rotation preview.
4. Strategy research/backtests need to support visual review.
5. Strategy buckets can be defined after more testing.
6. User-ready website and multi-user flows come after personal cockpit correctness.
7. Live execution remains later.

## P0/P1 — Dashboard semantics for Joost

Current issue:

- `EXIT_CANDIDATE` and `REDUCE_CANDIDATE` are too easy to misread as direct sell signals.
- `RISK_NEAR` on a DOWN-leg can mean the old map is close to invalidation/reclaim, not simply bearish exit.
- `review_refs` scores such as `NEAR:14.45, INJ:13.44, HYPE:12.60` are relative market-candidate quality references, not expected return and not direct rotation instructions.

Required clarification:

- Add dashboard help text explaining:
  - `review_refs` means broad comparison references.
  - `destinations` means stricter filtered rotation candidates.
  - `score` is a heuristic pressure/comparison score.
  - no label is an order instruction.
- Rename or clarify labels:
  - EXIT_CANDIDATE_TARGET_REACHED
  - EXIT_CANDIDATE_RISK_NEAR
  - EXIT_CANDIDATE_NO_EDGE
  - REDUCE_REVIEW_NO_EDGE
  - MAP_INVALIDATION_NEAR
  - RECLAIM_NEAR
  - RECLAIM_CONFIRMED
  - HARVEST_REVIEW
  - PARTIAL_TP_REVIEW
  - HOLD_REVIEW_RECLAIM_PENDING

Boundary:

- Rotation preview is account-aware review.
- It is not an order engine.
- It does not bypass decision_gate.
- It does not call execution_planner or executor.

## P1 — Entry candidate dashboard

Goal:

Add a clear buy/setup candidate view separate from position rotation preview.

Why:

- Rotation preview answers: what should be reviewed for existing positions?
- Entry candidate dashboard answers: which market-only setups are becoming actionable?

Candidate groups:

- PAPER_BUY_READY
- WATCH_FOR_CONFIRMATION
- RECLAIM_NEAR
- MAP_INVALIDATION_RECLAIM
- BLOCKED_NO_NEW_BUY
- CONTEXT_ONLY
- INSUFFICIENT_SAMPLE

Initial PAPER_BUY_READY criteria:

- setup_filter_state = PASS
- allowed_now = YES or policy_decision allows current horizon
- advice_action not in DO_NOT_ADD, AVOID_NO_NEW_BUY, CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP
- A+ not APLUS_AVOID
- target_state not TARGET_REACHED
- risk_state not RISK_NEAR unless explicitly classified as RECLAIM_NEAR
- market damage not hard-risk

Possible output:

- extend paper-advice.html with an Entry Candidates section
- or create /synth/entry-candidates.html

Boundary:

- market-only
- account-agnostic
- no account sizing
- no position data
- no broker calls
- no decision_gate
- no execution

## P1 — Volume-flow classification

Goal:

Add recent volume/candle-flow interpretation to rotation preview.

Reason:

Target/risk/zone logic exists, but high volume still needs interpretation:

- sell pressure
- buy pressure
- absorption
- reclaim
- distribution
- neutral

Inputs:

- open_price
- high_price
- low_price
- close_price
- volume_base
- volume_quote_eur
- trade_count when available

Candidate labels:

- VOLUME_SELL_PRESSURE
- VOLUME_BUY_PRESSURE
- VOLUME_ABSORPTION
- VOLUME_RECLAIM
- VOLUME_DISTRIBUTION
- VOLUME_NEUTRAL
- VOLUME_LOW_CONFIDENCE

Initial rules:

- High volume plus close near candle low means sell pressure or distribution.
- High volume plus close near candle high means buy pressure or reclaim.
- High volume plus long lower wick plus recovery close means possible absorption.
- High volume near target or rejection zone means harvest or distribution risk.
- Low volume bounce means weak reclaim.
- High volume break above invalidation on DOWN map means map invalidation or reclaim pressure.

Boundary:

- rotation preview context only
- no order logic
- no decision_gate changes
- no execution changes
- no broker writes/orders

## P1 — Strategy visual review flow

Goal:

Use visual backtests to review whether Synth labels behave correctly.

Current useful state:

- pipeline visual backtest runner exists
- events include setup pass/fail, enter sim, exit target, exit risk, map invalidated, block market damage
- output is research-only HTML/JSONL

Next improvements:

- expose selected visual backtests through cockpit later
- add quick links from dashboard rows to symbol visual review
- run NEAR/HYPE/LDO/INJ examples
- compare chart behavior with dashboard labels
- use visual review before trusting numerical batch results

Boundary:

- research-only
- no broker calls
- no broker writes
- no order submission
- no operational execution_zone_context historical backfills

## P1/P2 — Strategy bucket configuration

Goal:

Allow users to activate validated Synth strategy buckets with account-specific risk parameters.

Product principle:

- Users should not edit core strategy logic.
- Synth validates strategy buckets.
- Users enable/disable buckets.
- Users configure risk/allocation limits.

Candidate buckets:

- SHORT_TERM_ROTATION
- MEDIUM_SWING
- LONG_TERM_CYCLE
- BREATH_CURVE_RESEARCH
- MOONSHOT_ASYMMETRY
- DEFENSIVE_HARVEST

User-configurable fields:

- trading_account_id
- strategy_bucket_id
- is_enabled
- risk_profile
- max_position_amount_eur
- max_bucket_amount_eur
- max_asset_exposure_pct
- max_open_positions
- allow_new_entries
- allow_reduce_reviews
- created_ts_utc
- updated_ts_utc

Architecture:

- market-only strategy candidates
- validated strategy bucket
- account-specific risk config
- decision_gate resolves permission/allocation/conflicts
- execution_planner only after permission
- executor later

Rules:

- selection_engine remains market-only and account-agnostic.
- strategy validation remains research/backtest.
- user settings belong in decision_gate / portfolio layer.
- execution remains disabled until explicitly implemented.

## P2 — Backtest dashboard integration

Goal:

Expose backtest and visual review outputs through cockpit after research runners stabilize.

Possible pages:

- /synth/research/backtests.html
- /synth/research/visual-backtest/<run_id>.html
- /synth/research/forward-return.html

Features:

- choose symbol
- choose interval
- choose start/end date
- view generated chart with candles, zones, setup events, simulated entries/exits, blocks
- view summary counts
- view forward-return statistics later

Boundary:

- research-only
- no broker calls
- no broker writes
- no order submission
- no operational execution_zone_context historical backfills

## P2 — Dynamic multi-user cockpit

Goal:

Replace static-only single-user cockpit access with dynamic read-only cockpit backend.

Architecture:

- nginx HTTPS
- app auth or temporary Basic Auth
- cockpit app receives authenticated username
- cockpit app resolves allowed trading_account_id values
- cockpit app renders account-specific dashboards

Keep one Linux/runtime user:

- Linux user: theone
- systemd service: synth-cockpit-web.service
- web users: joost, hugo, later more

Do not create a Linux/systemd user per cockpit user.

Minimal data model:

- cockpit_user
- cockpit_account_access
- cockpit_share
- later cockpit_wallet_link

Shared market-only:

- candles
- features
- selection_engine output
- paper_advice
- A+ context
- Breath Curve research
- strategy/backtest results

User/account-specific:

- positions
- wallet/account snapshot
- rotation preview
- portfolio exposure
- risk per account
- future decision_gate result
- future execution permission

Meekijk mode:

- VIEW_ONLY
- MASK_VALUES
- FULL_VIEW

Rules:

- viewer cannot edit API credentials
- viewer cannot create orders
- viewer cannot change account settings
- all sharing explicit and revocable

## P2 — User-ready website

Goal:

Turn private cockpit into user-ready website.

Pages:

- /
- /register
- /login
- /app
- /app/accounts
- /app/accounts/bitvavo/connect

Security baseline:

- replace nginx Basic Auth for app users with app auth
- keep nginx Basic Auth only as temporary/admin fallback
- Argon2id password hashing
- minimum 14 character passwords
- block common/leaked passwords
- rate-limit login/register
- proof-of-human check, such as hCaptcha or Turnstile
- email verification
- secure HttpOnly cookies
- Secure cookie flag
- SameSite Lax or Strict
- session expiry
- audit log

2FA:

- required before exchange account linking
- TOTP first
- recovery codes
- WebAuthn/passkeys later

Bitvavo account linking:

- read-only API keys only
- no broker write permission
- no order permission
- no withdrawal permission
- credentials encrypted at rest
- never display secret after save
- test connection with private read only
- create trading_account row
- map cockpit_user to trading_account_id
- no seed phrases
- no wallet private keys
- no withdrawal keys

## P2 — Systemd service ownership cleanup

Goal:

Clarify when to use user units vs system units.

Current known mix:

- systemctl --user for synth-mvp-readonly-cockpit
- sudo systemctl for synth-paper-advice-lifecycle-refresh and synth-4h-market-chain

Recommendation to evaluate:

- all long-running/timer runtime jobs as system units with User=theone
- nginx remains normal system service

Boundary:

- ops cleanup only
- no strategy logic changes
- no DB schema changes
- no broker calls
- no execution changes

## P2 — Public HTTPS ops

Current state:

- nginx over HTTPS
- Basic Auth
- /var/www/html/synth
- public URL: https://gurk11.duckdns.org/synth/

Known issue:

- Let's Encrypt renewal dry-run showed intermittent DuckDNS secondary validation DNS failures.

Maintenance checks:

- sudo certbot renew --dry-run
- dig @1.1.1.1 A gurk11.duckdns.org +short
- dig @8.8.8.8 A gurk11.duckdns.org +short
- curl -i http://gurk11.duckdns.org/.well-known/acme-challenge/ping

Future hardening:

- real app authentication
- 2FA
- per-user account isolation
- optional rate limiting
- access log review
- fail2ban or nginx rate limiting
- remove Basic Auth once app auth is implemented
