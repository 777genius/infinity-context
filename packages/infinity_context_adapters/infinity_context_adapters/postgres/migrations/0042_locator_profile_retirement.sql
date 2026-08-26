-- Durable, restart-safe retirement cleanup state for Retrieval V2 profiles.
-- Published profile migrations remain immutable; completed cleanup keeps the
-- canonical profile identity as a compact audit tombstone.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE memory_locator_profile_cleanups (
    profile_id VARCHAR(120) PRIMARY KEY
        REFERENCES memory_locator_profiles(profile_id),
    phase VARCHAR(32) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error_code VARCHAR(120),
    requested_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_profile_cleanup_phase CHECK (
        phase IN (
            'requested', 'waiting_for_jobs', 'collection_deleted',
            'postgres_cleaned', 'complete'
        )
    ),
    CONSTRAINT ck_locator_profile_cleanup_attempt_count CHECK (attempt_count >= 0)
);

CREATE INDEX ix_locator_profile_cleanups_pending
    ON memory_locator_profile_cleanups (phase, updated_at)
    WHERE phase <> 'complete';
