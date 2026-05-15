from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.services.auth_service import get_current_user
from app.services.extractor.models import DocumentExtractResponse
from app.services.extractor.service import extract_document_from_file


router = APIRouter(prefix="/extractorV2", tags=["TextractV2"])
user_dependency = Annotated[dict, Depends(get_current_user)]


@router.post("/aws-extract", response_model=DocumentExtractResponse)
async def analyze_document(
    user: user_dependency,
    file: UploadFile = File(...),
) -> DocumentExtractResponse:
    return await extract_document_from_file(file)
