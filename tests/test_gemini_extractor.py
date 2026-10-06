from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.services.extractor import service
from app.services.extractor.gemini_client import GeminiExtractionError
from app.services.extractor.gemini_models import GeminiDocumentFields


def upload_file(content_type: str = "image/jpeg") -> UploadFile:
    return UploadFile(
        file=BytesIO(b"receipt-bytes"),
        filename="comprobante.jpg",
        headers=Headers({"content-type": content_type}),
    )


def complete_gemini_result() -> GeminiDocumentFields:
    return GeminiDocumentFields(
        amount="33.00",
        trx_id="179712727732",
        emisor_name=None,
        emisor_cuit="30714376809",
        emisor_cbu=None,
        receptor_name=None,
        receptor_cuit="20327213548",
        receptor_cbu="0170043520000005091629",
        date="2026-09-18",
    )


@pytest.mark.asyncio
async def test_extractor_uses_gemini_as_the_only_extraction_provider(monkeypatch):
    extract_mock = AsyncMock(return_value=complete_gemini_result())
    monkeypatch.setattr(service, "extract_document_fields", extract_mock)

    result = await service.extract_document_from_file(
        upload_file(),
        request_id="gemini-only",
    )

    assert result.ok is True
    assert result.document is not None
    assert result.document.trx_id == "179712727732"
    assert result.document.emisor_cuit == "30714376809"
    assert result.document.receptor_cuit == "20327213548"
    assert result.document.file_sha256
    assert result.document.receipt_fingerprint
    assert result.missing == []
    extract_mock.assert_awaited_once()
    assert extract_mock.await_args.kwargs["content_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_pdf_is_sent_directly_to_gemini(monkeypatch):
    extract_mock = AsyncMock(return_value=complete_gemini_result())
    monkeypatch.setattr(service, "extract_document_fields", extract_mock)

    await service.extract_document_from_file(
        upload_file("application/pdf"),
        request_id="gemini-pdf",
    )

    assert extract_mock.await_args.kwargs["data"] == b"receipt-bytes"
    assert extract_mock.await_args.kwargs["content_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_payment_required_is_returned_as_an_http_error(monkeypatch):
    monkeypatch.setattr(
        service,
        "extract_document_fields",
        AsyncMock(
            side_effect=GeminiExtractionError(
                "payment_required",
                status_code=402,
                model="gemini-flash-latest",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.extract_document_from_file(
            upload_file(),
            request_id="gemini-payment",
        )

    assert exc_info.value.status_code == 402
    assert "billing" in exc_info.value.detail.lower()
