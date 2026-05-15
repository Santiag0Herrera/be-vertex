from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile

from app.services.extractor.aws_client import analyze_document_bytes
from app.services.extractor.builder import build_document_response
from app.services.extractor.extractors import (
    extract_fields_from_wallet_lines,
    extract_kv_pairs_from_forms,
    extract_pairs_from_lines,
    merge_and_dedup_fields,
)
from app.services.extractor.heuristics import extract_datetime_from_filename
from app.services.extractor.models import DocumentExtractResponse, ExtractedField, ParseIssue
from app.services.extractor.pdf_converter import convert_first_pdf_page_to_png


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
}

MAX_SYNC_TEXTRACT_FILE_SIZE = 10 * 1024 * 1024


async def extract_document_from_file(file: UploadFile) -> DocumentExtractResponse:
    validate_file_metadata(file)

    data = await file.read()
    validate_file_data(data)

    if file.content_type == "application/pdf":
        data = convert_pdf_or_raise(data)

    aws_response = await call_textract_or_raise(data)

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

    if not fields:
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial={},
            missing=[],
            errors=[ParseIssue(field="*", message="No fields extracted from Textract response")],
            raw_fields=[],
        )

    return build_document_response(fields)


def validate_file_metadata(file: UploadFile) -> None:
    if not file.content_type:
        raise HTTPException(status_code=400, detail="Missing content_type")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content_type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )


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


async def call_textract_or_raise(data: bytes):
    try:
        return await analyze_document_bytes(data)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Textract error: {str(exc)}") from exc
