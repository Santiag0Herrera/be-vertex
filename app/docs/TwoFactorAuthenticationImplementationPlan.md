# Plan de implementación: autenticación de dos factores (2FA)

## 1. Objetivo

Incorporar autenticación de dos factores basada en TOTP para las cuentas de
clientes. La primera versión será opcional y podrá extenderse posteriormente a
usuarios internos y administradores.

TOTP debe ser compatible con aplicaciones como Google Authenticator,
Microsoft Authenticator, Authy y gestores de contraseñas que implementen
[RFC 6238](https://www.rfc-editor.org/rfc/rfc6238).

## 2. Alcance inicial

- Activar 2FA desde el perfil del cliente autenticado.
- Enrolar un autenticador mediante un URI `otpauth://` y un código QR generado
  en el frontend.
- Confirmar el enrolamiento con un primer código TOTP válido.
- Exigir un segundo paso durante el login cuando el cliente tenga 2FA activo.
- Emitir el JWT definitivo solamente después de validar el segundo factor.
- Generar códigos de recuperación de un solo uso.
- Consultar el estado de 2FA, regenerar códigos de recuperación y desactivar
  2FA de forma segura.
- Registrar eventos relevantes sin registrar secretos ni códigos.

### Fuera del alcance inicial

- SMS o llamadas telefónicas.
- Códigos enviados por correo electrónico.
- WebAuthn/passkeys.
- Obligatoriedad de 2FA por entidad o por rol.
- Recuperación administrativa sin un proceso de verificación de identidad.

## 3. Estado actual que se debe modificar

- `app/router/auth.py` entrega el token de acceso inmediatamente después de
  validar CUIT/correo y contraseña.
- `app/services/auth_service.py` autentica clientes por CUIT y usuarios
  internos por correo electrónico.
- `app/models.py` no almacena configuración de segundo factor.
- `app/router/clients.py` ya expone operaciones autenticadas bajo
  `/clients/me`.
- El frontend consume `/auth/token` esperando siempre un JWT definitivo.

El cambio debe conservar el comportamiento actual para cuentas que no tengan
2FA habilitado.

## 4. Diseño de datos

Se recomienda una tabla separada en lugar de agregar todos los campos a
`clients`.

### `client_two_factor_auth`

| Campo | Tipo sugerido | Reglas |
| --- | --- | --- |
| `id` | INTEGER | PK |
| `client_id` | INTEGER | FK a `clients.id`, UNIQUE, NOT NULL |
| `enabled` | BOOLEAN | NOT NULL, default `false` |
| `encrypted_secret` | TEXT | Secreto TOTP cifrado; nunca almacenar en texto plano |
| `secret_key_version` | INTEGER | Permite rotar la clave de cifrado |
| `confirmed_at` | DATETIME nullable | Momento de activación |
| `last_used_time_step` | BIGINT nullable | Evita reutilizar un TOTP dentro de la misma ventana |
| `created_at` | DATETIME | NOT NULL |
| `updated_at` | DATETIME | NOT NULL |

### `client_two_factor_recovery_codes`

| Campo | Tipo sugerido | Reglas |
| --- | --- | --- |
| `id` | INTEGER | PK |
| `two_factor_auth_id` | INTEGER | FK, NOT NULL, indexado |
| `code_hash` | TEXT | Hash lento del código; nunca guardar el valor original |
| `used_at` | DATETIME nullable | Un valor indica que ya fue consumido |
| `created_at` | DATETIME | NOT NULL |

### `two_factor_login_challenges`

Permite que el token temporal de login sea de un solo uso.

| Campo | Tipo sugerido | Reglas |
| --- | --- | --- |
| `id` | INTEGER | PK |
| `challenge_id_hash` | TEXT | UNIQUE, NOT NULL |
| `client_id` | INTEGER | FK, NOT NULL, indexado |
| `expires_at` | DATETIME | NOT NULL |
| `consumed_at` | DATETIME nullable | Se completa de forma atómica al verificar |
| `attempt_count` | INTEGER | NOT NULL, default `0` |
| `created_at` | DATETIME | NOT NULL |

La migración debe crear las tablas y sus índices sin modificar cuentas
existentes. Todas las cuentas comienzan con 2FA deshabilitado.

## 5. Protección de secretos

- Crear una variable `TOTP_ENCRYPTION_KEY` independiente de
  `JWT_SECRET_KEY`.
- Cifrar el secreto TOTP con un esquema autenticado, por ejemplo AES-GCM.
- Guardar junto al ciphertext el nonce, tag y versión de clave necesarios.
- No exponer el secreto después de confirmar el enrolamiento.
- No incluir secretos, URI `otpauth`, TOTP, códigos de recuperación ni tokens
  temporales en logs.
- Los códigos de recuperación deben ser aleatorios, mostrarse una sola vez y
  almacenarse hasheados.
- Documentar un procedimiento de rotación de `TOTP_ENCRYPTION_KEY`.

## 6. Contratos de API propuestos

Todas las respuestas deben conservar el envelope utilizado actualmente por
`SuccessService` y `ErrorService`.

### Perfil del cliente

#### `GET /clients/me/two-factor`

Devuelve solamente estado no sensible:

```json
{
  "enabled": true,
  "confirmed_at": "2026-11-02T21:00:00Z",
  "recovery_codes_remaining": 7
}
```

#### `POST /clients/me/two-factor/setup`

- Requiere JWT completo de cliente.
- Requiere la contraseña actual.
- Genera o reemplaza un enrolamiento pendiente.
- Devuelve el URI `otpauth://` y una clave manual solamente en esta respuesta.
- Debe responder con `Cache-Control: no-store`.

Request:

```json
{
  "password": "contraseña-actual"
}
```

#### `POST /clients/me/two-factor/confirm`

- Recibe un TOTP del enrolamiento pendiente.
- Habilita 2FA sólo si el código es válido.
- Genera entre 8 y 10 códigos de recuperación.
- Devuelve esos códigos una sola vez.

```json
{
  "code": "123456"
}
```

#### `POST /clients/me/two-factor/recovery-codes/regenerate`

- Requiere contraseña actual y TOTP válido.
- Invalida todos los códigos anteriores.
- Devuelve los nuevos códigos una sola vez.

#### `DELETE /clients/me/two-factor`

- Requiere contraseña actual y TOTP o código de recuperación.
- Deshabilita 2FA, elimina el secreto y revoca códigos pendientes.
- Revoca desafíos de login activos.

### Login

#### `POST /auth/token`

El login actual mantiene su respuesta para cuentas sin 2FA. Para un cliente
con 2FA activo no entrega un access token completo:

```json
{
  "requires_two_factor": true,
  "challenge_token": "token-temporal",
  "expires_in": 300
}
```

El token temporal:

- expira en un máximo de 5 minutos;
- contiene un scope específico, por ejemplo `two_factor_pending`;
- no es aceptado por `get_current_user` ni por rutas de negocio;
- referencia un challenge persistido y consumible una sola vez.

#### `POST /auth/two-factor/verify`

```json
{
  "challenge_token": "token-temporal",
  "code": "123456"
}
```

- Acepta un TOTP o un código de recuperación.
- Incrementa intentos fallidos y aplica rate limiting.
- Consume el challenge de manera atómica.
- Consume el código de recuperación si corresponde.
- Emite el JWT definitivo mediante el flujo existente de `create_token`.

## 7. Validación TOTP

- Período de 30 segundos.
- Códigos de 6 dígitos.
- Aceptar como máximo una ventana anterior y una posterior para tolerar una
  desviación razonable del reloj.
- Mantener los servidores sincronizados mediante NTP.
- Rechazar la reutilización del mismo time step.
- Actualizar `last_used_time_step` y emitir el JWT en una única transacción.
- Usar comparaciones resistentes a timing cuando corresponda.

## 8. Rate limiting y bloqueo

- Limitar intentos por challenge, cuenta e IP.
- Invalidar el challenge al superar el límite.
- Responder con un mensaje genérico para no revelar si falló el TOTP o el
  código de recuperación.
- Registrar intentos fallidos sin registrar el código recibido.
- No bloquear permanentemente la cuenta por ataques automatizados; aplicar
  backoff y expiración del challenge.

## 9. Cambios de backend por archivo

### Modelos y migraciones

- `app/models.py`: agregar relaciones y modelos 2FA.
- `migrations/versions/...`: crear tablas, constraints e índices.

### Esquemas

- Crear `app/schemas/two_factor.py` con requests y responses estrictos.
- Validar TOTP con una expresión de exactamente 6 dígitos.
- Aplicar `extra='forbid'` en requests sensibles.

### Servicios

- Crear `app/services/TwoFactorService.py` para enrolamiento, cifrado,
  verificación, recuperación y consumo atómico.
- Mantener la lógica criptográfica fuera de routers.
- Extender `DBService` para exponer el nuevo servicio si se conserva ese
  patrón.

### Autenticación

- `app/router/auth.py`: devolver challenge cuando corresponda y agregar la
  verificación del segundo factor.
- `app/services/auth_service.py`: separar validación del primer factor de la
  emisión del JWT definitivo.
- Crear funciones distintas para tokens completos y tokens temporales.

### Perfil de cliente

- `app/router/clients.py`: agregar endpoints autenticados de enrolamiento,
  estado, regeneración y desactivación.

### Configuración

- Agregar `TOTP_ENCRYPTION_KEY` y una feature flag como
  `CLIENT_TWO_FACTOR_ENABLED`.
- Actualizar `README.md`, `dev.env` de ejemplo y configuración de despliegue
  sin commitear secretos reales.

## 10. Cambios requeridos en frontend

- Incorporar en `Mi perfil` el estado de 2FA y acciones para activar,
  regenerar códigos o desactivar.
- Mostrar el QR a partir del URI `otpauth://` sin enviarlo a servicios
  externos.
- Exigir confirmación del primer TOTP antes de mostrar 2FA como activo.
- Mostrar los códigos de recuperación una sola vez, con opción de copiar o
  descargar.
- Adaptar el login para reconocer `requires_two_factor` y mostrar un segundo
  paso.
- No guardar el challenge token en `localStorage`; mantenerlo en memoria o en
  almacenamiento de sesión con expiración corta.
- Permitir ingresar código de recuperación desde el segundo paso.
- Evitar revelar si una cuenta tiene 2FA antes de validar correctamente la
  contraseña.

## 11. Auditoría y observabilidad

Registrar eventos con actor, fecha, entidad, IP y request ID:

- inicio y confirmación de enrolamiento;
- cancelación o reemplazo de enrolamiento pendiente;
- verificación exitosa y fallida;
- uso de código de recuperación;
- regeneración de códigos;
- desactivación de 2FA;
- bloqueo o expiración de challenge.

Los logs nunca deben incluir el secreto, el URI, un TOTP, un código de
recuperación ni tokens completos.

## 12. Estrategia de pruebas

### Unitarias

- Generación y cifrado/descifrado de secretos.
- Validación de TOTP actual, anterior y posterior.
- Rechazo de códigos vencidos, mal formados y reutilizados.
- Hash y consumo único de recovery codes.
- Expiración, límite de intentos y consumo único de challenges.

### Integración

- Login sin 2FA conserva la respuesta actual.
- Login con 2FA no entrega JWT completo en el primer paso.
- TOTP válido entrega el JWT definitivo.
- TOTP inválido no entrega sesión.
- Un challenge consumido no puede reutilizarse.
- Un recovery code consumido no puede reutilizarse.
- Un cliente no puede leer ni modificar la configuración de otro cliente.
- Un token temporal no accede a endpoints protegidos.
- Deshabilitar una cuenta o entidad invalida también el flujo 2FA.

### End-to-end

- Activar 2FA desde el perfil escaneando el QR.
- Cerrar sesión y completar login en dos pasos.
- Ingresar mediante un recovery code.
- Regenerar recovery codes y comprobar que los anteriores fallan.
- Desactivar 2FA y comprobar el retorno al login de un solo paso.

## 13. Despliegue gradual

1. Incorporar migraciones y configuración con la feature flag apagada.
2. Desplegar backend compatible con login tradicional y nuevo contrato.
3. Desplegar frontend capaz de manejar ambas respuestas.
4. Activar la feature flag en desarrollo y staging.
5. Ejecutar pruebas end-to-end con relojes sincronizados.
6. Habilitar 2FA opcional para un grupo reducido de clientes.
7. Monitorear errores, intentos fallidos y recuperaciones.
8. Habilitarlo para todos los clientes.

El rollback debe permitir apagar la feature flag sin borrar configuraciones ya
confirmadas. Mientras la flag esté apagada, se debe definir explícitamente si
el login ignora temporalmente 2FA o se bloquea; para producción se recomienda
no degradar silenciosamente la seguridad de cuentas ya enroladas.

## 14. Criterios de aceptación

- Una cuenta sin 2FA inicia sesión sin cambios visibles.
- Una cuenta con 2FA no obtiene un JWT completo sólo con su contraseña.
- El secreto TOTP nunca se almacena en texto plano ni aparece en logs.
- El enrolamiento no se activa hasta confirmar un TOTP válido.
- Los challenges y recovery codes son de un solo uso.
- Existe rate limiting para verificación y enrolamiento.
- El cliente puede consultar estado, regenerar recuperación y desactivar 2FA
  con reautenticación.
- Todas las fronteras de entidad y tipo de cuenta tienen pruebas automáticas.
- El flujo completo funciona en los modos claro y oscuro del frontend.

## 15. Estimación y fases sugeridas

### Fase 1: base segura de backend (1–2 días)

- migraciones;
- cifrado y servicio TOTP;
- enrolamiento y estado;
- pruebas unitarias.

### Fase 2: login en dos pasos (1–2 días)

- challenge temporal de un solo uso;
- verificación y emisión de JWT;
- rate limiting;
- pruebas de integración.

### Fase 3: frontend y recuperación (1–2 días)

- QR y confirmación;
- segundo paso del login;
- recovery codes;
- pruebas end-to-end y pulido de UX.

Estimación total orientativa: 3–5 días para una implementación completa,
probada y preparada para despliegue gradual.

## 16. Decisiones pendientes antes de implementar

- Confirmar si el alcance inicial es sólo clientes o también usuarios
  internos.
- Definir proveedor y ubicación del rate limiting.
- Definir dónde se administra `TOTP_ENCRYPTION_KEY` en cada entorno.
- Definir el proceso operativo de recuperación cuando se pierden autenticador
  y recovery codes.
- Decidir si una entidad podrá exigir 2FA a todos sus clientes en una fase
  posterior.
- Definir la política de sesiones existentes al activar o desactivar 2FA.

## Referencias

- [RFC 6238: TOTP](https://www.rfc-editor.org/rfc/rfc6238)
- [OWASP Multifactor Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html)
