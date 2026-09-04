from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import request_id_context


logger = logging.getLogger("vertex.http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started_at = perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            logger.exception(
                "Unhandled request error",
                extra={
                    "event": "http_request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                },
            )
            raise
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000)
            log_method = logger.error if status_code >= 500 else logger.info
            log_method(
                "HTTP request completed",
                extra={
                    "event": "http_request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else None,
                },
            )
            request_id_context.reset(context_token)
