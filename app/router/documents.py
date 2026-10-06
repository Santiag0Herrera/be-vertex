from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.documents import CreateUploadSessionRequest, RefreshUploadSessionRequest
from app.services.auth_service import get_current_user, require_admin_user
from app.services.DocumentService import DocumentService
from app.services.SuccessService import SuccessService


router = APIRouter(prefix="/documents", tags=["Transaction documents"])
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]
admin_dependency = Annotated[dict, Depends(require_admin_user)]


@router.post("/upload-sessions", status_code=201)
def create_upload_session(
    request: CreateUploadSessionRequest,
    db: db_dependency,
    user: user_dependency,
):
    return SuccessService.response(
        DocumentService(db, user).create_upload_session(request)
    )


@router.get("/upload-sessions/{session_id}")
def get_upload_session(
    session_id: str,
    db: db_dependency,
    user: user_dependency,
):
    return SuccessService.response(
        DocumentService(db, user).get_upload_session(session_id)
    )


@router.post("/upload-sessions/{session_id}/refresh")
def refresh_upload_session(
    session_id: str,
    request: RefreshUploadSessionRequest,
    db: db_dependency,
    user: user_dependency,
):
    client_document_ids = (
        [str(value) for value in request.client_document_ids]
        if request.client_document_ids
        else None
    )
    return SuccessService.response(
        DocumentService(db, user).refresh_upload_session(
            session_id,
            client_document_ids,
        )
    )


@router.get("/expired-summary")
def expired_summary(db: db_dependency, user: admin_dependency):
    return SuccessService.response(DocumentService(db, user).expired_summary())


@router.post("/delete-expired")
def delete_expired_documents(
    db: db_dependency,
    user: admin_dependency,
    limit: int = Query(100, ge=1, le=500),
):
    return SuccessService.response(DocumentService(db, user).delete_expired(limit))
