from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_403_FORBIDDEN, HTTP_401_UNAUTHORIZED
from jose import jwt, JWTError
from app.db.database import SessionLocal
from app.models import Endpoints, Permission, Logs
from datetime import datetime
import logging

# Setup básico de logging
logging.basicConfig(level=logging.INFO)

SECRET_KEY = 'bf75bf97eb8839552b6d64790c35fdecbe8874bd1791917b650494d3d54c60b5'
ALGORITHM = "HS256"

class PermissionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        db = SessionLocal()
        try:
            path = request.url.path
            method = request.method
            logging.info(f"🔒 Incoming request to: {path}")

            public_paths = ["/auth/", "/auth/token", "/docs", "/openapi.json", "/redoc"]
            if any(path.startswith(p) for p in public_paths):
                # Log para rutas públicas (usuario anónimo)
                _save_log(path, method, user="anonymous")
                return await call_next(request)

            # Verificar token
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                logging.warning("❌ No Authorization header")
                _save_log(path, method, user="no-token")
                return JSONResponse(status_code=HTTP_403_FORBIDDEN, content={"detail": "No token provided"})

            token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                logging.info("✅ Token payload")
            except JWTError as e:
                logging.error(f"❌ JWT decoding error: {e}")
                _save_log(path, method, user="invalid-token")
                return JSONResponse(status_code=HTTP_403_FORBIDDEN, content={"detail": "Invalid token"})

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
                logging.warning(f"⛔ Access denied for perm_id={perm_id} to path={path}")
                _save_log(path, method, user=f"{user_email} (denied)")
                return JSONResponse(status_code=HTTP_401_UNAUTHORIZED, content={"detail": "Permission denied"})

            # Request autorizada: llamamos la ruta y logeamos con status
            response = await call_next(request)
            _save_log(path, method, user=user_email)
            return response

        except Exception as e:
            logging.error(f"🔥 Middleware error: {e}")
            # Logueamos el fallo del middleware también
            try:
                _save_log(request.url.path, request.method, user="middleware-error")
            except Exception:
                pass
            return JSONResponse(status_code=HTTP_403_FORBIDDEN, content={"detail": f"Middleware failed: {str(e)}"})
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
          logging.error(f"⚠️ Failed to write log: {e}")