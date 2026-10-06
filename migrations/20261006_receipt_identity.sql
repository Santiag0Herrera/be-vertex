-- Stable receipt identity used to reject duplicate uploads before reconciliation.
-- Existing rows remain NULL because historical uploads do not retain enough source data
-- to reconstruct these values safely.
ALTER TABLE trx
    ADD COLUMN IF NOT EXISTS file_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS receipt_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_trx_id VARCHAR;

CREATE INDEX IF NOT EXISTS ix_trx_source_trx_id
ON trx(source_trx_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trx_entity_file_sha256
ON trx(entity_id, file_sha256)
WHERE file_sha256 IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_trx_entity_receipt_fingerprint
ON trx(entity_id, receipt_fingerprint)
WHERE receipt_fingerprint IS NOT NULL;
