from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from fastapi import HTTPException

from app.services.extractor import service


def make_client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "AWS error"}},
        operation_name="AnalyzeDocument",
    )


@pytest.mark.asyncio
async def test_transient_textract_error_returns_429(monkeypatch):
    monkeypatch.setattr(
        service,
        "analyze_document_bytes",
        AsyncMock(side_effect=make_client_error("ThrottlingException")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.call_textract_or_raise(b"document", request_id="test-request")

    assert exc_info.value.status_code == 429
    assert "temporarily busy" in exc_info.value.detail


@pytest.mark.asyncio
async def test_textract_timeout_returns_504(monkeypatch):
    monkeypatch.setattr(
        service,
        "analyze_document_bytes",
        AsyncMock(
            side_effect=ReadTimeoutError(
                endpoint_url="https://textract.us-east-1.amazonaws.com"
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.call_textract_or_raise(b"document", request_id="test-request")

    assert exc_info.value.status_code == 504
    assert "did not respond in time" in exc_info.value.detail


@pytest.mark.asyncio
async def test_non_transient_textract_error_returns_502(monkeypatch):
    monkeypatch.setattr(
        service,
        "analyze_document_bytes",
        AsyncMock(side_effect=make_client_error("InvalidParameterException")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.call_textract_or_raise(b"document", request_id="test-request")

    assert exc_info.value.status_code == 502
    assert "InvalidParameterException" in exc_info.value.detail
