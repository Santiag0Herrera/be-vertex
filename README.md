# Vertex API

Backend de Vertex construido con FastAPI, SQLAlchemy 2, Pydantic 2 y PostgreSQL.

Vertex permite que una entidad (tenant) reciba comprobantes de transferencias de sus clientes, extraiga sus datos con Google Gemini, los concilie contra los movimientos bancarios reales obtenidos de Interbanking y, al conciliarlos, acredite el saldo de la cuenta del cliente descontando la comisión configurada.

## Flujo principal

1. **Login** — `POST /auth/token` con email (usuario interno) o CUIT (cliente). Devuelve un JWT de ocho horas.
2. **Extracción** — `POST /extractorV2/extract` envía el comprobante a Gemini y devuelve los campos detectados (CBU, CUIT, monto, fecha, número de operación). Antes de responder se rechazan con HTTP 409 los comprobantes ya cargados.
3. **Carga del archivo** — `POST /documents/upload-sessions` entrega formularios firmados para subir el comprobante directamente a S3, sin pasar por la API.
4. **Alta** — `POST /trx/new` o `POST /trx/multiple/new` crean las transacciones en estado `pendiente` y asocian cada archivo.
5. **Conciliación** — `POST /trx/reconcile-pending` ejecuta el job `app/jobs/validate_trx.py`, que compara las transacciones pendientes con los movimientos de Interbanking. Ver [app/docs/Conciliacion.md](app/docs/Conciliacion.md).
6. **Saldos y pagos** — las transacciones conciliadas acreditan `customers_balance`. Los clientes crean órdenes de pago y los usuarios internos las ejecutan, total o parcialmente.

## Estructura

```text
app/
  main.py              # crea la app, registra middlewares y routers
  models.py            # modelos SQLAlchemy
  db/database.py       # engine, SessionLocal, Base y create_tables()
  router/              # endpoints HTTP, uno por dominio
  schemas/             # contratos Pydantic de entrada y salida
  services/            # lógica de negocio
    extractor/         # cliente Gemini, normalización y scoring de campos
  jobs/validate_trx.py # conciliación contra Interbanking
  middlewares/         # PermissionMiddleware y RequestLoggingMiddleware
  docs/                # documentación complementaria
migrations/            # scripts SQL que se aplican manualmente
tests/                 # suite pytest
```

## Requisitos

- Python 3.11 o superior.
- PostgreSQL (el `compose.yaml` local levanta PostgreSQL 17).
- Clave de API de Google Gemini para la extracción de comprobantes.
- Bucket S3 y credenciales de AWS para almacenar comprobantes.
- Credenciales de Interbanking para la conciliación.

## Instalación local

Desde la raíz de `be-vertex`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Base de datos local (opcional):

```bash
docker compose up -d postgres
```

Crear `dev.env` con las variables de la sección siguiente e iniciar la aplicación:

```bash
uvicorn app.main:app --reload
```

Con `ENVIRONMENT=dev`, Swagger queda disponible en `http://localhost:8000/docs`. En otros ambientes `/docs`, `/redoc` y `/openapi.json` se deshabilitan.

## Variables de entorno

`app/main.py` carga `dev.env` al iniciar.

### Generales

| Variable | Obligatoria | Default | Uso |
|---|---|---|---|
| `ENVIRONMENT` | No | `dev` | Con `dev` habilita Swagger. |
| `DATABASE_URL` | Sí | — | Conexión a PostgreSQL. |
| `JWT_SECRET_KEY` | Sí | — | Firma HS256 de los tokens. Distinta por ambiente; generar con `openssl rand -hex 32`. Se acepta `SECRET_KEY` como alternativa histórica. |
| `ALLOW_ORIGINS` | Sí | — | Origen permitido por CORS (un único valor), por ejemplo `http://localhost:3000`. |

### Extracción con Gemini

