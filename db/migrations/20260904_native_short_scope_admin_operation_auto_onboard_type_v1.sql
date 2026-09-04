-- Migration: native_short_scope_admin_operation_auto_onboard_type_v1
-- Boundary: Native SHORT market-data administration ledger schema only.
-- Idempotent: safe to re-run on MariaDB 10.5.2+ (this environment:
--             11.8.6-MariaDB), matching the explicitly labeled idempotent
--             CHECK-constraint-replacement convention already established by
--             20260609_trading_account_credential_add_valid_private_read.sql,
--             20260721_account_credential_binding_contract_v1.sql, and
--             20260828_trading_account_account_mode_live_readonly_v1.sql
--             (each: `DROP CONSTRAINT IF EXISTS` followed by `ADD CONSTRAINT`
--             with the same name). DROP CONSTRAINT IF EXISTS never fails
--             whether or not the constraint is currently present, and ADD
--             CONSTRAINT then (re)creates the identical definition, so the end
--             state after N applications equals the end state after 1
--             application. This corrects an earlier draft of this migration
--             that used plain `DROP CONSTRAINT` (no IF EXISTS) and an
--             inaccurate claim that this is a fail-loud, single-application
--             ALTER matching 20260829's plain DROP CONSTRAINT and the
--             ADD COLUMN / DROP INDEX statements in 20260718: those DO fail
--             loudly on reapplication because they add/drop something that
--             does not symmetrically restore itself, which does not apply to
--             a same-named DROP-then-ADD CONSTRAINT pair.
-- Incident: synth-chain-4h AUTO_ONBOARD_SCOPES fails MariaDB 4025 on
--   chk_native_short_scope_admin_operation_v1_type because the canonical
--   operation_type enum (native_short_scope_administration_v1.py) already
--   defines and executes AUTO_ONBOARD_SCOPE (Issue #539), but the original
--   20260718_native_short_scope_administration_v1.sql CHECK constraint still
--   only permits ADOPT_LEGACY_SCOPE / PROMOTE_SCOPE / REMOVE_SCOPE.
-- Scope of this fix:
--   Audited every CHECK constraint on native_short_scope_admin_operation_v1
--   against the exact row AUTO_ONBOARD_SCOPE persists
--   (src/market_data/native_short_auto_onboarding_v1.py ->
--   execute_scope_administration). actor_type=SERVICE_PRINCIPAL and
--   trigger_type=AUTOMATION are already permitted values, decide_administration
--   routes AUTO_ONBOARD_SCOPE through the same _decide_promote result codes as
--   PROMOTE_SCOPE (already permitted values), and every other persisted field
--   (uuid, scope, actor/trigger provenance shape, required text, repository
--   sha, metadata digest, terminal shape, timestamps, generation) is
--   independent of operation_type. chk_native_short_scope_admin_operation_v1_type
--   is the only stale constraint; no other constraint on this table requires
--   change for this operation type.
-- Forward-only: the historical 20260718 migration is not edited; this is a
-- pure follow-up ALTER.
--
-- Safety:
--   broker_private_calls=0
--   broker_writes=0
--   order_submission=0
--   live_orders=0
--   decision_gate=none
--   execution_planner=none
--   executor=none

ALTER TABLE native_short_scope_admin_operation_v1
    DROP CONSTRAINT IF EXISTS chk_native_short_scope_admin_operation_v1_type;

ALTER TABLE native_short_scope_admin_operation_v1
    ADD CONSTRAINT chk_native_short_scope_admin_operation_v1_type
        CHECK (operation_type IN (
            'ADOPT_LEGACY_SCOPE',
            'PROMOTE_SCOPE',
            'AUTO_ONBOARD_SCOPE',
            'REMOVE_SCOPE'
        ));
