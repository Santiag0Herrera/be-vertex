import datetime
import logging
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from app.models import Trx, CBU, Entity, CustomersBalance, EntityCBU, Clients
from sqlalchemy import cast, or_, String
from app.schemas.transactions import (
    DocumentRequest,
    MultipleDocumentRequest,
)
import uuid

from .ErrorService import ErrorService
from .SuccessService import SuccessService
from .ResponseSerializationService import ResponseSerializationService
from .ReceiptIdentityService import (
    build_receipt_fingerprint,
    duplicate_payload,
    find_duplicate_receipt,
)


@dataclass(frozen=True)
class ReceiptIdentity:
    source_trx_id: str | None
    file_sha256: str | None
    receipt_fingerprint: str


@dataclass
class MultipleTransactionBuild:
    transactions: list[Trx]
    transactions_by_client_document_id: dict[str, Trx]
    duplicates: list[dict]


logger = logging.getLogger("vertex.receipts")


class TransactionsService:
    BUSINESS_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")
    db: Session
    req_user: dict
    error: ErrorService
    success: SuccessService

    def __init__(self, db: Session, req_user: dict):
        self.db = db
        self.req_user = req_user
        self.error = ErrorService()
        self.success = SuccessService()

    def _get_scoped_account(self, account_id: int) -> CustomersBalance:
        query = (
            self.db.query(CustomersBalance)
            .join(Clients, CustomersBalance.client_id == Clients.id)
            .filter(
                CustomersBalance.id == account_id,
                CustomersBalance.enabled == True,
                Clients.enabled == True,
                Clients.entity_id == self.req_user.get("entity_id"),
            )
        )
        if self.req_user.get("account_type") == "client":
            query = query.filter(Clients.id == self.req_user.get("id"))

        account = query.first()
        self.error.raise_if_none(account, "Client Account")
        return account

    def _parse_date_filter(self, value, end_of_day=False):
        if not value:
            return None

        if isinstance(value, datetime.datetime):
            return value

        if isinstance(value, datetime.date):
            boundary_time = datetime.time.max if end_of_day else datetime.time.min
            return datetime.datetime.combine(value, boundary_time)

        if isinstance(value, str):
            raw_value = value.strip()
            is_date_only = len(raw_value) == 10 and raw_value.count("-") == 2

            try:
                parsed_value = datetime.datetime.fromisoformat(
                    raw_value.replace("Z", "+00:00")
                )
            except ValueError:
                self.error.raise_bad_request(
                    "Invalid date format. Use YYYY-MM-DD or ISO datetime."
                )

            if parsed_value.tzinfo is not None:
                parsed_value = parsed_value.replace(tzinfo=None)

            if is_date_only:
                boundary_time = datetime.time.max if end_of_day else datetime.time.min
                parsed_value = datetime.datetime.combine(
                    parsed_value.date(), boundary_time
                )

            return parsed_value

        self.error.raise_bad_request("Invalid date value.")

    def _received_date(self, value):
        return value or datetime.datetime.now(self.BUSINESS_TIMEZONE).date()

    @staticmethod
    def _normalize_account(value):
        return re.sub(r"[^0-9A-Z]", "", str(value or "").strip().upper())

    def _receipt_identity(self, document_request: DocumentRequest) -> ReceiptIdentity:
        try:
            receipt_fingerprint = build_receipt_fingerprint(document_request)
        except ValueError as exc:
            self.error.raise_bad_request(str(exc))

        return ReceiptIdentity(
            source_trx_id=(
                str(document_request.trx_id).strip()
                if document_request.trx_id
                else None
            ),
            file_sha256=(
                str(document_request.file_sha256).strip().lower()
                if document_request.file_sha256
                else None
            ),
            receipt_fingerprint=receipt_fingerprint,
        )

    def _find_duplicate(self, identity: ReceiptIdentity):
        return find_duplicate_receipt(
            self.db,
            entity_id=self.req_user.get("entity_id"),
            content_sha256=identity.file_sha256,
            receipt_fingerprint=identity.receipt_fingerprint,
        )

    @staticmethod
    def _duplicate_result(document_request, duplicate, matched_by):
        result = duplicate_payload(duplicate, matched_by)
        result.update(
            {
                "client_document_id": document_request.client_document_id,
                "trx_id": document_request.trx_id,
                "amount": document_request.amount,
                "date": document_request.date,
            }
        )
        return result

    def get_all(
        self,
        page=0,
        recordsPerPage=10,
        dateFrom=None,
        dateTo=None,
        status=None,
        account=None,
        client=None,
        account_id=None,
        client_id=None,
        document_name=None,
    ):
        page = max(int(page or 0), 0)
        recordsPerPage = min(max(int(recordsPerPage or 10), 1), 100)

        offset = page * recordsPerPage

        base_query = (
            self.db.query(Trx)
            .options(
                joinedload(Trx.account).joinedload(CustomersBalance.client),
                joinedload(Trx.account).joinedload(CustomersBalance.currency),
                joinedload(Trx.document),
            )
            .join(CustomersBalance, Trx.account_id == CustomersBalance.id)
            .join(Clients, CustomersBalance.client_id == Clients.id)
            .filter(
                Trx.entity_id == self.req_user.get("entity_id"),
                Clients.entity_id == self.req_user.get("entity_id"),
            )
        )

        if dateFrom:
            base_query = base_query.filter(Trx.date >= dateFrom)

        if dateTo:
            base_query = base_query.filter(Trx.date <= dateTo)

        if status:
            base_query = base_query.filter(Trx.status.ilike(f"%{status.strip()}%"))

        if account:
            account_value = f"%{account.strip()}%"
            base_query = base_query.filter(
                or_(
                    cast(CustomersBalance.id, String).ilike(account_value),
                    cast(Trx.account_id, String).ilike(account_value),
                    Trx.emisor_cbu.ilike(account_value),
                    Trx.receptor_cbu.ilike(account_value),
                )
            )

        if client:
            client_value = f"%{client.strip()}%"
            base_query = base_query.filter(
                or_(
                    Clients.first_name.ilike(client_value),
                    Clients.last_name.ilike(client_value),
                    Clients.email.ilike(client_value),
                )
            )

        if account_id:
            base_query = base_query.filter(Trx.account_id == account_id)

        if client_id:
            base_query = base_query.filter(CustomersBalance.client_id == client_id)

        if document_name and document_name.strip():
            base_query = base_query.filter(
                Trx.document_name.ilike(f"%{document_name.strip()}%")
            )

        total_records = base_query.count()

        transactions_model = (
            base_query.order_by(
                Trx.received_date.desc(),
                Trx.creation_date.desc(),
                Trx.id.desc(),
            )
            .offset(offset)
            .limit(recordsPerPage)
            .all()
        )

        day_total_amount = sum(transaction.amount for transaction in transactions_model)

        result = {
            "transactions": [
                ResponseSerializationService.transaction(transaction)
                for transaction in transactions_model
            ],
            "total_amount": day_total_amount,
            "page": page,
            "recordsPerPage": recordsPerPage,
            "totalRecords": total_records,
            "totalPages": (total_records + recordsPerPage - 1) // recordsPerPage,
        }

        return self.success.response(result)

    def create(self, document_request: DocumentRequest, user: dict):
        account_model = self._get_scoped_account(document_request.account_id)
        identity = self._receipt_identity(document_request)

        duplicate, matched_by = self._find_duplicate(identity)
        if duplicate is not None:
            logger.warning(
                "Duplicate receipt rejected during transaction creation",
                extra={
                    "event": "duplicate_receipt_rejected",
                    "stage": "transaction_creation",
                    "entity_id": self.req_user.get("entity_id"),
                    "duplicate_internal_id": duplicate.trx_id,
                    "matched_by": matched_by,
                },
            )
            raise HTTPException(
                status_code=409,
                detail=duplicate_payload(duplicate, matched_by),
            )

        cbu_model = (
            self.db.query(CBU)
            .join(EntityCBU, EntityCBU.cbu_id == CBU.id)
            .filter(
                CBU.cuit == document_request.receptor_cuit,
                EntityCBU.entity_id == self.req_user.get("entity_id"),
            )
            .first()
        )
        self.error.raise_if_none(cbu_model)

        internal_trx_id = (
            document_request.trx_id or f"AUTO-{uuid.uuid4().hex[:16].upper()}"
        )
        trx_exists_model = (
            self.db.query(Trx).filter(Trx.trx_id == internal_trx_id).first()
        )
        if trx_exists_model:
            self.error.raise_conflict("Transaction already exists")

        entity_model = (
            self.db.query(Entity)
            .join(EntityCBU, Entity.id == EntityCBU.entity_id)
            .filter(EntityCBU.cbu_id == cbu_model.id)
            .first()
        )
        self.error.raise_if_none(
            entity_model, f"Entity with cuit: {document_request.receptor_cuit}"
        )

        create_user_model = Trx(
            file_sha256=identity.file_sha256,
            receipt_fingerprint=identity.receipt_fingerprint,
            source_trx_id=identity.source_trx_id,
            document_name=document_request.document_name,
            emisor_cbu=document_request.emisor_cbu,
            emisor_name=document_request.emisor_name,
            emisor_cuit=document_request.emisor_cuit,
            receptor_cuit=document_request.receptor_cuit,
            receptor_cbu=cbu_model.nro,
            entity_id=entity_model.id,
            client_id=account_model.client_id,
            amount=document_request.amount,
            date=document_request.date,
            received_date=self._received_date(document_request.received_date),
            creation_date=datetime.datetime.utcnow(),
            trx_id=internal_trx_id,
            account_id=document_request.account_id,
            status="pendiente",
        )
        try:
            self.db.add(create_user_model)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate_receipt"},
            ) from exc
        return self.success.response("Transaction registered!")

    def build_multiple(self, multiple_trx_request: MultipleDocumentRequest):
        account_model = self._get_scoped_account(multiple_trx_request.account_id)
        entity_model = (
            self.db.query(Entity)
            .filter(Entity.id == self.req_user.get("entity_id"))
            .first()
        )
        self.error.raise_if_none(entity_model, "Entity")
        receptor_account_number = multiple_trx_request.owner_account_number
        if not receptor_account_number:
            self.error.raise_bad_request("Owner account number is required")
        if self.req_user.get("account_type") == "client":
            owner_accounts = (
                self.db.query(EntityCBU)
                .join(CBU, EntityCBU.cbu_id == CBU.id)
                .filter(
                    EntityCBU.entity_id == self.req_user.get("entity_id"),
                )
                .all()
            )
            owner_account = next(
                (
                    entity_cbu
                    for entity_cbu in owner_accounts
                    if self._normalize_account(entity_cbu.cbu.nro)
                    == self._normalize_account(receptor_account_number)
                ),
                None,
            )
            self.error.raise_if_none(owner_account, "Owner account")
            receptor_account_number = owner_account.cbu.nro
        new_trx = []
        transactions_by_client_document_id: dict[str, Trx] = {}
        duplicates = []
        seen_file_hashes: dict[str, str | None] = {}
        seen_receipt_fingerprints: dict[str, str | None] = {}
        for doc in multiple_trx_request.transactions:
            identity = self._receipt_identity(doc)
            matched_in_batch = []
            duplicate_of = None
            if identity.file_sha256 and identity.file_sha256 in seen_file_hashes:
                matched_in_batch.append("file_sha256")
                duplicate_of = seen_file_hashes[identity.file_sha256]
            if identity.receipt_fingerprint in seen_receipt_fingerprints:
                matched_in_batch.append("receipt_fingerprint")
                duplicate_of = seen_receipt_fingerprints[
                    identity.receipt_fingerprint
                ]

            if matched_in_batch:
                logger.warning(
                    "Duplicate receipt skipped inside upload batch",
                    extra={
                        "event": "duplicate_receipt_rejected",
                        "stage": "transaction_creation",
                        "entity_id": self.req_user.get("entity_id"),
                        "matched_by": matched_in_batch,
                    },
                )
                duplicates.append(
                    {
                        "code": "duplicate_receipt",
                        "duplicate_of": duplicate_of,
                        "matched_by": matched_in_batch,
                        "client_document_id": doc.client_document_id,
                        "trx_id": doc.trx_id,
                        "document_name": doc.document_name,
                        "amount": doc.amount,
                        "date": doc.date,
                    }
                )
                continue

            duplicate, matched_by = self._find_duplicate(identity)
            if duplicate is not None:
                logger.warning(
                    "Duplicate receipt skipped during transaction creation",
                    extra={
                        "event": "duplicate_receipt_rejected",
                        "stage": "transaction_creation",
                        "entity_id": self.req_user.get("entity_id"),
                        "duplicate_internal_id": duplicate.trx_id,
                        "matched_by": matched_by,
                    },
                )
                duplicates.append(
                    self._duplicate_result(doc, duplicate, matched_by)
                )
                continue

            emisor_name = doc.emisor_name
            emisor_cuit = doc.emisor_cuit
            emisor_cbu = doc.emisor_cbu
            internal_trx_id = f"AUTO-{uuid.uuid4().hex[:16].upper()}"
            trx_model = Trx(
                file_sha256=identity.file_sha256,
                receipt_fingerprint=identity.receipt_fingerprint,
                source_trx_id=identity.source_trx_id,
                document_name=doc.document_name or multiple_trx_request.document_name,
                emisor_cbu=emisor_cbu,
                emisor_name=emisor_name,
                emisor_cuit=emisor_cuit,
                receptor_cuit=doc.receptor_cuit,
                receptor_cbu=receptor_account_number,
                entity_id=entity_model.id,
                client_id=account_model.client_id,
                amount=doc.amount,
                date=doc.date,
                received_date=self._received_date(doc.received_date),
                trx_id=internal_trx_id,
                account_id=multiple_trx_request.account_id,
                status="pendiente",
            )
            new_trx.append(trx_model)
            self.db.add(trx_model)
            if doc.client_document_id is not None:
                transactions_by_client_document_id[
                    str(doc.client_document_id)
                ] = trx_model
            if identity.file_sha256:
                seen_file_hashes[identity.file_sha256] = identity.source_trx_id
            seen_receipt_fingerprints[
                identity.receipt_fingerprint
            ] = identity.source_trx_id

        self.db.flush()
        return MultipleTransactionBuild(
            transactions=new_trx,
            transactions_by_client_document_id=transactions_by_client_document_id,
            duplicates=duplicates,
        )

    def create_multiple(self, multiple_trx_request: MultipleDocumentRequest):
        try:
            build = self.build_multiple(multiple_trx_request)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "duplicate_receipt",
                    "message": "A receipt was uploaded concurrently. Retry the request.",
                },
            ) from exc
        except Exception:
            self.db.rollback()
            raise

        return self.success.response(
            {
                "created": len(build.transactions),
                "duplicates": build.duplicates,
            }
        )

    def get_all_by_client_id(
        self,
        page=0,
        recordsPerPage=10,
        dateFrom=None,
        dateTo=None,
        status=None,
    ):

        if self.req_user.get("account_type") != "client":
            self.error.raise_forbidden("Este endpoint es exclusivo para clientes.")

        page = max(int(page or 0), 0)
        recordsPerPage = min(max(int(recordsPerPage or 10), 1), 100)
        offset = page * recordsPerPage
        date_from_filter = self._parse_date_filter(dateFrom)
        date_to_filter = self._parse_date_filter(dateTo, end_of_day=True)

        base_query = (
            self.db.query(Trx)
            .options(
                joinedload(Trx.account).joinedload(CustomersBalance.client),
                joinedload(Trx.account).joinedload(CustomersBalance.currency),
                joinedload(Trx.document),
            )
            .join(CustomersBalance, Trx.account_id == CustomersBalance.id)
            .filter(
                CustomersBalance.client_id == self.req_user.get("id"),
                Trx.entity_id == self.req_user.get("entity_id"),
            )
        )

        if date_from_filter:
            base_query = base_query.filter(Trx.date >= date_from_filter)
        if date_to_filter:
            base_query = base_query.filter(Trx.date <= date_to_filter)
        if status:
            base_query = base_query.filter(Trx.status.ilike(f"%{status.strip()}%"))

        total_records = base_query.count()
        transactions_model = (
            base_query.order_by(
                Trx.received_date.desc(),
                Trx.creation_date.desc(),
                Trx.id.desc(),
            )
            .offset(offset)
            .limit(recordsPerPage)
            .all()
        )
        day_total_amount = sum(transaction.amount for transaction in transactions_model)
        result = {
            "transactions": [
                ResponseSerializationService.transaction(transaction)
                for transaction in transactions_model
            ],
            "total_amount": day_total_amount,
            "page": page,
            "recordsPerPage": recordsPerPage,
            "totalRecords": total_records,
            "totalPages": (total_records + recordsPerPage - 1) // recordsPerPage,
        }
        return self.success.response(result)
