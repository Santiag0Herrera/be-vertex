# Vertex API

Backend de Vertex construido con FastAPI, SQLAlchemy 2, Pydantic 2 y PostgreSQL. Expone autenticación JWT, clientes, usuarios, cuentas, conciliación, órdenes de pago, dashboard y extracción de comprobantes.

## Requisitos

- Python 3.11 o superior.
- PostgreSQL.
- Credenciales de AWS Textract si se utiliza el extractor.
- Credenciales de Interbanking si se utilizan sus endpoints.

## Instalación local

Desde la raíz de `be-vertex`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Crear `dev.env` con, como mínimo:

```dotenv
ENVIRONMENT=dev
DATABASE_URL=postgresql://usuario:clave@localhost:5432/vertex
JWT_SECRET_KEY=una-clave-larga-aleatoria
ALLOW_ORIGINS=http://localhost:3000
```

`JWT_SECRET_KEY` es obligatorio y debe ser distinto por ambiente. Una clave puede generarse con `openssl rand -hex 32`. La API ya no contiene una clave JWT por defecto.

Iniciar la aplicación desde la raíz del repositorio:

```bash
uvicorn app.main:app --reload
```

Con `ENVIRONMENT=dev`, Swagger queda disponible en `http://localhost:8000/docs`.

## Base de datos

SQLAlchemy utiliza una única instancia de `Base`, definida en `app/db/database.py`. Al iniciar, `create_tables()` crea las tablas que falten y propaga cualquier error de conexión.

Alembic no forma parte del flujo actual y sus archivos existentes se mantienen sin cambios. Para una base nueva pueden utilizarse `data_base_start_up_query.txt` y, opcionalmente, los datos iniciales locales. Las entidades no se crean por API: deben administrarse directamente en PostgreSQL.

El modelo permite múltiples cuentas por cliente. En una base existente creada con la restricción histórica de cuenta única, hay que retirarla una sola vez directamente en PostgreSQL (el nombre predeterminado es `customers_balance_client_id_key`) y crear el índice no único `idx_customers_balance_client_id`. No se agregó una migración de Alembic porque ese mecanismo no forma parte del flujo del proyecto.

```sql
ALTER TABLE customers_balance
  DROP CONSTRAINT IF EXISTS customers_balance_client_id_key;
CREATE INDEX IF NOT EXISTS idx_customers_balance_client_id
  ON customers_balance(client_id);
```

## Autenticación y autorización

`POST /auth/token` acepta email para usuarios internos o CUIT para clientes y devuelve un JWT con vigencia de ocho horas. Todas las demás rutas requieren:

```http
Authorization: Bearer <token>
```

El middleware valida firma, vencimiento y claims mínimos. Las dependencias de cada ruta aplican el tipo de cuenta y rol requerido (`client`, usuario interno o `admin/super`). Además, en cada request se vuelve a consultar la cuenta, su permiso y la entidad; deshabilitar una cuenta, cambiarle el permiso o deshabilitar la entidad invalida efectivamente los tokens emitidos.

Las consultas y mutaciones por identificador están limitadas a `entity_id`. Un cliente queda limitado también a su propio `client_id` y sus cuentas.

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

## Reportes de comprobantes

`GET /trx/report.csv` genera el reporte operativo de comprobantes para usuarios internos. Acepta filtros opcionales por `month` (`AAAA-MM`), `date_from`, `date_to`, `status`, `client_id` y uno o más `account_ids`. Si se indica un cliente sin cuentas, se incluyen todas sus cuentas; si además se indican cuentas, todas deben pertenecer a ese cliente.

El reporte queda limitado a la entidad del usuario autenticado, se ordena y agrupa por fecha de carga, e informa además la fecha del comprobante. Agrega una fila de total al final de cada fecha. Se entrega en UTF-8 con BOM, separador punto y coma y saltos CRLF para facilitar su apertura directa en Excel. Si no hay resultados, responde HTTP 404 con un error JSON estándar.

## Interbanking

Variables disponibles:

```dotenv
MS_INTER_BANKING_AUTH_URL=
MS_INTER_BANKING_API_URL=
MS_INTER_BANKING_API_BALANCES=
MS_INTER_BANKING_API_ACCOUNTS=
MS_INTER_BANKING_CLIENT_ID=
MS_INTER_BANKING_CLIENT_SECRET=
MS_INTER_BANKING_CUSTOMER_ID=
MS_INTER_BANKING_AT=
MS_INTER_BANKING_TIMEOUT_SECONDS=20
```

Las llamadas se realizan con `httpx.AsyncClient`; no bloquean el event loop. Un timeout devuelve HTTP 504, un error de conexión HTTP 502 y una configuración faltante HTTP 503. No se envían cookies hardcodeadas.

## Pruebas

La configuración de base debe existir al importar la aplicación. Para ejecutar la suite:

```bash
DATABASE_URL=postgresql://usuario:clave@localhost:5432/vertex_test \
AWS_EC2_METADATA_DISABLED=true \
JWT_SECRET_KEY=test-secret \
.venv/bin/python -m pytest -q
```

La suite incluye regresiones para autenticación revocable, aislamiento entre entidades, contratos de saldos, exportación CSV e Interbanking asíncrono.

## Alcance de administración

No existe alta de entidades desde la API.

La referencia de rutas está en [app/docs/Endpoints.md](app/docs/Endpoints.md) y el diseño de autorización en [app/docs/PermissionMiddleware.md](app/docs/PermissionMiddleware.md).
