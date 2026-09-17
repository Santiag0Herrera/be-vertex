# Autenticación y autorización

La autorización tiene dos capas complementarias.

## 1. Validación global del JWT

`PermissionMiddleware` exige `Authorization: Bearer <token>` para toda ruta salvo:

- `POST /auth/token`
- `/docs`
- `/openapi.json`
- `/redoc`

El middleware verifica la firma HS256 con `JWT_SECRET_KEY`, el vencimiento y los claims mínimos `perm_id`, `hierarchy` y `account_type`. También registra la request en la tabla de auditoría. Un fallo del registro no interrumpe la request.

El middleware no decide permisos por URL ni consulta la tabla `endpoints`.

## 2. Actor y permiso actuales

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

Los servicios aplican además filtros por `entity_id` y, para clientes, por `client_id`. De este modo, conocer un ID de otra entidad no concede acceso.

## Configuración

`JWT_SECRET_KEY` es obligatoria. La aplicación falla de forma cerrada si no está configurada; no existe un secreto embebido en el código.

## Respuestas

- Token faltante, inválido, vencido o desincronizado con la base: HTTP 401.
- Tipo de cuenta o rol insuficiente: HTTP 403.
- Recurso fuera de la entidad: HTTP 404, para no revelar su existencia.