| Variable | Obligatoria | Default |
|---|---|---|
| `GEMINI_API_KEY` | Sí | — |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` |
| `GEMINI_TIMEOUT_SECONDS` | No | `20` |

### Comprobantes en S3

| Variable | Obligatoria | Default | Uso |
|---|---|---|---|
| `DOCUMENT_BUCKET` | Sí | — | Bucket privado de comprobantes. |
| `DOCUMENT_REGION` | No | `us-east-1` | Región del bucket. |
| `DOCUMENT_UPLOAD_TTL_SECONDS` | No | `600` | Vigencia de los formularios de carga. |
| `DOCUMENT_VIEW_TTL_SECONDS` | No | `120` | Vigencia de las URLs de visualización. |
| `DOCUMENT_SESSION_TTL_HOURS` | No | `24` | Vigencia de una sesión de carga. |
| `DOCUMENT_MAX_SIZE_BYTES` | No | `10485760` | Tamaño máximo por archivo (10 MB). |
| `DOCUMENT_MAX_BATCH_SIZE` | No | `50` | Archivos máximos por sesión. |

Las credenciales de AWS se toman de la cadena estándar de boto3 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` o un rol IAM). La configuración del bucket (CORS, lifecycle) está en la segunda parte de `../implementation_plan.md`.

### Interbanking

| Variable | Obligatoria | Default |
|---|---|---|
| `MS_INTER_BANKING_AUTH_URL` | Sí | — |
| `MS_INTER_BANKING_API_URL` | Sí | — |
| `MS_INTER_BANKING_API_BALANCES` | Sí | — |
| `MS_INTER_BANKING_API_ACCOUNTS` | Sí | — |
| `MS_INTER_BANKING_CLIENT_ID` | Sí | — |
| `MS_INTER_BANKING_CLIENT_SECRET` | Sí | — |
| `MS_INTER_BANKING_CUSTOMER_ID` | Sí | — |
| `MS_INTER_BANKING_AT` | Sí | — |
| `MS_INTER_BANKING_TIMEOUT_SECONDS` | No | `20` |
| `MS_INTER_BANKING_RETRY_ATTEMPTS` | No | `2` |
| `MS_INTER_BANKING_RETRY_DELAY_SECONDS` | No | `0.25` |

Las llamadas se realizan con `httpx.AsyncClient` y no bloquean el event loop. Un timeout devuelve HTTP 504, un error de conexión HTTP 502 y una configuración faltante HTTP 503.

### Calendario hábil

| Variable | Default | Uso |
|---|---|---|
| `ARGENTINA_BANK_HOLIDAYS` | vacío | Feriados bancarios adicionales, fechas ISO separadas por coma. |
| `ARGENTINA_HOLIDAYS_API_TIMEOUT_SECONDS` | `5` | Timeout de `api.argentinadatos.com`, de donde se obtienen los feriados nacionales. |

## Base de datos

SQLAlchemy utiliza una única instancia de `Base`, definida en `app/db/database.py`. Al iniciar, `create_tables()` crea las tablas que falten y propaga cualquier error de conexión. **No modifica tablas existentes**: los cambios de esquema se aplican con los scripts de `migrations/`.

Para una base nueva puede utilizarse `data_base_start_up_query.txt` y, opcionalmente, `data_base_start_up_inserts.sql` (datos locales, no versionados). Las entidades no se crean por API: deben administrarse directamente en PostgreSQL.

El modelo de tablas está descrito en [app/docs/Models.md](app/docs/Models.md).

### Migraciones

Alembic figura en `requirements.txt` pero no forma parte del flujo. Las migraciones son scripts SQL que se ejecutan manualmente, en orden, antes de desplegar la versión que los necesita:

| Script | Cambio |
|---|---|
| `20260907_receipt_fingerprint.sql` | Huella de comprobante en `trx`. |
| `20260908_payment_orders.sql` | Tabla `payment_orders` y vínculo con `payments`. |
| `20260925_transaction_received_date.sql` | Columna `trx.received_date`. |
| `20260929_reconciliation_integrity.sql` | Índice único: dos comprobantes conciliados no pueden usar el mismo movimiento bancario. |
| `20261005_transaction_documents.sql` | Tablas de sesiones de carga y documentos en S3; columna `trx.reconciled_at`. |
| `20261006_receipt_identity.sql` | Detección de comprobantes repetidos por hash y huella. |
| `20261006_trx_required_receipt_fields.sql` | Columna `trx.receptor_cuit` para conservar los datos del comprobante. |
| `20261006_relax_receipt_identity.sql` | Nombre y CUIT del emisor pasan a ser opcionales. |

> **Pendiente:** `.gitignore` hace referencia a `migrations/20261102_enforce_endpoint_registry.sql`, con el catálogo de rutas para la tabla `endpoints`. Ese archivo no existe en el repositorio. Sin esa carga, `PermissionMiddleware` responde HTTP 403 a toda ruta no registrada, incluida `POST /auth/token`. Ver [app/docs/PermissionMiddleware.md](app/docs/PermissionMiddleware.md).

