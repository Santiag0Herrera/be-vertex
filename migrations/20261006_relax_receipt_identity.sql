-- Sender data is not present in every receipt. Amount and transaction datetime
-- are the only mandatory fields used by the semantic receipt fingerprint.
ALTER TABLE trx
    ALTER COLUMN emisor_name DROP NOT NULL,
    ALTER COLUMN emisor_cuit DROP NOT NULL;
