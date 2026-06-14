CREATE TABLE IF NOT EXISTS memory_users (
    id VARCHAR(80) PRIMARY KEY,
    external_ref VARCHAR(200) NOT NULL,
    display_name VARCHAR(240) NOT NULL,
    email VARCHAR(320),
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    metadata_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_user_external_ref
ON memory_users(external_ref);

CREATE INDEX IF NOT EXISTS ix_memory_users_status
ON memory_users(status, updated_at);

CREATE TABLE IF NOT EXISTS memory_space_memberships (
    id VARCHAR(80) PRIMARY KEY,
    space_id VARCHAR(80) NOT NULL REFERENCES memory_spaces(id),
    user_id VARCHAR(80) NOT NULL REFERENCES memory_users(id),
    role VARCHAR(40) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_space_membership_active_user
ON memory_space_memberships(space_id, user_id)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_memory_space_memberships_space
ON memory_space_memberships(space_id, status, updated_at);

CREATE INDEX IF NOT EXISTS ix_memory_space_memberships_user
ON memory_space_memberships(user_id, status, updated_at);
