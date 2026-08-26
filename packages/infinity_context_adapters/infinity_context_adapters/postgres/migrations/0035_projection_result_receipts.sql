CREATE TABLE IF NOT EXISTS memory_cleanup_v3_context_authorities (
    run_id_sha256 CHAR(64) NOT NULL
        REFERENCES memory_comparison_benchmark_runs(run_id_sha256),
    context_sha256 CHAR(64) PRIMARY KEY,
    authority_terminal_sha256 CHAR(64) NOT NULL,
    context_json JSONB NOT NULL,
    authority_json JSONB NOT NULL,
    registration_sha256 CHAR(64) NOT NULL,
    registration_mac_sha256 CHAR(64) NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_cleanup_v3_context_authority_run_context UNIQUE (
        run_id_sha256, context_sha256
    ),
    CONSTRAINT uq_cleanup_v3_context_authority_run_context_terminal UNIQUE (
        run_id_sha256, context_sha256, authority_terminal_sha256
    ),
    CONSTRAINT ck_projection_context_authority_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND context_sha256 ~ '^[0-9a-f]{64}$'
        AND authority_terminal_sha256 ~ '^[0-9a-f]{64}$'
        AND registration_sha256 ~ '^[0-9a-f]{64}$'
        AND registration_mac_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE IF NOT EXISTS memory_projection_receipt_claims (
    outbox_id INTEGER PRIMARY KEY REFERENCES memory_outbox(id) ON DELETE CASCADE,
    run_id_sha256 CHAR(64) NOT NULL,
    context_sha256 CHAR(64) NOT NULL,
    worker_authority_sha256 CHAR(64) NOT NULL,
    projection_key_sha256 CHAR(64) NOT NULL,
    operation VARCHAR(20) NOT NULL,
    expected_identities_sha256 CHAR(64) NOT NULL,
    claim_token_sha256 CHAR(64) NOT NULL,
    generation INTEGER NOT NULL,
    state VARCHAR(24) NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_projection_receipt_claim_context FOREIGN KEY (
        run_id_sha256, context_sha256
    ) REFERENCES memory_cleanup_v3_context_authorities(
        run_id_sha256, context_sha256
    ),
    CONSTRAINT ck_projection_receipt_claim_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND context_sha256 ~ '^[0-9a-f]{64}$'
        AND worker_authority_sha256 ~ '^[0-9a-f]{64}$'
        AND projection_key_sha256 ~ '^[0-9a-f]{64}$'
        AND expected_identities_sha256 ~ '^[0-9a-f]{64}$'
        AND claim_token_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_projection_receipt_claim_state CHECK (
        state IN ('prepared', 'dispatch_started')
        AND generation > 0
        AND operation IN ('upsert', 'delete')
    )
);

CREATE TABLE IF NOT EXISTS memory_projection_result_receipts (
    outbox_id INTEGER PRIMARY KEY REFERENCES memory_outbox(id),
    run_id_sha256 CHAR(64) NOT NULL
        REFERENCES memory_comparison_benchmark_runs(run_id_sha256),
    context_sha256 CHAR(64) NOT NULL,
    lane VARCHAR(40) NOT NULL,
    operation VARCHAR(20) NOT NULL,
    result_state VARCHAR(20) NOT NULL,
    space_id VARCHAR(80) NOT NULL,
    memory_scope_id VARCHAR(80) NOT NULL,
    thread_id VARCHAR(80),
    aggregate_type VARCHAR(80) NOT NULL,
    aggregate_id VARCHAR(80) NOT NULL,
    aggregate_version INTEGER,
    target_authority_sha256 CHAR(64) NOT NULL,
    worker_authority_sha256 CHAR(64) NOT NULL,
    outbox_event_commitment_sha256 CHAR(64) NOT NULL,
    identity_count INTEGER NOT NULL,
    ordered_identity_root_sha256 CHAR(64) NOT NULL,
    lineage_root_sha256 CHAR(64) NOT NULL,
    provider_completed_at TIMESTAMPTZ NOT NULL,
    persisted_at TIMESTAMPTZ NOT NULL,
    receipt_sha256 CHAR(64) NOT NULL,
    receipt_mac_sha256 CHAR(64) NOT NULL,
    CONSTRAINT ck_projection_receipt_identity_count CHECK (
        identity_count BETWEEN 1 AND 1000000
    ),
    CONSTRAINT ck_projection_receipt_lane CHECK (lane IN ('qdrant', 'graphiti')),
    CONSTRAINT ck_projection_receipt_operation CHECK (
        operation IN ('upsert', 'delete')
    ),
    CONSTRAINT ck_projection_receipt_result_state CHECK (
        result_state IN ('present', 'absent')
    ),
    CONSTRAINT ck_projection_receipt_operation_result CHECK (
        (operation = 'upsert' AND result_state = 'present')
        OR (operation = 'delete' AND result_state = 'absent')
    ),
    CONSTRAINT ck_projection_receipt_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND context_sha256 ~ '^[0-9a-f]{64}$'
        AND target_authority_sha256 ~ '^[0-9a-f]{64}$'
        AND worker_authority_sha256 ~ '^[0-9a-f]{64}$'
        AND outbox_event_commitment_sha256 ~ '^[0-9a-f]{64}$'
        AND ordered_identity_root_sha256 ~ '^[0-9a-f]{64}$'
        AND lineage_root_sha256 ~ '^[0-9a-f]{64}$'
        AND receipt_sha256 ~ '^[0-9a-f]{64}$'
        AND receipt_mac_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT fk_projection_receipt_context_authority FOREIGN KEY (
        run_id_sha256, context_sha256
    ) REFERENCES memory_cleanup_v3_context_authorities(
        run_id_sha256, context_sha256
    ),
    CONSTRAINT uq_projection_receipt_outbox_run UNIQUE (outbox_id, run_id_sha256),
    CONSTRAINT uq_projection_receipt_canonical_job UNIQUE NULLS NOT DISTINCT (
        run_id_sha256, context_sha256, lane, operation, aggregate_type, aggregate_id,
        aggregate_version
    )
);

CREATE INDEX IF NOT EXISTS ix_projection_receipts_run_receipt
    ON memory_projection_result_receipts(run_id_sha256, receipt_sha256);

CREATE INDEX IF NOT EXISTS ix_projection_receipts_cleanup_page
    ON memory_projection_result_receipts(
        run_id_sha256, context_sha256, space_id, outbox_id
    );

CREATE INDEX IF NOT EXISTS ix_projection_receipts_inventory_page
    ON memory_projection_result_receipts(
        run_id_sha256, context_sha256, space_id, lane, operation, outbox_id
    );

CREATE INDEX IF NOT EXISTS ix_projection_receipts_operation_page
    ON memory_projection_result_receipts(
        run_id_sha256, context_sha256, space_id,
        operation, outbox_id
    );

CREATE INDEX IF NOT EXISTS ix_projection_receipts_delete_page
    ON memory_projection_result_receipts(
        run_id_sha256, context_sha256, space_id, outbox_id
    ) WHERE operation = 'delete';

CREATE TABLE IF NOT EXISTS memory_projection_target_identities (
    run_id_sha256 CHAR(64) NOT NULL
        REFERENCES memory_comparison_benchmark_runs(run_id_sha256),
    kind VARCHAR(40) NOT NULL,
    identity_sha256 CHAR(64) NOT NULL,
    identity_commitment_sha256 CHAR(64) NOT NULL,
    canonical_source_id VARCHAR(160) NOT NULL,
    physical_identity TEXT NOT NULL,
    lineage_root_sha256 CHAR(64) NOT NULL,
    target_authority_sha256 CHAR(64) NOT NULL,
    identity_mac_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id_sha256, kind, identity_sha256),
    CONSTRAINT ck_projection_identity_physical_value CHECK (
        canonical_source_id <> '' AND physical_identity <> ''
    ),
    CONSTRAINT ck_projection_identity_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND identity_sha256 ~ '^[0-9a-f]{64}$'
        AND identity_commitment_sha256 ~ '^[0-9a-f]{64}$'
        AND lineage_root_sha256 ~ '^[0-9a-f]{64}$'
        AND target_authority_sha256 ~ '^[0-9a-f]{64}$'
        AND identity_mac_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_projection_identity_kind CHECK (kind IN (
        'qdrant_point_id', 'graphiti_group_id', 'graphiti_group_name',
        'graphiti_episode_uuid', 'graphiti_episode_name', 'graphiti_node_uuid',
        'graphiti_node_name', 'graphiti_relation_uuid', 'graphiti_relation_name'
    )),
    CONSTRAINT uq_projection_identity_authenticated UNIQUE (
        run_id_sha256, kind, identity_sha256, identity_commitment_sha256
    )
);

