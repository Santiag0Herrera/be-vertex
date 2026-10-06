import base64
import datetime
import json
import logging
import os
import uuid
from typing import Iterable

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import DocumentUploadSession, TransactionDocument, Trx
from app.schemas.documents import CreateUploadSessionRequest
from app.schemas.transactions import MultipleDocumentRequest
from app.services.DocumentStorageService import DocumentStorageService
from app.services.TransactionsService import TransactionsService


logger = logging.getLogger("vertex.documents")

ALLOWED_MIME_TYPES = {
    value.strip().lower()
    for value in os.getenv(
        "DOCUMENT_ALLOWED_MIME_TYPES",
        "application/pdf,image/jpeg,image/png,image/tiff",
    ).split(",")
    if value.strip()
}

FILE_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/tiff": (b"II*\x00", b"MM\x00*"),
}


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


class DocumentService:
    def __init__(
        self,
        db: Session,
        req_user: dict,
        storage: DocumentStorageService | None = None,
    ):
        self.db = db
        self.req_user = req_user
        self.storage = storage or DocumentStorageService()
        self.max_batch_size = int(os.getenv("DOCUMENT_MAX_BATCH_SIZE", "50"))
        self.session_ttl_hours = int(os.getenv("DOCUMENT_SESSION_TTL_HOURS", "24"))

    @property
    def entity_id(self) -> int:
        return int(self.req_user["entity_id"])

    @property
    def actor_id(self) -> int:
        return int(self.req_user["id"])

    @property
    def actor_type(self) -> str:
        return str(self.req_user["account_type"])

    def _scoped_session(self, session_id: str, *, lock: bool = False):
        query = (
            self.db.query(DocumentUploadSession)
            .filter(
                DocumentUploadSession.id == session_id,
                DocumentUploadSession.entity_id == self.entity_id,
                DocumentUploadSession.actor_id == self.actor_id,
                DocumentUploadSession.actor_type == self.actor_type,
            )
        )
        if lock:
            query = query.with_for_update()
        else:
            query = query.options(joinedload(DocumentUploadSession.documents))
        session = query.first()
        if session is None:
            raise HTTPException(status_code=404, detail="Upload session not found")
        return session

    @staticmethod
    def _session_payload(session: DocumentUploadSession) -> dict:
        return {
            "upload_session_id": session.id,
            "status": session.status,
            "expires_at": session.expires_at,
            "committed_at": session.committed_at,
            "documents": [
                {
                    "document_id": document.id,
                    "client_document_id": document.client_document_id,
                    "status": document.status,
                    "original_name": document.original_name,
                }
                for document in session.documents
            ],
        }

    def create_upload_session(self, request: CreateUploadSessionRequest) -> dict:
        if len(request.documents) > self.max_batch_size:
            raise HTTPException(
                status_code=400,
                detail=f"A maximum of {self.max_batch_size} documents is allowed",
            )

        client_ids = [str(document.client_document_id) for document in request.documents]
        if len(client_ids) != len(set(client_ids)):
            raise HTTPException(status_code=400, detail="Duplicate client document id")

        for document in request.documents:
            if document.mime_type not in ALLOWED_MIME_TYPES:
                raise HTTPException(status_code=400, detail="Unsupported document type")
            if document.size_bytes > self.storage.max_size_bytes:
                raise HTTPException(status_code=413, detail="Document is too large")

        now = _utcnow()
        session_id = str(uuid.uuid4())
        upload_session = DocumentUploadSession(
            id=session_id,
            entity_id=self.entity_id,
            actor_id=self.actor_id,
            actor_type=self.actor_type,
            status="created",
            expires_at=now + datetime.timedelta(hours=self.session_ttl_hours),
            created_at=now,
            updated_at=now,
        )
        self.db.add(upload_session)

        response_documents = []
        try:
            for requested_document in request.documents:
                document_id = str(uuid.uuid4())
                client_document_id = str(requested_document.client_document_id)
                staging_key = self.storage.staging_key(
                    self.entity_id,
                    session_id,
                    document_id,
                )
                document = TransactionDocument(
                    id=document_id,
                    upload_session_id=session_id,
                    client_document_id=client_document_id,
                    entity_id=self.entity_id,
                    staging_key=staging_key,
                    original_name=requested_document.original_name,
                    mime_type=requested_document.mime_type,
                    size_bytes=requested_document.size_bytes,
                    sha256=requested_document.sha256,
                    status="pending_upload",
                    created_at=now,
                    updated_at=now,
                )
                self.db.add(document)
                upload_form = self.storage.create_upload_form(
                    key=staging_key,
                    mime_type=document.mime_type,
                    sha256=document.sha256,
                    size_bytes=document.size_bytes,
                )
                response_documents.append(
                    {
                        "document_id": document.id,
                        "client_document_id": document.client_document_id,
                        "upload_url": upload_form["url"],
                        "upload_fields": upload_form["fields"],
                    }
                )

            upload_session.status = "uploading"
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "upload_session_id": upload_session.id,
            "expires_at": upload_session.expires_at,
            "documents": response_documents,
        }

    def get_upload_session(self, session_id: str) -> dict:
        session = self._scoped_session(session_id)
        if session.status not in {"committed", "expired"} and _as_utc(
            session.expires_at
        ) <= _utcnow():
            session.status = "expired"
            self.db.commit()
        payload = self._session_payload(session)
        if session.status == "committed" and session.result_json:
            payload["result"] = json.loads(session.result_json)
        return payload

    def refresh_upload_session(
        self,
        session_id: str,
        client_document_ids: Iterable[str] | None = None,
    ) -> dict:
        session = self._scoped_session(session_id)
        if session.status in {"committed", "expired", "failed"}:
            raise HTTPException(
                status_code=409,
                detail=f"Upload session is {session.status}",
            )
        if _as_utc(session.expires_at) <= _utcnow():
            session.status = "expired"
            self.db.commit()
            raise HTTPException(status_code=409, detail="Upload session expired")

        requested_ids = set(client_document_ids or [])
        available_ids = {document.client_document_id for document in session.documents}
        if requested_ids and not requested_ids.issubset(available_ids):
            raise HTTPException(status_code=404, detail="Upload document not found")

        response_documents = []
        for document in session.documents:
            if requested_ids and document.client_document_id not in requested_ids:
                continue
            upload_form = self.storage.create_upload_form(
                key=document.staging_key,
                mime_type=document.mime_type,
                sha256=document.sha256,
                size_bytes=document.size_bytes,
            )
            response_documents.append(
                {
                    "document_id": document.id,
                    "client_document_id": document.client_document_id,
                    "upload_url": upload_form["url"],
                    "upload_fields": upload_form["fields"],
                }
            )

        return {
            "upload_session_id": session.id,
            "expires_at": session.expires_at,
            "documents": response_documents,
        }

    def _verify_staged_document(self, document: TransactionDocument) -> None:
        try:
            head = self.storage.head(document.staging_key)
            file_prefix = self.storage.read_prefix(document.staging_key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Staged document is unavailable",
                extra={"event": "staged_document_missing", "document_id": document.id},
            )
            raise HTTPException(
                status_code=409,
                detail="One or more documents have not finished uploading",
            ) from exc

        metadata = {
            str(key).lower(): str(value).lower()
            for key, value in (head.get("Metadata") or {}).items()
        }
        expected_checksum = base64.b64encode(bytes.fromhex(document.sha256)).decode(
            "ascii"
        )
        if (
            int(head.get("ContentLength", -1)) != document.size_bytes
            or str(head.get("ContentType", "")).lower() != document.mime_type
            or metadata.get("sha256") != document.sha256
            or head.get("ChecksumSHA256") not in {None, expected_checksum}
        ):
            raise HTTPException(
                status_code=400,
                detail="Uploaded document metadata does not match the request",
            )
        signatures = FILE_SIGNATURES.get(document.mime_type, ())
        if not any(file_prefix.startswith(signature) for signature in signatures):
            raise HTTPException(
                status_code=400,
                detail="Uploaded document content does not match its type",
            )

    def create_multiple_transactions(
        self,
        request: MultipleDocumentRequest,
    ) -> dict:
        if request.upload_session_id is None:
            return TransactionsService(self.db, self.req_user).create_multiple(request)

        session_id = str(request.upload_session_id)
        copied_keys: list[str] = []
        session = self._scoped_session(session_id, lock=True)

        if session.status == "committed":
            if not session.result_json:
                raise HTTPException(status_code=409, detail="Committed session has no result")
            return {"status": "ok", "result": json.loads(session.result_json)}
        if session.status in {"expired", "failed"} or _as_utc(
            session.expires_at
        ) <= _utcnow():
            session.status = "expired"
            self.db.commit()
            raise HTTPException(status_code=409, detail="Upload session expired")

        requested_ids = [
            str(transaction.client_document_id)
            for transaction in request.transactions
            if transaction.client_document_id is not None
        ]
        session_documents = {
            document.client_document_id: document for document in session.documents
        }
        if (
            len(requested_ids) != len(set(requested_ids))
            or set(requested_ids) != set(session_documents)
        ):
            raise HTTPException(
                status_code=400,
                detail="Transactions and uploaded documents do not match",
            )

        try:
            session.status = "committing"
            for document in session.documents:
                self._verify_staged_document(document)
                document.status = "staged"
                document.uploaded_at = _utcnow()

            transactions = TransactionsService(
                self.db,
                self.req_user,
            ).build_multiple(request)
            transactions_by_client_id = {
                str(transaction_request.client_document_id): transaction
                for transaction_request, transaction in zip(
                    request.transactions,
                    transactions,
                )
                if transaction_request.client_document_id is not None
            }

            now = _utcnow()
            for client_document_id, document in session_documents.items():
                destination_key = self.storage.object_key(
                    self.entity_id,
                    document.id,
                )
                self.storage.copy(document.staging_key, destination_key)
                copied_keys.append(destination_key)
                document.object_key = destination_key
                document.trx_id = transactions_by_client_id[client_document_id].id
                document.status = "active"
                document.activated_at = now

            result = {"created": len(transactions), "duplicates": []}
            session.status = "committed"
            session.committed_at = now
            session.result_json = json.dumps(result)
            self.db.commit()
        except HTTPException:
            self.db.rollback()
            self._delete_compensating_copies(copied_keys)
            raise
        except (BotoCoreError, ClientError) as exc:
            self.db.rollback()
            self._delete_compensating_copies(copied_keys)
            logger.exception(
                "S3 failed while committing an upload session",
                extra={"event": "document_commit_s3_failed", "session_id": session_id},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Document storage is temporarily unavailable",
            ) from exc
        except Exception:
            self.db.rollback()
            self._delete_compensating_copies(copied_keys)
            raise

        for document in session.documents:
            try:
                self.storage.delete(document.staging_key)
            except (BotoCoreError, ClientError):
                logger.warning(
                    "Could not remove staged document after commit",
                    extra={
                        "event": "staging_cleanup_failed",
                        "document_id": document.id,
                    },
                )

        return {"status": "ok", "result": result}

    def _delete_compensating_copies(self, keys: Iterable[str]) -> None:
        for key in keys:
            try:
                self.storage.delete(key)
            except Exception:
                logger.exception(
                    "Could not remove copied document after rollback",
                    extra={"event": "document_compensation_failed"},
                )

    def create_transaction_document_url(self, trx_id: int) -> dict:
        query = self.db.query(Trx).filter(
            Trx.id == trx_id,
            Trx.entity_id == self.entity_id,
        )
        if self.actor_type == "client":
            query = query.filter(Trx.client_id == self.actor_id)
        transaction = query.first()
        if transaction is None or transaction.document is None:
            raise HTTPException(status_code=404, detail="Document not available")

        document = transaction.document
        if document.status == "deleted":
            raise HTTPException(
                status_code=410,
                detail="Document deleted according to the retention policy",
            )
        if document.status != "active" or not document.object_key:
            raise HTTPException(status_code=404, detail="Document not available")

        try:
            url = self.storage.create_view_url(
                key=document.object_key,
                original_name=document.original_name,
                mime_type=document.mime_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Document storage is temporarily unavailable",
            ) from exc

        return {
            "url": url,
            "expires_in": self.storage.view_ttl_seconds,
            "mime_type": document.mime_type,
            "original_name": document.original_name,
        }

    def expired_summary(self) -> dict:
        now = _utcnow()
        query = self.db.query(TransactionDocument).filter(
            TransactionDocument.entity_id == self.entity_id,
            TransactionDocument.status == "active",
            TransactionDocument.delete_after.isnot(None),
            TransactionDocument.delete_after <= now,
        )
        eligible, size_bytes = query.with_entities(
            func.count(TransactionDocument.id),
            func.coalesce(func.sum(TransactionDocument.size_bytes), 0),
        ).one()
        return {
            "eligible": int(eligible),
            "size_bytes": int(size_bytes),
        }

    def delete_expired(self, limit: int = 100) -> dict:
        now = _utcnow()
        eligible = (
            self.db.query(TransactionDocument)
            .filter(
                TransactionDocument.entity_id == self.entity_id,
                TransactionDocument.status == "active",
                TransactionDocument.delete_after.isnot(None),
                TransactionDocument.delete_after <= now,
            )
            .count()
        )
        documents = (
            self.db.query(TransactionDocument)
            .filter(
                TransactionDocument.entity_id == self.entity_id,
                TransactionDocument.status == "active",
                TransactionDocument.delete_after.isnot(None),
                TransactionDocument.delete_after <= now,
            )
            .order_by(TransactionDocument.delete_after.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        for document in documents:
            document.status = "deleting"
        self.db.commit()

        deleted = 0
        failed_ids: list[str] = []
        for document in documents:
            try:
                if document.object_key:
                    self.storage.delete(document.object_key)
                document.status = "deleted"
                document.deleted_at = _utcnow()
                document.last_deletion_error = None
                deleted += 1
            except (BotoCoreError, ClientError) as exc:
                document.status = "active"
                document.deletion_attempts += 1
                document.last_deletion_error = type(exc).__name__
                failed_ids.append(document.id)
                logger.warning(
                    "Manual document deletion failed",
                    extra={"event": "document_delete_failed", "document_id": document.id},
                )
            self.db.commit()

        return {
            "eligible": eligible,
            "attempted": len(documents),
            "deleted": deleted,
            "failed": len(failed_ids),
            "remaining": max(eligible - len(documents), 0),
            "failed_document_ids": failed_ids,
        }
