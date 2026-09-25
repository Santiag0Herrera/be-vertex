-- Conserva creation_date como auditoria y agrega la fecha operativa informada.
BEGIN;

ALTER TABLE trx ADD COLUMN IF NOT EXISTS received_date DATE;

-- creation_date se guarda como UTC sin zona horaria en la aplicacion.
UPDATE trx
SET received_date = (
    creation_date AT TIME ZONE 'UTC' AT TIME ZONE 'America/Argentina/Buenos_Aires'
)::date
WHERE received_date IS NULL;

ALTER TABLE trx
    ALTER COLUMN received_date SET DEFAULT (
        (CURRENT_TIMESTAMP AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
    ),
    ALTER COLUMN received_date SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_trx_entity_received_date
    ON trx(entity_id, received_date);

COMMIT;
