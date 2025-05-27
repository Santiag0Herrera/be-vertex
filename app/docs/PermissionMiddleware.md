
# 🛡️ Middleware: `PermissionMiddleware`

## 📄 Description
This middleware ensures that authenticated users have the correct permissions to access specific API routes. It uses JWT tokens to identify the user and their hierarchy level, then checks the database to determine if access is authorized.

## 🧠 How It Works

1. Intercepts each incoming HTTP request.
2. Allows direct access to public paths (e.g., `/auth/`, `/docs`).
3. Validates the presence and format of the JWT token in the `Authorization` header.
4. Decodes the token using a `SECRET_KEY` and the `HS256` algorithm.
5. Extracts `perm_id` and `hierarchy` from the token payload.
6. Queries the database to verify if the user has sufficient permissions.
7. Grants or denies access accordingly.

## 🔐 Validations

- **JWT Token**:
  - Must be present and properly formatted (`Bearer <token>`).
  - Must be successfully decoded.
  - Must contain `perm_id` and `hierarchy`.

- **Permissions and Hierarchy**:
  - Checks the `Endpoints` table joined with `Permission`.
  - User's `hierarchy` must be greater than or equal to the required value for the requested path.

## ⚠️ Error Handling

| Status Code | Cause                               | Description                          |
|-------------|--------------------------------------|--------------------------------------|
| 403         | Missing token, access denied, error | Access denied or internal failure    |
| 401         | Invalid token or missing fields     | Authentication failure               |

### Logging
Uses the `logging` module to track key events:

- `INFO`: Incoming requests and valid tokens.
- `WARNING`: Missing authentication or insufficient permissions.
- `ERROR`: Decoding issues or general exceptions.

## 🔓 Public Paths Exempted

```python
public_paths = [
  "/auth/", "/auth/token", "/docs",
  "/openapi.json", "/redoc"
]
```

These paths bypass token validation and permission checks.

## 🛠️ Requirements

- Dependencies:
  - `fastapi`, `starlette`, `jose`, `sqlalchemy`
- Models required:
  - `Endpoints`, `Permission`
- Database:
  - `SessionLocal` from `db.database`

## 🧪 Example of Expected Token

```json
{
  "perm_id": 3,
  "hierarchy": 2,
  "exp": 1716982112
}
```

## 🧹 Best Practices

- Periodically rotate the `SECRET_KEY`.
- Implement token expiration and renewal handling.
- Maintain well-defined permission hierarchies for clean access control.
