-- Ejecutar antes de desplegar el backend de órdenes de pago.
BEGIN;
CREATE TABLE IF NOT EXISTS payment_orders (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    customer_balance_id INTEGER NOT NULL REFERENCES customers_balance(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    currency_id INTEGER NOT NULL REFERENCES currency(id),
    amount NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    executed_amount NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (executed_amount >= 0 AND executed_amount <= amount),
    status VARCHAR NOT NULL DEFAULT 'pendiente_aprobacion' CHECK (status IN ('pendiente_aprobacion', 'parcialmente_ejecutada', 'ejecutada')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_payment_orders_entity_id ON payment_orders(entity_id);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_order_id INTEGER REFERENCES payment_orders(id);
CREATE INDEX IF NOT EXISTS ix_payments_payment_order_id ON payments(payment_order_id);

-- Copiar los permisos existentes de consulta de clientes y ejecución de pagos.
INSERT INTO endpoints (path, perm_id)
SELECT routes.path, source.perm_id
FROM (VALUES
    ('/payment-orders/create', '/balance/client/all'),
    ('/payment-orders/all', '/balance/client/all'),
    ('/payment-orders/detail', '/balance/client/all'),
    ('/payment-orders/execute', '/payments/create')
) AS routes(path, source_path)
JOIN endpoints source ON source.path = routes.source_path
ON CONFLICT (path) DO NOTHING;
COMMIT;
