-- Coalesce locator-profile outbox evidence invalidation once per transaction
-- while preserving the global evidence -> profiles -> dependent-row lock order.

ALTER TABLE memory_locator_profile_evidence_versions
    ADD COLUMN IF NOT EXISTS outbox_invalidation_xid XID8;

COMMENT ON COLUMN memory_locator_profile_evidence_versions.outbox_invalidation_xid IS
    'Transaction that most recently invalidated locator-profile outbox evidence';

CREATE OR REPLACE FUNCTION memory_locator_profile_guard_outbox_xid_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    evidence_owner NAME;
BEGIN
    SELECT pg_catalog.pg_get_userbyid(relation.relowner)
    INTO evidence_owner
    FROM pg_catalog.pg_class AS relation
    WHERE relation.oid = 'public.memory_locator_profile_evidence_versions'::regclass;

    -- Runtime roles can write other lifecycle columns on this table.  Only the
    -- object owner, acting through the SECURITY DEFINER invalidator below, may
    -- set the coalescing marker.  Object owners can already replace triggers.
    IF CURRENT_USER <> evidence_owner THEN
        RAISE EXCEPTION 'outbox invalidation xid is trigger-managed'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION memory_locator_profile_guard_outbox_xid_v1() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_locator_profile_outbox_xid_guard
    ON memory_locator_profile_evidence_versions;
CREATE TRIGGER trg_locator_profile_outbox_xid_guard
BEFORE UPDATE OF outbox_invalidation_xid
    ON memory_locator_profile_evidence_versions
FOR EACH ROW
WHEN (OLD.outbox_invalidation_xid IS DISTINCT FROM NEW.outbox_invalidation_xid)
EXECUTE FUNCTION memory_locator_profile_guard_outbox_xid_v1();

CREATE OR REPLACE FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    invalidated_rows INTEGER;
BEGIN
    -- This atomic conditional update is both the transaction-scope marker and
    -- the first lock in the global order.  A concurrent transaction waits for
    -- the singleton row, then rechecks its distinct xid and invalidates once.
    UPDATE public.memory_locator_profile_evidence_versions
    SET aggregate_version = aggregate_version + 1,
        changed_at = CURRENT_TIMESTAMP,
        outbox_invalidation_xid = pg_catalog.pg_current_xact_id()
    WHERE singleton = TRUE
      AND outbox_invalidation_xid IS DISTINCT FROM pg_catalog.pg_current_xact_id();

    GET DIAGNOSTICS invalidated_rows = ROW_COUNT;
    IF invalidated_rows > 0 THEN
        UPDATE public.memory_locator_profiles
        SET reconciliation_drifted = CASE WHEN state = 'active' THEN TRUE
                                          ELSE reconciliation_drifted END,
            activation_lease_expires_at = CASE
                WHEN activation_lease_issued_at IS NULL THEN activation_lease_expires_at
                ELSE GREATEST(
                    activation_lease_issued_at + INTERVAL '1 microsecond',
                    CURRENT_TIMESTAMP
                )
            END
        WHERE state IN ('building', 'active', 'retained')
          AND activation_lease_id IS NOT NULL;
    END IF;

    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2() FROM PUBLIC;

-- Drop every historical outbox invalidator before installing the row triggers.
DROP TRIGGER IF EXISTS trg_locator_profile_outbox_evidence_version ON memory_outbox;
DROP TRIGGER IF EXISTS trg_00_locator_profile_outbox_evidence_insert ON memory_outbox;
DROP TRIGGER IF EXISTS trg_00_locator_profile_outbox_evidence_update ON memory_outbox;
DROP TRIGGER IF EXISTS trg_00_locator_profile_outbox_evidence_delete ON memory_outbox;

-- The trg_00_locator names sort before strict-v4 dependent-row fence triggers.
CREATE TRIGGER trg_00_locator_profile_outbox_evidence_insert
BEFORE INSERT ON memory_outbox
FOR EACH ROW
WHEN (NEW.event_type IN (
    'vector.upsert_locator_profile', 'vector.delete_locator_profile'
))
EXECUTE FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2();

CREATE TRIGGER trg_00_locator_profile_outbox_evidence_update
BEFORE UPDATE ON memory_outbox
FOR EACH ROW
WHEN (
    OLD.event_type IN (
        'vector.upsert_locator_profile', 'vector.delete_locator_profile'
    ) OR NEW.event_type IN (
        'vector.upsert_locator_profile', 'vector.delete_locator_profile'
    )
)
EXECUTE FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2();

CREATE TRIGGER trg_00_locator_profile_outbox_evidence_delete
BEFORE DELETE ON memory_outbox
FOR EACH ROW
WHEN (OLD.event_type IN (
    'vector.upsert_locator_profile', 'vector.delete_locator_profile'
))
EXECUTE FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2();
