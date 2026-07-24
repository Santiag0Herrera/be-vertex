from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.schemas.transactions import DocumentRequest
from app.services.extractor.builder import REQUIRED_FOR_DOCUMENT
from app.services.extractor.gemini_client import (
    GeminiFallbackError,
    extract_document_fields,
    is_gemini_configured,
)
from app.services.extractor.models import DocumentExtractResponse, ExtractedField, ParseIssue


FIELD_KEYS = {
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


async def recover_missing_fields(
    original_data: bytes,
    content_type: str,
    textract_result: DocumentExtractResponse,
    request_id: str = "unknown",
) -> list[ExtractedField]:
    if textract_result.ok or not is_gemini_configured():
        return []

    recoverable_fields = get_invalid_or_missing_fields(textract_result.partial)
    if not recoverable_fields:
        return []

    try:
        gemini_result = await extract_document_fields(
            data=original_data,
            content_type=content_type,
            partial=textract_result.partial,
            required_fields=recoverable_fields,
            request_id=request_id,
        )
    except GeminiFallbackError as exc:
        logger.warning(
            "Gemini fallback failed request_id=%s error=%s",
            request_id,
            exc,
        )
        textract_result.errors.append(
            ParseIssue(field="gemini", message="Unable to recover missing fields")
        )
        return []

    recovered_fields: list[ExtractedField] = []
    recovered_payload = gemini_result.model_dump()

    for field_name in recoverable_fields:
        value = recovered_payload.get(field_name)
        if value in (None, ""):
            continue

        recovered_fields.append(
            ExtractedField(
                key=FIELD_KEYS[field_name],
                value=str(value),
                confidence=1000.0,
            )
        )

    logger.info(
        "Gemini fallback completed request_id=%s requested_fields=%s recovered_fields=%s",
        request_id,
        sorted(recoverable_fields),
        sorted(
            field_name
            for field_name in recoverable_fields
            if recovered_payload.get(field_name) not in (None, "")
        ),
    )
    return recovered_fields


def get_invalid_or_missing_fields(partial: dict[str, Any]) -> set[str]:
    invalid_fields = REQUIRED_FOR_DOCUMENT.difference(partial)

    try:
        DocumentRequest.model_validate(partial)
    except ValidationError as exc:
        invalid_fields.update(
            str(error["loc"][0])
            for error in exc.errors()
            if error.get("loc") and str(error["loc"][0]) in REQUIRED_FOR_DOCUMENT
        )

    return invalid_fields
