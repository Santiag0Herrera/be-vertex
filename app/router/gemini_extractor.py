from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.auth_service import get_current_user
from app.services.extractor.models import DocumentExtractResponse
from app.services.extractor.service import extract_document_from_file
from app.services.ReceiptIdentityService import duplicate_payload, find_duplicate_receipt


router = APIRouter(prefix="/extractorV2", tags=["Gemini"])
user_dependency = Annotated[dict, Depends(get_current_user)]
db_dependency = Annotated[Session, Depends(get_db)]
logger = logging.getLogger("vertex.receipts")


@router.post("/extract", response_model=DocumentExtractResponse)
@router.post(
    "/aws-extract",
    response_model=DocumentExtractResponse,
    include_in_schema=False,
)
async def analyze_document(
    request: Request,
    response: Response,
    user: user_dependency,
    db: db_dependency,
    file: UploadFile = File(...),
) -> DocumentExtractResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    response.headers["X-Request-ID"] = request_id
    result = await extract_document_from_file(file, request_id=request_id)
    document = result.document
    duplicate, matched_by = find_duplicate_receipt(
        db,
        entity_id=user["entity_id"],
        content_sha256=(
            document.file_sha256
            if document
            else result.partial.get("file_sha256")
        ),
        receipt_fingerprint=(
            document.receipt_fingerprint
            if document
            else result.partial.get("receipt_fingerprint")
        ),
    )
    if duplicate is not None:
        logger.warning(
            "Duplicate receipt rejected during extraction",
            extra={
                "event": "duplicate_receipt_rejected",
                "stage": "extraction",
                "entity_id": user["entity_id"],
                "duplicate_internal_id": duplicate.trx_id,
                "matched_by": matched_by,
            },
        )
        raise HTTPException(
            status_code=409,
            detail=duplicate_payload(duplicate, matched_by),
        )
    return result
