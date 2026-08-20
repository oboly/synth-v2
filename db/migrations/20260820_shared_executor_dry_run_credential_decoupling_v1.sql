-- Issue #461: DRY_RUN shared-executor handoffs require no broker credential authority.
-- Additive production migration. The original shared-executor migration is already applied.
--
-- Safety contract:
--   DRY_RUN -> executor_credential_binding_id MUST be NULL
--   PAPER   -> executor_credential_binding_id MUST be non-NULL
--   LIVE    -> executor_credential_binding_id MUST be non-NULL
--
-- This migration creates no credential, binding, LIVE authority, kill-switch state,
-- broker permission, order, or runtime activation.

ALTER TABLE executor_execution_handoff
    MODIFY COLUMN executor_credential_binding_id BIGINT UNSIGNED NULL;

ALTER TABLE executor_execution_handoff
    ADD CONSTRAINT chk_eeh_credential_binding_by_mode_v1
        CHECK (
            (executor_mode = 'DRY_RUN' AND executor_credential_binding_id IS NULL)
            OR
            (executor_mode IN ('PAPER', 'LIVE') AND executor_credential_binding_id IS NOT NULL)
        );
