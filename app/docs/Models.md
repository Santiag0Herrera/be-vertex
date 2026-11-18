# Modelo de datos

Modelos SQLAlchemy definidos en `app/models.py`. Todas las tablas de negocio llevan `entity_id`: cada entidad (tenant) sólo ve sus propios datos.

```text
entities ─┬─ users ─────────────── permissions ── products
          ├─ clients ── customers_balance ─┬─ trx ── transaction_documents ── document_upload_sessions
          │                                ├─ payments ── payment_orders
          │                                └─ fee_withdrawals
          └─ entities_cbus ── cbus / currency
endpoints ── permissions
logs (auditoría)
```

## Identidad y permisos

### `entities` — Entity
Empresa que usa Vertex. Se administra directamente en la base; no hay endpoints de alta.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | Integer | PK |
| `name`, `mail` | String | obligatorios |
| `phone`, `products`, `status` | String | `status` deshabilita la entidad y sus tokens |

### `entities_cbus` — EntityCBU
Cuentas bancarias propias de la entidad, contra las que se concilia. Une `entity_id`, `cbu_id` y `currency_id`.

### `cbus` — CBU
`nro` (único), `banco`, `alias`, `cuit`.

### `users` — Users
Personal interno de la entidad. Inicia sesión con email.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | Integer | PK |
| `first_name`, `last_name` | String | obligatorios |
| `email` | String | único |
| `hashed_password` | String | bcrypt |
| `phone` | String | |
| `perm_id` | FK `permissions` | |
| `entity_id` | FK `entities` | |
| `enabled` | Boolean | `false` invalida sus tokens |

### `clients` — Clients
Clientes finales de la entidad. Inician sesión con CUIT.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | Integer | PK |
| `first_name`, `last_name` | String | obligatorios |
| `email` | String | único |
| `cuit` | String(11) | nullable sólo por datos históricos; la API lo exige |
| `hashed_password`, `phone` | String | |
| `perm_id`, `entity_id` | FK | obligatorios |
| `enabled` | Boolean | |

### `permissions` — Permission
`product` (FK `products`), `level` (`client`, `user`, `admin` o `super`) y `hierarchy` (entero; mayor jerarquía, más acceso).

### `products` — Product
Productos que ofrece la plataforma: `name`, `description`, `img`, `path` (ruta del frontend).

### `endpoints` — Endpoints
Registro de rutas de la API. `path` (template, único) y `perm_id` (permiso mínimo; `NULL` = pública). Ver [PermissionMiddleware.md](PermissionMiddleware.md).

### `logs` — Logs
Auditoría de requests: `datetime`, `endpoint`, `method`, `username`.

## Cuentas y dinero

### `customers_balance` — CustomersBalance
Cuenta de un cliente. Un cliente puede tener varias.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | Integer | PK |
| `client_id` | FK `clients` | indexado, no único |
| `balance_amount` | Float | saldo acreditado |
| `fee_amount` | Float | comisión acumulada sin retirar |
| `fee_percentage` | Float | comisión aplicada a cada transacción conciliada |
| `balance_currency_id` | FK `currency` | |
| `last_update` | DateTime | |
| `enabled` | Boolean | |

### `currency` — Currency
Monedas disponibles (`name`).

### `payments` — Payments
Pago realizado desde una cuenta: `amount`, `date`, `status`, `customer_balance_id`, `currency_id`, `payee_user_id` (usuario interno que lo ejecutó), `entity_id` y, opcionalmente, `payment_order_id`.

### `payment_orders` — PaymentOrders
Orden de pago creada por un cliente y ejecutada por usuarios internos, en uno o más pagos.

| Campo | Tipo | Notas |
|---|---|---|
| `amount` | Numeric(10,2) | > 0 |
| `executed_amount` | Numeric(10,2) | entre 0 y `amount` |
| `status` | String | `pendiente_aprobacion`, `parcialmente_ejecutada` o `ejecutada` |
| `client_id`, `customer_balance_id`, `entity_id`, `currency_id` | FK | |
| `created_at`, `updated_at` | DateTime | |

### `fee_withdrawals` — FeeWithdrawals
Retiro de la comisión acumulada de una cuenta: `amount`, `date`, `status` (`consolidado`), `customer_balance_id`, `withdrawn_by_user_id`, `entity_id`, `currency_id`.

## Comprobantes

### `trx` — Trx
Cada comprobante de transferencia cargado.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | Integer | PK interna |
| `trx_id` | String | identificador único visible |
| `source_trx_id` | String | número de operación del comprobante |
| `emisor_cbu`, `emisor_name`, `emisor_cuit` | String | opcionales |
| `receptor_cbu` | String | obligatorio |
| `receptor_cuit` | String | |
| `amount` | Float | |
| `date` | DateTime | fecha del comprobante |
| `received_date` | Date | fecha en que se recibió del cliente (default: hoy en Argentina) |
| `creation_date` | DateTime | alta en Vertex (UTC, auditoría) |
| `reconciled_at` | DateTime tz | momento de la conciliación |
| `status` | String | `pendiente`, `conciliado`, `repetido` o `vencida` (ver [Conciliacion.md](Conciliacion.md)) |
| `account_id` | FK `customers_balance` | obligatorio |
| `client_id`, `entity_id` | FK | |
| `applied_fee_percentage`, `fee_amount` | Float | comisión aplicada al conciliar |
| `file_sha256` | String(64) | hash del archivo; único por entidad |
| `receipt_fingerprint` | String(64) | huella de los datos del comprobante; única por entidad |
| `document_fingerprint` | String | huella del movimiento de Interbanking; única entre conciliados |
| `document_name` | String | nombre original del archivo |

Los tres índices únicos parciales impiden cargar dos veces el mismo comprobante y conciliar dos comprobantes contra el mismo movimiento bancario.

### `document_upload_sessions` — DocumentUploadSession
Sesión de carga directa a S3. `id` (UUID), `entity_id`, `actor_id`, `actor_type`, `status` (`created`, `uploading`, `committing`, `committed`, `expired`), `expires_at`, `committed_at`, `result_json`.

### `transaction_documents` — TransactionDocument
Archivo de un comprobante en S3.

| Campo | Notas |
|---|---|
| `id` | UUID |
| `upload_session_id`, `client_document_id` | únicos en conjunto |
| `trx_id` | FK `trx.id`, único |
| `staging_key`, `object_key` | claves en S3 (staging y definitiva) |
| `original_name`, `mime_type`, `size_bytes`, `sha256` | metadatos |
| `status` | `pending_upload`, `staged`, `active`, `deleting`, `deleted` |
| `delete_after` | fecha desde la que puede eliminarse (dos meses después de conciliar) |
| `deleted_at`, `deletion_attempts`, `last_deletion_error` | control de la eliminación |

## Notas

- Los montos de `trx`, `customers_balance`, `payments` y `fee_withdrawals` usan `Float`; sólo `payment_orders` usa `Numeric`.
- `create_tables()` crea tablas faltantes pero no altera las existentes. Los cambios de esquema se aplican con `migrations/`.
