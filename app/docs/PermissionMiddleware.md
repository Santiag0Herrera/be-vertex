# Autenticación y autorización

La autorización tiene tres capas complementarias. Las dos primeras viven en `app/middlewares/PermissionMiddleware.py`; la tercera, en las dependencias de `app/services/auth_service.py`.

## 1. Registro de endpoints

Toda request, incluidas las de CORS preflight (`OPTIONS`), debe resolver una ruta registrada en la tabla `endpoints`.

- El middleware traduce la URL concreta al template de FastAPI (`/entities/7` → `/entities/{entity_id}`) y busca ese `path` en la tabla.
- El registro es por ruta, no por método HTTP: una fila cubre todos los métodos de ese path.
- Si la ruta no está registrada, responde **HTTP 403** `Endpoint not registered`.
- Una fila con `perm_id = NULL` marca una ruta **pública**: se deja pasar sin token. Así deben registrarse `POST /auth/token` y, en desarrollo, `/docs`, `/redoc` y `/openapi.json`.
- Las requests `OPTIONS` registradas pasan sin validar credenciales.

> **Pendiente:** el catálogo inicial de rutas iba a entregarse en `migrations/20261102_enforce_endpoint_registry.sql`, pero el archivo no existe en el repositorio. Hasta que se cargue la tabla `endpoints`, una base nueva rechaza todas las requests, incluido el login.

Ejemplo de registro:

```sql
-- Ruta pública
INSERT INTO endpoints (path, perm_id) VALUES ('/auth/token', NULL);
-- Ruta protegida por el permiso 3
INSERT INTO endpoints (path, perm_id) VALUES ('/trx/all', 3);
```

## 2. Validación del JWT y del permiso requerido

Para rutas con `perm_id`:

1. Exige `Authorization: Bearer <token>` (401 si falta o está vacío).
2. Verifica firma HS256 con `JWT_SECRET_KEY` y vencimiento (401 si falla).
3. Exige los claims `perm_id`, `hierarchy` y `account_type` (`user` o `client`) (401 si faltan).
4. Compara el permiso del actor con el permiso requerido por la ruta. El acceso se concede sólo si:
   - ambos permisos existen;
   - pertenecen al mismo producto;
   - la jerarquía del token coincide con la jerarquía actual del permiso en la base;
   - la jerarquía del actor es mayor o igual a la requerida.

   Si no se cumple, responde **HTTP 403** `Permission denied`.

El payload validado queda en `request.state.auth_payload`.

Cada request se registra en la tabla `logs` (salvo las de `/logs`), incluidos los rechazos, con marcas como `no-token`, `invalid-token`, `(denied)` o `unregistered-endpoint`. Un fallo al guardar el log no interrumpe la request. Un error interno del propio middleware responde HTTP 500.

## 3. Actor y rol actuales

Las dependencias de FastAPI vuelven a cargar el actor y validan que:

- el usuario o cliente siga habilitado;
- pertenezca a la entidad incluida en el token;
- la entidad siga habilitada;
- el permiso actual coincida con `perm_id`, nivel y jerarquía del token;
- la ruta acepte ese tipo de cuenta y rol.

Dependencias disponibles:

- `get_current_user`: cualquier actor autenticado.
- `require_internal_user`: sólo usuarios internos.
- `require_client`: sólo clientes.
- `require_admin_user`: usuarios internos con nivel `admin` o `super`.

Los servicios aplican además filtros por `entity_id` y, para clientes, por `client_id`. Conocer un ID de otra entidad no concede acceso.

## Configuración

`JWT_SECRET_KEY` es obligatoria (se acepta `SECRET_KEY` como alternativa histórica). La aplicación falla de forma cerrada si no está configurada; no hay un secreto embebido en el código.

## Respuestas

| Caso | Código |
|---|---|
| Ruta no registrada en `endpoints` | 403 |
| Token faltante, inválido, vencido o con claims incompletos | 401 |
| Permiso insuficiente según la tabla `endpoints` | 403 |
| Actor deshabilitado o desincronizado con la base | 401 |
| Tipo de cuenta o rol insuficiente | 403 |
| Recurso fuera de la entidad | 404, para no revelar su existencia |