El modelo permite múltiples cuentas por cliente. En una base creada con la restricción histórica de cuenta única, hay que retirarla una sola vez:

```sql
ALTER TABLE customers_balance
  DROP CONSTRAINT IF EXISTS customers_balance_client_id_key;
CREATE INDEX IF NOT EXISTS idx_customers_balance_client_id
  ON customers_balance(client_id);
```

## Autenticación y autorización

`POST /auth/token` acepta email para usuarios internos o CUIT para clientes y devuelve un JWT con vigencia de ocho horas. Las rutas protegidas requieren:

```http
Authorization: Bearer <token>
```

Resumen:

1. `PermissionMiddleware` exige que la ruta esté registrada en la tabla `endpoints` (por su template, por ejemplo `/entities/{entity_id}`). Una ruta con `perm_id = NULL` es pública; una ruta ausente se rechaza con HTTP 403.
2. En rutas protegidas, valida firma, vencimiento y claims del JWT y compara producto y jerarquía con el permiso requerido.
3. Las dependencias de cada ruta vuelven a cargar el actor y aplican tipo de cuenta y rol (`client`, usuario interno o `admin/super`).

Deshabilitar una cuenta, cambiarle el permiso o deshabilitar la entidad invalida efectivamente los tokens emitidos. Las consultas por identificador están limitadas a `entity_id`, y un cliente queda limitado además a su `client_id` y sus cuentas.

Detalle completo en [app/docs/PermissionMiddleware.md](app/docs/PermissionMiddleware.md).

## Contrato de respuestas

Los endpoints de negocio responden con un sobre común:

```json
{
  "status": "ok",
  "result": {}
}
```

Los errores conservan el formato estándar de FastAPI:

```json
{
  "detail": "Descripción del error"
}
```

Las excepciones deliberadas son `POST /auth/token`, por el contrato OAuth2; los endpoints del extractor, que mantienen su esquema tipado de extracción; y `GET /trx/report.csv`, que devuelve un archivo `text/csv` descargable.

Cada respuesta incluye el encabezado `X-Request-ID`, que también aparece en los logs.

## Reportes de comprobantes

`GET /trx/report.csv` genera el reporte operativo de comprobantes para usuarios internos. Acepta filtros opcionales por `month` (`AAAA-MM`), `date_from`, `date_to`, `status`, `client_id` y uno o más `account_ids`. Si se indica un cliente sin cuentas, se incluyen todas sus cuentas; si además se indican cuentas, todas deben pertenecer a ese cliente.

El reporte queda limitado a la entidad del usuario autenticado, se ordena y agrupa por `received_date` (fecha en que el comprobante fue recibido del cliente) e informa además la fecha del comprobante. `creation_date` conserva el momento real de alta en Vertex como dato de auditoría. Agrega una fila de total al final de cada fecha. Se entrega en UTF-8 con BOM, separador punto y coma y saltos CRLF para facilitar su apertura directa en Excel. Si no hay resultados, responde HTTP 404 con un error JSON estándar.

## Pruebas

La configuración de base debe existir al importar la aplicación. Para ejecutar la suite:

```bash
DATABASE_URL=postgresql://usuario:clave@localhost:5432/vertex_test \
AWS_EC2_METADATA_DISABLED=true \
JWT_SECRET_KEY=test-secret \
.venv/bin/python -m pytest -q
```

La suite cubre autenticación revocable, registro de endpoints, aislamiento entre entidades, extracción con Gemini, detección de duplicados, conciliación (matching y vencimiento), calendario hábil, saldos, órdenes de pago, documentos en S3, exportación CSV e Interbanking asíncrono.

## Documentación complementaria

- [app/docs/Endpoints.md](app/docs/Endpoints.md): referencia de rutas.
- [app/docs/Models.md](app/docs/Models.md): tablas y relaciones.
- [app/docs/PermissionMiddleware.md](app/docs/PermissionMiddleware.md): autenticación y autorización.
- [app/docs/Conciliacion.md](app/docs/Conciliacion.md): extracción, duplicados y conciliación.
- [app/docs/TwoFactorAuthenticationImplementationPlan.md](app/docs/TwoFactorAuthenticationImplementationPlan.md): plan de 2FA (no implementado).
- `../implementation_plan.md`: diseño del almacenamiento de comprobantes en S3 y configuración de AWS.
