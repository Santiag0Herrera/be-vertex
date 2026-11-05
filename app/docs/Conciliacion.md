# Extracción, duplicados y conciliación

Este documento describe el ciclo de vida de un comprobante, desde que se sube hasta que acredita el saldo del cliente.

## 1. Extracción con Gemini

`POST /extractorV2/extract` recibe el archivo (PDF o imagen) y llama a `app/services/extractor/service.py`:

1. Valida tipo y tamaño del archivo.
2. Envía el contenido a la API de Google Gemini (`GEMINI_MODEL`, por defecto `gemini-2.5-flash`) mediante `gemini_client.py`.
3. Normaliza los campos devueltos (`normalizer.py`, `parsers.py`, `aliases.py`) y les asigna un puntaje de confianza (`scoring.py`, `heuristics.py`).
4. Calcula la identidad del comprobante (ver punto 2).

La respuesta mantiene el esquema tipado `DocumentExtractResponse`, sin el sobre `{"status","result"}`. Los errores de Gemini (cuota, timeout, respuesta inválida) se traducen a códigos HTTP con `retry_after` cuando corresponde.

`POST /extractorV2/aws-extract` es un alias histórico; también usa Gemini.

## 2. Detección de comprobantes repetidos

`app/services/ReceiptIdentityService.py` calcula dos huellas por comprobante:

| Huella | Cómo se calcula | Detecta |
|---|---|---|
| `file_sha256` | SHA-256 del archivo | el mismo archivo subido dos veces |
| `receipt_fingerprint` | SHA-256 del número de operación, monto en centavos y fecha y hora | el mismo comprobante en otro archivo (captura, reenvío) |

Si el número de operación tiene menos de cuatro caracteres, no se calcula `receipt_fingerprint`.

Ambas huellas son únicas por entidad. Si alguna ya existe, la extracción y el alta responden **HTTP 409** con los datos del comprobante original.

## 3. Alta y almacenamiento en S3

1. `POST /documents/upload-sessions` crea una sesión y devuelve formularios firmados para subir cada archivo directamente al bucket (`DOCUMENT_BUCKET`) bajo una clave de staging.
2. El frontend sube los archivos sin pasar por la API.
3. `POST /trx/new` o `POST /trx/multiple/new` confirman la sesión: crean cada `trx` en estado `pendiente` y mueven el archivo a su clave definitiva (`transaction_documents.status = active`).
4. `POST /trx/{trx_id}/document-url` devuelve una URL temporal (`DOCUMENT_VIEW_TTL_SECONDS`) para ver el comprobante.

Diseño completo en `../implementation_plan.md`.

## 4. Conciliación contra Interbanking

`POST /trx/reconcile-pending` (usuarios internos) ejecuta `app/jobs/validate_trx.py` para la entidad del usuario. También puede correrse para todas las entidades:

```bash
python -m app.jobs.validate_trx
```

Sólo puede haber una ejecución a la vez: la API usa un lock en memoria (responde 409 si está ocupado) y el job toma además un advisory lock de PostgreSQL.

### Pasos

1. **Vencimiento.** Las transacciones `pendiente` con fecha de comprobante de hace más de un mes calendario pasan a `vencida`.
2. **Cuentas.** Obtiene de Interbanking las cuentas de la entidad y asocia cada transacción a su cuenta receptora (`receptor_cbu`). Las que no tienen cuenta se omiten.
3. **Fecha de acreditación.** `BusinessCalendarService` calcula el siguiente día hábil (fines de semana, feriados de `api.argentinadatos.com` y `ARGENTINA_BANK_HOLIDAYS`). Se aceptan movimientos con la fecha del comprobante o con esa fecha hábil.
4. **Movimientos.** Agrupa las transacciones por cuenta y rango de fechas y pide los movimientos a Interbanking una vez por grupo. Si la respuesta llega al límite de resultados, el grupo queda pendiente para no conciliar con datos truncados.
5. **Matching.** Un movimiento es candidato si:
   - es un crédito (`debit_credit_type = "C"`);
   - tiene el mismo monto absoluto;
   - su fecha está entre las fechas válidas.
6. **Huella del movimiento.** Cada movimiento recibe un `document_fingerprint` (SHA-256 de banco, cuenta, números de comprobante y operación, fecha, monto, CUIT y CBU). Si hay varios movimientos idénticos sin identificador fuerte, se numeran como slots (`<huella>:2`, `<huella>:3`…).
7. **Resultado.**
   - Si el movimiento ya fue usado por otra transacción conciliada y no quedan slots libres → `repetido`.
   - Si está libre → `conciliado`: se guarda la huella, se registra `reconciled_at`, se calcula la comisión (`fee_percentage` de la cuenta) y se acredita en `customers_balance` el monto menos la comisión. El archivo en S3 queda marcado para borrarse dos meses después.
   - Si no hay coincidencia → sigue `pendiente` para la próxima ejecución.

El índice único `uq_trx_conciliated_document_fingerprint` garantiza a nivel de base que un movimiento bancario no se use dos veces.

La respuesta del endpoint resume la ejecución con `checked`, `conciliated`, `repeated`, `expired`, `skipped`, `skipped_by_reason`, `still_pending`, `movement_requests`, `movement_cache_hits` y `duration_seconds`.

## Estados de una transacción

```text
pendiente ──► conciliado
    │
    ├──► repetido
    └──► vencida
```

`rechazado` está aceptado como filtro en `GET /trx/report.csv`, pero ningún proceso actual asigna ese estado.

## Retención de comprobantes

- `GET /documents/expired-summary` (admin/super) informa los archivos con `delete_after` vencido.
- `POST /documents/delete-expired` (admin/super) los elimina de S3 y marca `transaction_documents.status = deleted`.
- Las sesiones de carga abandonadas expiran tras `DOCUMENT_SESSION_TTL_HOURS`; los objetos de staging se limpian con la regla lifecycle del bucket.
