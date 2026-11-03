from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import (
    HTTP_403_FORBIDDEN,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from starlette.routing import Match
from app.db.database import SessionLocal
from app.models import Endpoints, Logs, Permission
from app.services.auth_service import decode_access_token
from datetime import datetime
import logging

logger = logging.getLogger("vertex.auth")


def _registered_path(request: Request) -> str:
    """Resolve concrete URLs to the route template stored in endpoints."""
    partial_match = None
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return route.path
        if match == Match.PARTIAL and partial_match is None:
            partial_match = route.path
    return partial_match or request.url.path

class PermissionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        db = SessionLocal()
        downstream_started = False
        try:
            path = request.url.path
            registered_path = _registered_path(request)
            method = request.method

            endpoint = db.query(Endpoints).filter(
                Endpoints.path == registered_path
            ).first()
            if endpoint is None:
                logger.warning(
                    "Endpoint is not registered",
                    extra={
                        "event": "auth_failed",
                        "reason": "endpoint_not_registered",
                        "path": path,
                        "registered_path": registered_path,
                        "method": method,
                    },
                )
                _save_log(path, method, user="unregistered-endpoint")
                return JSONResponse(
                    status_code=HTTP_403_FORBIDDEN,
                    content={"detail": "Endpoint not registered"},
                )

            # CORS preflight is still checked against the endpoint registry,
            # but does not carry user credentials.
            if method == "OPTIONS":
                db.close()
                downstream_started = True
                return await call_next(request)

            # A NULL permission marks an explicitly registered public route.
            if endpoint.perm_id is None:
                _save_log(path, method, user="anonymous")
                db.close()
                downstream_started = True
                return await call_next(request)

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
                payload = decode_access_token(token)
            except Exception:
                logger.warning(
                    "JWT validation failed",
                    extra={"event": "auth_failed", "reason": "invalid_token", "path": path},
                )
                _save_log(path, method, user="invalid-token")
                return JSONResponse(status_code=HTTP_401_UNAUTHORIZED, content={"detail": "Invalid token"})

            perm_id = payload.get("perm_id")
            user_hierarchy = payload.get("hierarchy")
            user_email = payload.get("sub") or "unknown"
            if (
                perm_id is None
                or user_hierarchy is None
                or payload.get("account_type") not in {"user", "client"}
            ):
                _save_log(path, method, user=f"{user_email} (missing-claims)")
                return JSONResponse(
                    status_code=HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing permission or hierarchy in token"}
                )

            actor_permission = db.query(Permission).filter(
                Permission.id == perm_id
            ).first()
            required_permission = db.query(Permission).filter(
                Permission.id == endpoint.perm_id
            ).first()
            has_access = (
                actor_permission is not None
                and required_permission is not None
                and actor_permission.product == required_permission.product
                and actor_permission.hierarchy == user_hierarchy
                and actor_permission.hierarchy >= required_permission.hierarchy
            )
            if not has_access:
                logger.warning(
                    "Permission denied",
                    extra={
                        "event": "auth_failed",
                        "reason": "permission_denied",
                        "path": path,
                        "registered_path": registered_path,
                        "perm_id": perm_id,
                        "required_perm_id": endpoint.perm_id,
                    },
                )
                _save_log(path, method, user=f"{user_email} (denied)")
                return JSONResponse(
                    status_code=HTTP_403_FORBIDDEN,
                    content={"detail": "Permission denied"},
                )

            request.state.auth_payload = payload
            db.close()
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
      except Exception:
          # No bloqueamos la request por un error de logging
          logger.exception("Failed to persist request log", extra={"event": "audit_log_failed"})
      finally:
          db.close()
