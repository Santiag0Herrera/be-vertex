-- Prevent two reconciled receipts from claiming the same Interbanking movement
-- while allowing repeated receipts to retain the fingerprint they collided with.
CREATE UNIQUE INDEX IF NOT EXISTS uq_trx_conciliated_document_fingerprint
ON trx(document_fingerprint)
WHERE status = 'conciliado' AND document_fingerprint IS NOT NULL;
