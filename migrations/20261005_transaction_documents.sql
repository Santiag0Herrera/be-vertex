BEGIN;

ALTER TABLE trx
    ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS document_upload_sessions (
    id VARCHAR(36) PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    actor_id INTEGER NOT NULL,
    actor_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'created',
    expires_at TIMESTAMPTZ NOT NULL,
    committed_at TIMESTAMPTZ NULL,
    result_json TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_document_upload_sessions_actor_type
        CHECK (actor_type IN ('user', 'client')),
    CONSTRAINT ck_document_upload_sessions_status
        CHECK (status IN (
            'created',
            'uploading',
            'ready',
            'committing',
            'committed',
            'expired',
            'failed'
        ))
);

CREATE INDEX IF NOT EXISTS ix_document_upload_sessions_entity_id
    ON document_upload_sessions (entity_id);

CREATE INDEX IF NOT EXISTS ix_document_upload_sessions_status
    ON document_upload_sessions (status);

CREATE INDEX IF NOT EXISTS ix_document_upload_sessions_expires_at
    ON document_upload_sessions (expires_at);

CREATE TABLE IF NOT EXISTS transaction_documents (
    id VARCHAR(36) PRIMARY KEY,
    upload_session_id VARCHAR(36) NOT NULL REFERENCES document_upload_sessions(id),
    client_document_id VARCHAR(36) NOT NULL,
    trx_id INTEGER NULL UNIQUE REFERENCES trx(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    staging_key TEXT NOT NULL UNIQUE,
    object_key TEXT NULL UNIQUE,
    original_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending_upload',
    uploaded_at TIMESTAMPTZ NULL,
    activated_at TIMESTAMPTZ NULL,
    delete_after TIMESTAMPTZ NULL,
    deleted_at TIMESTAMPTZ NULL,
    deletion_attempts INTEGER NOT NULL DEFAULT 0,
    last_deletion_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_transaction_documents_session_client_id
        UNIQUE (upload_session_id, client_document_id),
    CONSTRAINT ck_transaction_documents_size
        CHECK (size_bytes > 0),
    CONSTRAINT ck_transaction_documents_status
        CHECK (status IN (
            'pending_upload',
            'staged',
            'active',
            'deleting',
            'deleted',
            'failed'
        ))
);

CREATE INDEX IF NOT EXISTS ix_transaction_documents_upload_session_id
    ON transaction_documents (upload_session_id);

CREATE INDEX IF NOT EXISTS ix_transaction_documents_entity_id
    ON transaction_documents (entity_id);

CREATE INDEX IF NOT EXISTS ix_transaction_documents_status
    ON transaction_documents (status);

CREATE INDEX IF NOT EXISTS ix_transaction_documents_delete_after_active
    ON transaction_documents (delete_after)
    WHERE status IN ('active', 'deleting') AND delete_after IS NOT NULL;

COMMIT;
