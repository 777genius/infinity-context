-- Durable exact-result idempotency for strict-admin Retrieval V2 profile operations.
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE memory_locator_profile_operator_receipts (
    idempotency_key VARCHAR(120) PRIMARY KEY,
    request_fingerprint CHAR(64) NOT NULL,
    operation VARCHAR(24) NOT NULL,
    profile_id VARCHAR(120) NOT NULL,
    result_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_locator_profile_operator_receipt_fingerprint CHECK (
        request_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_locator_profile_operator_receipt_operation CHECK (
        operation IN ('create', 'rebuild', 'attest', 'activate')
    ),
    CONSTRAINT ck_locator_profile_operator_receipt_result_object CHECK (
        jsonb_typeof(result_json) = 'object'
    )
);

CREATE FUNCTION memory_locator_profile_operator_receipt_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'retrieval profile operator receipts are append-only';
END;
$$;

CREATE TRIGGER trg_memory_locator_profile_operator_receipt_append_only
BEFORE UPDATE OR DELETE ON memory_locator_profile_operator_receipts
FOR EACH ROW EXECUTE FUNCTION memory_locator_profile_operator_receipt_append_only();
