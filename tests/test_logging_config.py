import json
import logging

from app.logging_config import JsonFormatter, request_id_context


def test_json_formatter_exposes_structured_fields():
    token = request_id_context.set("request-123")
    try:
        record = logging.LogRecord(
            name="vertex.http",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="HTTP request completed",
            args=(),
            exc_info=None,
        )
        record.event = "http_request_completed"
        record.method = "GET"
        record.path = "/clients/all"
        record.status_code = 200
        record.duration_ms = 42

        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert payload["event"] == "http_request_completed"
    assert payload["request_id"] == "request-123"
    assert payload["method"] == "GET"
    assert payload["path"] == "/clients/all"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 42
