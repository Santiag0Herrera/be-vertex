from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Response, UploadFile

from app.services.auth_service import get_current_user
from app.services.extractor.models import DocumentExtractResponse
from app.services.extractor.service import extract_document_from_file


router = APIRouter(prefix="/extractorV2", tags=["TextractV2"])
user_dependency = Annotated[dict, Depends(get_current_user)]


@router.post("/aws-extract", response_model=DocumentExtractResponse)
async def analyze_document(
    response: Response,
    user: user_dependency,
    file: UploadFile = File(...),
) -> DocumentExtractResponse:
    request_id = uuid4().hex
    response.headers["X-Request-ID"] = request_id
    return await extract_document_from_file(file, request_id=request_id)
