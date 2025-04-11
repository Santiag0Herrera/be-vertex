from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_403_FORBIDDEN, HTTP_401_UNAUTHORIZED
from jose import jwt, JWTError
from db.database import SessionLocal
from models import Endpoints, Permission
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
            logging.info(f"🔒 Incoming request to: {path}")

            # Paths públicos (sin auth)
            public_paths = ["/auth/", "/auth/token", "/docs", "/openapi.json", "/redoc"]
            if any(path.startswith(p) for p in public_paths):
                return await call_next(request)

            # Verificar token
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                logging.warning("❌ No Authorization header")
                return JSONResponse(
                    status_code=HTTP_403_FORBIDDEN,
                    content={"detail": "No token provided"}
                )

            token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                logging.info(f"✅ Token payload")
            except JWTError as e:
                logging.error(f"❌ JWT decoding error: {e}")
                return JSONResponse(
                    status_code=HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid token"}
                )

            perm_id = payload.get("perm_id")
            user_hierarchy = payload.get("hierarchy")
            if perm_id is None or user_hierarchy is None:
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
                return JSONResponse(
                    status_code=HTTP_403_FORBIDDEN,
                    content={"detail": "Permission denied"}
                )

            return await call_next(request)

        except Exception as e:
            logging.error(f"🔥 Middleware error: {e}")
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={"detail": f"Middleware failed: {str(e)}"}
            )
        finally:
            db.close()