CREATE TABLE IF NOT EXISTS memory_projection_receipt_identity_links (
    outbox_id INTEGER NOT NULL,
    run_id_sha256 CHAR(64) NOT NULL,
    kind VARCHAR(40) NOT NULL,
    identity_sha256 CHAR(64) NOT NULL,
    identity_commitment_sha256 CHAR(64) NOT NULL,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY (outbox_id, run_id_sha256, kind, identity_sha256),
    CONSTRAINT fk_projection_receipt_link_identity FOREIGN KEY (
        run_id_sha256, kind, identity_sha256, identity_commitment_sha256
    ) REFERENCES memory_projection_target_identities(
        run_id_sha256, kind, identity_sha256, identity_commitment_sha256
    ),
    CONSTRAINT fk_projection_receipt_link_receipt FOREIGN KEY (
        outbox_id, run_id_sha256
    ) REFERENCES memory_projection_result_receipts(
        outbox_id, run_id_sha256
    ) ON DELETE CASCADE,
    CONSTRAINT ck_projection_receipt_link_ordinal CHECK (ordinal >= 0),
    CONSTRAINT ck_projection_receipt_link_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND identity_sha256 ~ '^[0-9a-f]{64}$'
        AND identity_commitment_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT uq_projection_receipt_link_ordinal UNIQUE (outbox_id, ordinal)
);

