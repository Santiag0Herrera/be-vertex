import datetime

from sqlalchemy.orm import Session, joinedload
from app.models import Trx, Users, CBU, Entity, CustomersBalance, EntityCBU, Clients
from sqlalchemy import cast, or_, String
from app.schemas.transactions import (
    DocumentRequest,
    MultipleDocumentRequest,
    UploadDocumentRequest,
)
import uuid

from .ErrorService import ErrorService
from .SuccessService import SuccessService
from .InterBankingService import InterBankingService
from .N8NService import N8NService


class TransactionsService:
    db: Session
    req_user: dict
    error: ErrorService
    success: SuccessService

    def __init__(self, db: Session, req_user: dict):
        self.db = db
        self.req_user = req_user
        self.error = ErrorService()
        self.success = SuccessService()
        self.ib_service = InterBankingService()
        self.n8n_service = N8NService()

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

    async def _verify_bank_movement(
        self, account_number: str, bank_number: str, customer_id: str
    ):
        movement_model = self.ib_service.get_movement(
            account_number=account_number,
            bank_number=bank_number,
            customer_id=customer_id,
        )
        return self.error.raise_if_none(movement_model, "Movment")

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
    ):
        user_model = (
            self.db.query(Users).filter(Users.id == self.req_user.get("id")).first()
        )

        page = max(int(page or 0), 0)
        recordsPerPage = max(int(recordsPerPage or 10), 1)

        offset = page * recordsPerPage

        base_query = (
            self.db.query(Trx)
            .options(joinedload(Trx.account).joinedload(CustomersBalance.currency))
            .join(CustomersBalance, Trx.account_id == CustomersBalance.id)
            .join(Clients, CustomersBalance.client_id == Clients.id)
            .filter(
                Trx.entity_id == user_model.entity_id,
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

        total_records = base_query.count()

        transactions_model = (
            base_query.order_by(Trx.creation_date.desc(), Trx.id.desc())
            .offset(offset)
            .limit(recordsPerPage)
            .all()
        )

        day_total_amount = sum(transaction.amount for transaction in transactions_model)

        result = {
            "transactions": transactions_model,
            "total_amount": day_total_amount,
            "page": page,
            "recordsPerPage": recordsPerPage,
            "totalRecords": total_records,
            "totalPages": (total_records + recordsPerPage - 1) // recordsPerPage,
        }

        return self.success.response(result)

    def create(self, document_request: DocumentRequest, user: dict):
        account_model = self.db.query(CustomersBalance).filter(
            CustomersBalance.id == document_request.account_id
        )
        self.error.raise_if_none(account_model, "Clinet Account")

        cbu_model = (
            self.db.query(CBU)
            .filter(CBU.cuit == document_request.receptor_cuit)
            .first()
        )
        self.error.raise_if_none(cbu_model)

        trx_exists_model = (
            self.db.query(Trx).filter(Trx.trx_id == document_request.trx_id).first()
        )
        self.error.raise_if_none(trx_exists_model)

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
            emisor_cbu=document_request.emisor_cbu,
            emisor_name=document_request.emisor_name,
            emisor_cuit=document_request.emisor_cuit,
            receptor_cbu=cbu_model.nro,
            entity_id=entity_model.id,
            amount=document_request.amount,
            date=document_request.date,
            creation_date=datetime.utcnow(),
            trx_id=document_request.trx_id,
            account_id=document_request.account_id,
            status="pendiente",
        )
        self.db.add(create_user_model)
        self.db.commit()
        return self.success.response("Transaction registered!")

    def create_multiple(self, multiple_trx_request: MultipleDocumentRequest):
        account_model = (
            self.db.query(CustomersBalance)
            .filter(CustomersBalance.id == multiple_trx_request.account_id)
            .first()
        )
        self.error.raise_if_none(account_model, "Client Account")
        entity_model = (
            self.db.query(Entity)
            .filter(Entity.id == self.req_user.get("entity_id"))
            .first()
        )
        self.error.raise_if_none(entity_model, "Entity")
        receptor_account_number = multiple_trx_request.owner_account_number
        if not receptor_account_number:
            self.error.raise_bad_request("Owner account number is required")
        new_trx = []
        for doc in multiple_trx_request.transactions:
            emisor_name = doc.emisor_name or entity_model.name
            emisor_cuit = "-"
            emisor_cbu = doc.emisor_cbu or receptor_account_number
            trx_model = Trx(
                emisor_cbu=emisor_cbu,
                emisor_name=emisor_name,
                emisor_cuit=emisor_cuit,
                receptor_cbu=receptor_account_number,
                entity_id=entity_model.id,
                amount=doc.amount,
                date=doc.date,
                trx_id=f"AUTO-{uuid.uuid4().hex[:16].upper()}",
                account_id=multiple_trx_request.account_id,
                status="pendiente",
            )
            new_trx.append(trx_model)
            self.db.add(trx_model)

        self.db.commit()
        return self.success.response(
            {"created": len(new_trx), "duplicates": []}
        )

    async def upload_file(self, upload_document_request: UploadDocumentRequest):
        response = await self.n8n_service.ai_extract_info(upload_document_request)
        self.error.raise_if_none(response, "Document info")
        return response

    def get_all_by_client_id(
        self,
        page=0,
        recordsPerPage=10,
        dateFrom=None,
        dateTo=None,
        status=None,
    ):

        page = max(int(page or 0), 0)
        recordsPerPage = max(int(recordsPerPage or 10), 1)
        offset = page * recordsPerPage
        date_from_filter = self._parse_date_filter(dateFrom)
        date_to_filter = self._parse_date_filter(dateTo, end_of_day=True)

        base_query = (
            self.db.query(Trx)
            .options(joinedload(Trx.account).joinedload(CustomersBalance.currency))
            .join(CustomersBalance, Trx.account_id == CustomersBalance.id)
            .filter(CustomersBalance.client_id == self.req_user.get("id"))
        )

        if date_from_filter:
            base_query = base_query.filter(Trx.date >= date_from_filter)
        if date_to_filter:
            base_query = base_query.filter(Trx.date <= date_to_filter)
        if status:
            base_query = base_query.filter(Trx.status.ilike(f"%{status.strip()}%"))

        total_records = base_query.count()
        transactions_model = (
            base_query.order_by(Trx.creation_date.desc(), Trx.id.desc())
            .offset(offset)
            .limit(recordsPerPage)
            .all()
        )
        day_total_amount = sum(transaction.amount for transaction in transactions_model)
        result = {
            "transactions": transactions_model,
            "total_amount": day_total_amount,
            "page": page,
            "recordsPerPage": recordsPerPage,
            "totalRecords": total_records,
            "totalPages": (total_records + recordsPerPage - 1) // recordsPerPage,
        }
        return self.success.response(result)
