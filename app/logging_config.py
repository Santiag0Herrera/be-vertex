from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")

STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }

        for key, value in record.__dict__.items():
            if key in STANDARD_LOG_RECORD_FIELDS or key.startswith("_") or key in payload:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": "app.logging_config.JsonFormatter"}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["console"], "level": "INFO"},
        }
    )
