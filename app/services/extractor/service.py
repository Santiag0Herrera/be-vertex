from __future__ import annotations

import logging
from time import perf_counter

from fastapi import HTTPException, UploadFile

from app.services.extractor.builder import build_document_response
from app.services.extractor.gemini_client import (
    GeminiExtractionError,
    extract_document_fields,
)
from app.services.extractor.models import DocumentExtractResponse, ExtractedField
from app.services.ReceiptIdentityService import (
    build_receipt_fingerprint,
    file_sha256,
)


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
}

MAX_DOCUMENT_FILE_SIZE = 10 * 1024 * 1024
GEMINI_FIELD_KEYS = {
    "amount": "importe",
    "trx_id": "numero de transaccion",
    "emisor_name": "nombre originante",
    "emisor_cuit": "cuit originante",
    "emisor_cbu": "cbu origen",
    "receptor_name": "nombre destinatario",
    "receptor_cuit": "cuit destinatario",
    "receptor_cbu": "cbu destino",
    "date": "fecha",
}
logger = logging.getLogger(__name__)


async def extract_document_from_file(
    file: UploadFile,
    request_id: str = "unknown",
) -> DocumentExtractResponse:
    started_at = perf_counter()
    filename = file.filename or "unnamed"
    logger.info(
        "Extractor started request_id=%s filename=%s content_type=%s",
        request_id,
        filename,
        file.content_type,
    )
    outcome = "success"

    try:
        validate_file_metadata(file)

        original_data = await file.read()
        validate_file_data(original_data)
        content_sha256 = file_sha256(original_data)

        gemini_result = await call_gemini_or_raise(
            original_data,
            content_type=file.content_type,
            request_id=request_id,
        )
        fields = gemini_fields(gemini_result.model_dump())
        result = attach_document_identity(
            build_document_response(fields),
            filename,
            content_sha256,
        )
        outcome = "success" if result.ok else "incomplete"
        return result
    except HTTPException as exc:
        outcome = f"http_{exc.status_code}"
        raise
    except Exception:
        outcome = "unhandled_error"
        logger.exception(
            "Extractor unhandled error request_id=%s filename=%s",
            request_id,
            filename,
        )
        raise
    finally:
        logger.info(
            "Extractor finished request_id=%s filename=%s outcome=%s duration_ms=%s",
            request_id,
            filename,
            outcome,
            round((perf_counter() - started_at) * 1000),
        )


def validate_file_metadata(file: UploadFile) -> None:
    if not file.content_type:
        raise HTTPException(status_code=400, detail="Missing content_type")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content_type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )


def attach_document_identity(
    result: DocumentExtractResponse,
    filename: str | None,
    content_sha256: str,
) -> DocumentExtractResponse:
    document_name = filename or "unnamed"
    result.partial["document_name"] = document_name
    result.partial["file_sha256"] = content_sha256
    if result.document:
        result.document.document_name = document_name
        result.document.file_sha256 = content_sha256
        receipt_fingerprint = build_receipt_fingerprint(result.document)
        result.document.receipt_fingerprint = receipt_fingerprint
        result.partial["receipt_fingerprint"] = receipt_fingerprint
    return result


def validate_file_data(data: bytes) -> None:
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(data) > MAX_DOCUMENT_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large for Gemini extraction (max 10MB)",
        )


def gemini_fields(payload: dict) -> list[ExtractedField]:
    return [
        ExtractedField(
            key=GEMINI_FIELD_KEYS[field_name],
            value=str(value),
            confidence=None,
        )
        for field_name, value in payload.items()
        if field_name in GEMINI_FIELD_KEYS and value not in (None, "")
    ]


async def call_gemini_or_raise(
    data: bytes,
    *,
    content_type: str,
    request_id: str = "unknown",
):
    try:
        return await extract_document_fields(
            data=data,
            content_type=content_type,
            required_fields={
                "amount",
                "trx_id",
                "emisor_cuit",
                "receptor_cuit",
                "date",
            },
            request_id=request_id,
        )
    except GeminiExtractionError as exc:
        logger.error(
            "Gemini extraction failed request_id=%s reason=%s status_code=%s "
            "retry_after=%s model=%s",
            request_id,
            exc.reason,
            exc.status_code or "none",
            exc.retry_after or "none",
            exc.model or "unknown",
        )
        if exc.reason == "not_configured":
            raise HTTPException(
                status_code=503,
                detail="Gemini is not configured.",
            ) from exc
        if exc.reason == "payment_required":
            raise HTTPException(
                status_code=402,
                detail="Gemini billing is not enabled for the configured project.",
            ) from exc
        if exc.reason in {"quota_exceeded", "rate_limited"}:
            raise HTTPException(
                status_code=429,
                detail="Gemini quota is temporarily unavailable. Please retry this file.",
            ) from exc
        if exc.reason == "timeout":
            raise HTTPException(
                status_code=504,
                detail="Gemini did not respond in time. Please retry this file.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"Gemini could not process the document ({exc.reason}).",
        ) from exc