CREATE INDEX IF NOT EXISTS ix_projection_links_identity_outbox
    ON memory_projection_receipt_identity_links(
        run_id_sha256, kind, identity_sha256,
        identity_commitment_sha256, outbox_id
    ) INCLUDE (ordinal);

CREATE INDEX IF NOT EXISTS ix_projection_links_outbox_page
    ON memory_projection_receipt_identity_links(
        run_id_sha256, outbox_id, identity_sha256,
        kind, identity_commitment_sha256
    );

CREATE INDEX IF NOT EXISTS ix_memory_scopes_space_id_id
    ON memory_scopes(space_id, id);

CREATE INDEX IF NOT EXISTS ix_memory_threads_space_scope_id
    ON memory_threads(space_id, memory_scope_id, id);

CREATE TABLE IF NOT EXISTS memory_cleanup_inventory_materializations (
    run_id_sha256 CHAR(64) NOT NULL
        REFERENCES memory_comparison_benchmark_runs(run_id_sha256),
    context_sha256 CHAR(64) NOT NULL,
    cleanup_receipt_sha256 CHAR(64) NOT NULL,
    kind VARCHAR(80) NOT NULL,
    authority_terminal_sha256 CHAR(64) NOT NULL,
    expected_count INTEGER NOT NULL,
    ordered_rows_root_sha256 CHAR(64) NOT NULL,
    complete BOOLEAN NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL,
    row_mac_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (run_id_sha256, context_sha256, cleanup_receipt_sha256, kind),
    CONSTRAINT fk_cleanup_inventory_context_authority FOREIGN KEY (
        run_id_sha256, context_sha256, authority_terminal_sha256
    ) REFERENCES memory_cleanup_v3_context_authorities(
        run_id_sha256, context_sha256, authority_terminal_sha256
    ),
    CONSTRAINT ck_cleanup_inventory_expected_count CHECK (
        expected_count BETWEEN 0 AND 1000000000
    ),
    CONSTRAINT ck_cleanup_inventory_materialization_kind CHECK (kind IN (
        'memory_scopes', 'memory_threads', 'facts', 'fact_source_refs',
        'documents', 'chunks', 'qdrant_target_identities', 'graphiti_target_names',
        'graphiti_target_uuids', 'qdrant_upsert_jobs', 'qdrant_delete_jobs',
        'graphiti_upsert_jobs', 'graphiti_delete_jobs', 'cleanup_outbox_receipts',
        'unsupported_rows'
    )),
    CONSTRAINT ck_cleanup_inventory_materialization_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND context_sha256 ~ '^[0-9a-f]{64}$'
        AND cleanup_receipt_sha256 ~ '^[0-9a-f]{64}$'
        AND authority_terminal_sha256 ~ '^[0-9a-f]{64}$'
        AND ordered_rows_root_sha256 ~ '^[0-9a-f]{64}$'
        AND row_mac_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE IF NOT EXISTS memory_cleanup_inventory_keys (
    run_id_sha256 CHAR(64) NOT NULL,
    context_sha256 CHAR(64) NOT NULL,
    cleanup_receipt_sha256 CHAR(64) NOT NULL,
    kind VARCHAR(80) NOT NULL,
    canonical_key_sha256 CHAR(64) NOT NULL,
    locator_json JSONB NOT NULL,
    locator_sha256 CHAR(64) NOT NULL,
    row_sha256 CHAR(64) NOT NULL,
    row_mac_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (
        run_id_sha256, context_sha256, cleanup_receipt_sha256, kind,
        canonical_key_sha256
    ),
    CONSTRAINT fk_cleanup_inventory_key_materialization FOREIGN KEY (
        run_id_sha256, context_sha256, cleanup_receipt_sha256, kind
    ) REFERENCES memory_cleanup_inventory_materializations(
        run_id_sha256, context_sha256, cleanup_receipt_sha256, kind
    ),
    CONSTRAINT uq_cleanup_inventory_locator UNIQUE (
        run_id_sha256, context_sha256, cleanup_receipt_sha256, kind, locator_sha256
    ),
    CONSTRAINT ck_cleanup_inventory_key_kind CHECK (kind IN (
        'memory_scopes', 'memory_threads', 'facts', 'fact_source_refs',
        'documents', 'chunks', 'qdrant_target_identities', 'graphiti_target_names',
        'graphiti_target_uuids', 'qdrant_upsert_jobs', 'qdrant_delete_jobs',
        'graphiti_upsert_jobs', 'graphiti_delete_jobs', 'cleanup_outbox_receipts',
        'unsupported_rows'
    )),
    CONSTRAINT ck_cleanup_inventory_key_digests CHECK (
        run_id_sha256 ~ '^[0-9a-f]{64}$'
        AND context_sha256 ~ '^[0-9a-f]{64}$'
        AND cleanup_receipt_sha256 ~ '^[0-9a-f]{64}$'
        AND canonical_key_sha256 ~ '^[0-9a-f]{64}$'
        AND locator_sha256 ~ '^[0-9a-f]{64}$'
        AND row_sha256 ~ '^[0-9a-f]{64}$'
        AND row_mac_sha256 ~ '^[0-9a-f]{64}$'
    )
);
