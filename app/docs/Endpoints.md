# Rutas de la API

Salvo `POST /auth/token`, todas las rutas requieren un JWT. Las respuestas de negocio usan `{"status":"ok","result":...}`.

## Autenticación

- `POST /auth/token`: login por email o CUIT.

## Usuarios internos

- `GET /users/all`
- `GET /users/me`
- `PUT /users/me`
- `PUT /users/me/changePassword`
- `POST /users/newUser` — admin/super.
- `DELETE /users/delete?user_id={id}` — admin/super.
- `PUT /users/changePermisson` — admin/super; se conserva el nombre histórico de la ruta.

## Clientes

- `GET /clients/all`
- `POST /clients/create` — admin/super.
- `PUT /clients/update?client_id={id}` — admin/super.
- `DELETE /clients/delete?client_id={id}` — admin/super.
- `GET /clients/me` — cliente autenticado.

## Entidades

- `GET /entities/all` — admin/super; un admin sólo ve su entidad.
- `GET /entities/{entity_id}` — admin/super y limitado por entidad.

No hay endpoint de alta, modificación ni baja de entidades. Esa administración se realiza directamente en la base de datos.

## Saldos y movimientos

- `GET /balance/all`
- `GET /balance/detail?account_id={id}`
- `POST /balance/create` — admin/super.
- `PUT /balance/update-fee`
- `DELETE /balance/delete`
- `POST /balance/withdraw-fee`
- `GET /balance/fee-withdrawals`
- `GET /balance/client/all` — sólo el cliente autenticado.
- `GET /balance/client/detail` — sólo una cuenta del cliente autenticado.

## Transacciones y conciliación

- `POST /trx/reconcile-pending`
- `GET /trx/all`
- `GET /trx/report.csv` — reporte CSV para usuarios internos; admite `month`, `date_from`, `date_to` (sobre la fecha de carga), `status`, `client_id` y múltiples `account_ids`.
- `GET /trx/all_by_client` — sólo el cliente autenticado.
- `POST /trx/new`
- `POST /trx/multiple/new`
- `GET /trx/get_movement`
- `POST /trx/get_movements`
- `GET /trx/get_owner_accounts`
- `GET /trx/get_all_movements`
- `GET /trx/get_accounts`

## Pagos y órdenes

- `POST /payments/create`
- `POST /payment-orders/create` — sólo clientes.
- `GET /payment-orders/all`
- `GET /payment-orders/detail`
- `POST /payment-orders/execute` — sólo usuarios internos.

## Otros

- `GET /products/all`
- `GET /currency/all`
- `GET /logs/all` — admin/super y limitado a actores de su entidad.
- `GET /dashboard/summary`
- `POST /extractor/aws-extract`
- `POST /extractorV2/aws-extract`

Swagger en desarrollo es la fuente exacta de parámetros y esquemas: `/docs`.
