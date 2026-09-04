from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import (
    HTTP_403_FORBIDDEN,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from jose import jwt, JWTError
from app.db.database import SessionLocal
from app.models import Endpoints, Permission, Logs
from datetime import datetime
import logging

logger = logging.getLogger("vertex.auth")

SECRET_KEY = 'bf75bf97eb8839552b6d64790c35fdecbe8874bd1791917b650494d3d54c60b5'
ALGORITHM = "HS256"

class PermissionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        db = SessionLocal()
        downstream_started = False
        try:
            path = request.url.path
            method = request.method
            public_paths = ["/auth/", "/auth/token", "/docs", "/openapi.json", "/redoc"]
            if any(path.startswith(p) for p in public_paths):
                # Log para rutas públicas (usuario anónimo)
                _save_log(path, method, user="anonymous")
                return await call_next(request)

            # Verificar token
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                logger.warning(
                    "Authorization header missing",
                    extra={"event": "auth_failed", "reason": "missing_header", "path": path},
                )
                _save_log(path, method, user="no-token")
                return JSONResponse(status_code=HTTP_401_UNAUTHORIZED, content={"detail": "No token provided"})

            token = auth_header.removeprefix("Bearer ").strip()
            if not token:
                logger.warning(
                    "Bearer token empty",
                    extra={"event": "auth_failed", "reason": "empty_token", "path": path},
                )
                _save_log(path, method, user="no-token")
                return JSONResponse(
                    status_code=HTTP_401_UNAUTHORIZED,
                    content={"detail": "No token provided"},
                )
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            except JWTError as e:
                logger.warning(
                    "JWT validation failed",
                    extra={"event": "auth_failed", "reason": "invalid_token", "path": path},
                )
                _save_log(path, method, user="invalid-token")
                return JSONResponse(status_code=HTTP_401_UNAUTHORIZED, content={"detail": "Invalid token"})

            perm_id = payload.get("perm_id")
            user_hierarchy = payload.get("hierarchy")
            user_email = payload.get("sub") or "unknown"
            if perm_id is None or user_hierarchy is None:
                _save_log(path, method, user=f"{user_email} (missing-claims)")
                return JSONResponse(
                    status_code=HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing permission or hierarchy in token"}
                )

            # Validar jerarquía
            has_access = (
                db.query(Endpoints)
                .join(Permission, Endpoints.perm_id == Permission.id)
                .filter(
                    Endpoints.path == path,
                    Permission.hierarchy <= user_hierarchy
                )
                .first()
            )

            if not has_access:
                logger.warning(
                    "Permission denied",
                    extra={
                        "event": "auth_failed",
                        "reason": "permission_denied",
                        "path": path,
                        "perm_id": perm_id,
                    },
                )
                _save_log(path, method, user=f"{user_email} (denied)")
                return JSONResponse(status_code=HTTP_403_FORBIDDEN, content={"detail": "Permission denied"})

            # Request autorizada: llamamos la ruta y logeamos con status
            downstream_started = True
            response = await call_next(request)
            _save_log(path, method, user=user_email)
            return response

        except Exception as e:
            if downstream_started:
                logger.exception("Downstream route error", extra={"event": "downstream_error"})
                raise

            logger.exception("Permission middleware error", extra={"event": "middleware_error"})
            # Logueamos el fallo del middleware también
            try:
                _save_log(request.url.path, request.method, user="middleware-error")
            except Exception:
                pass
            return JSONResponse(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal authentication middleware error"},
            )
        finally:
            db.close()

def _save_log(endpoint: str, method: str, user: str):
    db = SessionLocal()
    if not endpoint.startswith("/logs"):  # Evitar loguear las propias llamadas al endpoint de logs
      try:
          log = Logs(
              datetime=datetime.utcnow().isoformat(),
              endpoint=endpoint,
              method=method,
              username=user
          )
          db.add(log)
          db.commit()
      except Exception as e:
          # No bloqueamos la request por un error de logging
          logger.exception("Failed to persist request log", extra={"event": "audit_log_failed"})
      finally:
          db.close()
