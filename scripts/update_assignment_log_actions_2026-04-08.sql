-- Migration: extend device_assignment_log action CHECK constraint
-- Adds: capture, extract_fingerprint, enroll_site
-- Run once against the live database.

ALTER TABLE device_assignment_log
    DROP CONSTRAINT device_assignment_log_action_check;

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
        'enroll_site'
    ));
