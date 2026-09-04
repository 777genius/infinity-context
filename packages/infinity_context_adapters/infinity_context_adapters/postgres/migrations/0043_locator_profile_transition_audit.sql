-- Atomic append-only evidence for every Retrieval V2 active-profile transition.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE memory_locator_profile_transition_audit (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id VARCHAR(120) NOT NULL REFERENCES memory_locator_profiles(profile_id),
    previous_active_profile_id VARCHAR(120),
    lease_id VARCHAR(120) NOT NULL UNIQUE,
    evidence_digest CHAR(64) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_profile_transition_audit_digest CHECK (
        evidence_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_locator_profile_transition_audit_distinct CHECK (
        previous_active_profile_id IS NULL OR previous_active_profile_id <> profile_id
    )
);

CREATE FUNCTION memory_locator_profile_transition_audit_immutable_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'retrieval profile transition audit is append-only';
END;
$$;

CREATE TRIGGER trg_memory_locator_profile_transition_audit_immutable_v2
BEFORE UPDATE OR DELETE ON memory_locator_profile_transition_audit
FOR EACH ROW EXECUTE FUNCTION memory_locator_profile_transition_audit_immutable_v2();

REVOKE UPDATE, DELETE, TRUNCATE ON memory_locator_profile_transition_audit FROM PUBLIC;
