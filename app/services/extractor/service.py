from __future__ import annotations

import logging
from time import perf_counter

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from fastapi import HTTPException, UploadFile

from app.services.extractor.aws_client import (
    TRANSIENT_TEXTRACT_ERROR_CODES,
    analyze_document_bytes,
    get_client_error_code,
)
from app.services.extractor.builder import build_document_response
from app.services.extractor.extractors import (
    extract_fields_from_wallet_lines,
    extract_kv_pairs_from_forms,
    extract_pairs_from_lines,
    merge_and_dedup_fields,
)
from app.services.extractor.gemini_fallback import recover_missing_fields
from app.services.extractor.heuristics import extract_datetime_from_filename
from app.services.extractor.models import DocumentExtractResponse, ExtractedField
from app.services.extractor.pdf_converter import convert_first_pdf_page_to_png


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
}

MAX_SYNC_TEXTRACT_FILE_SIZE = 10 * 1024 * 1024
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

        textract_data = original_data
        if file.content_type == "application/pdf":
            textract_data = convert_pdf_or_raise(original_data)

        aws_response = await call_textract_or_raise(textract_data, request_id=request_id)

        fields = merge_and_dedup_fields(
            extract_kv_pairs_from_forms(aws_response),
            extract_pairs_from_lines(aws_response),
            extract_fields_from_wallet_lines(aws_response),
        )

        filename_datetime = extract_datetime_from_filename(file.filename)
        if filename_datetime:
            fields.append(
                ExtractedField(
                    key="fecha archivo",
                    value=filename_datetime,
                    confidence=999.0,
                )
            )

        textract_result = build_document_response(fields)
        if textract_result.ok:
            return attach_document_name(textract_result, filename)

        gemini_fields = await recover_missing_fields(
            original_data=original_data,
            content_type=file.content_type,
            textract_result=textract_result,
            request_id=request_id,
        )
        if not gemini_fields:
            return attach_document_name(textract_result, filename)

        result = build_document_response(merge_and_dedup_fields(fields, gemini_fields))
        return attach_document_name(result, filename)
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


def attach_document_name(
    result: DocumentExtractResponse,
    filename: str | None,
) -> DocumentExtractResponse:
    document_name = filename or "unnamed"
    result.partial["document_name"] = document_name
    if result.document:
        result.document.document_name = document_name
    return result


def validate_file_data(data: bytes) -> None:
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(data) > MAX_SYNC_TEXTRACT_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large for synchronous Textract (max 10MB)",
        )


def convert_pdf_or_raise(data: bytes) -> bytes:
    try:
        return convert_first_pdf_page_to_png(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PDF conversion failed: {str(exc)}") from exc


async def call_textract_or_raise(data: bytes, request_id: str = "unknown"):
    try:
        return await analyze_document_bytes(data, request_id=request_id)
    except ClientError as exc:
        error_code = get_client_error_code(exc)
        logger.error(
            "Textract client error request_id=%s error_code=%s",
            request_id,
            error_code,
        )
        if error_code in TRANSIENT_TEXTRACT_ERROR_CODES:
            raise HTTPException(
                status_code=429,
                detail="Textract is temporarily busy. Please retry this file.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"Textract rejected the document ({error_code}).",
        ) from exc
    except (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError) as exc:
        logger.error("Textract timeout request_id=%s error=%s", request_id, exc)
        raise HTTPException(
            status_code=504,
            detail="Textract did not respond in time. Please retry this file.",
        ) from exc
    except BotoCoreError as exc:
        logger.error("Textract SDK error request_id=%s error=%s", request_id, exc)
        raise HTTPException(
            status_code=502,
            detail="Unable to process the document with Textract.",
        ) from exc
