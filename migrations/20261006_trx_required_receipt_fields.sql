-- Preserve every field required to identify a receipt after it is loaded.
-- Existing rows remain NULL because receptor_cuit was not stored historically.
ALTER TABLE trx
    ADD COLUMN IF NOT EXISTS receptor_cuit VARCHAR(255);
