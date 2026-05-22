-- Migration: fix_assignment_log_actions
-- Fix the device_assignment_log action CHECK constraint to include all valid actions.
-- The original constraint was missing: extract_face, extract_card, sync_tenants
-- which caused DB errors whenever those actions were logged.

ALTER TABLE device_assignment_log
    DROP CONSTRAINT IF EXISTS device_assignment_log_action_check;

ALTER TABLE device_assignment_log
    ADD CONSTRAINT device_assignment_log_action_check
    CHECK (action IN (
        'assign',
        'revoke',
        'update',
        'enroll',
        'unenroll',
        'capture',
        'extract_fingerprint',
        'enroll_site',
        'extract_face',
        'extract_card',
        'sync_tenants'
    ));
