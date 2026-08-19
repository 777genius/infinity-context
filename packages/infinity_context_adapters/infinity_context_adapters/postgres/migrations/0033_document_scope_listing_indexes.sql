CREATE INDEX IF NOT EXISTS ix_memory_documents_scope_status_page
  ON memory_documents (
    space_id,
    memory_scope_id,
    status,
    updated_at DESC,
    id DESC
  );

CREATE INDEX IF NOT EXISTS ix_memory_documents_scope_thread_status_page
  ON memory_documents (
    space_id,
    memory_scope_id,
    thread_id,
    status,
    updated_at DESC,
    id DESC
  );

CREATE INDEX IF NOT EXISTS ix_memory_documents_scope_thread_source_page
  ON memory_documents (
    space_id,
    memory_scope_id,
    thread_id,
    source_external_id,
    status,
    updated_at DESC,
    id DESC
  );
