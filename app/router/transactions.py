from datetime import date
from typing import Annotated
from sqlalchemy.orm import Session
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user, require_client, require_internal_user
from app.schemas.transactions import (
    DocumentRequest,
    MultipleDocumentRequest,
    MovementsRequest,
)
from app.jobs.validate_trx import run as run_reconciliation_job
from app.services.DBService import DBService
from app.services.InterBankingService import InterBankingService
from app.services.SuccessService import SuccessService
from app.services.TransactionReportService import TransactionReportService
from app.models import CBU, EntityCBU
from typing import Optional

router = APIRouter(prefix="/trx", tags=["Transactions"])

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]
internal_dependency = Annotated[dict, Depends(require_internal_user)]
client_dependency = Annotated[dict, Depends(require_client)]
reconciliation_job_lock = asyncio.Lock()


def _normalize_account(value: object) -> str:
    return str(value or "").replace(" ", "").replace("-", "").strip()


def _entity_cbus(db: Session, entity_id: int) -> set[str]:
    rows = (
        db.query(CBU.nro)
        .join(EntityCBU, EntityCBU.cbu_id == CBU.id)
        .filter(EntityCBU.entity_id == entity_id)
        .all()
    )
    return {_normalize_account(row[0]) for row in rows}


def _filter_entity_accounts(accounts: list[dict], owned_cbus: set[str]) -> list[dict]:
    return [
        account
        for account in accounts
        if _normalize_account(account.get("account_cbu")) in owned_cbus
        or _normalize_account(account.get("cbu")) in owned_cbus
        or _normalize_account(account.get("account_number")) in owned_cbus
    ]


async def _require_entity_interbanking_account(
    db: Session,
    user: dict,
    ib_service: InterBankingService,
    account_number: str,
    bank_number: str,
) -> None:
    accounts = await ib_service.get_accounts_only()
    allowed_accounts = _filter_entity_accounts(
        accounts,
        _entity_cbus(db, user["entity_id"]),
    )
    requested_account = _normalize_account(account_number)
    requested_bank = _normalize_account(bank_number)
    if not any(
        _normalize_account(account.get("account_number")) == requested_account
        and _normalize_account(account.get("bank_number")) == requested_bank
        for account in allowed_accounts
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found")


@router.post(
    "/reconcile-pending",
    status_code=status.HTTP_200_OK,
)
async def reconcile_pending_transactions(user: internal_dependency):
    if reconciliation_job_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The reconciliation job is already running",
        )

    async with reconciliation_job_lock:
        return SuccessService.response(
            await run_reconciliation_job(entity_id=user["entity_id"])
        )


@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_transactions(
    db: db_dependency,
    user: internal_dependency,
    page: int = Query(0, ge=0),
    recordsPerPage: int = Query(10, gt=0),
    dateFrom: Optional[str] = Query(None),
    dateTo: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    account: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    account_id: Optional[int] = Query(None),
    client_id: Optional[int] = Query(None),
    document_name: Optional[str] = Query(None),
):
    db_service = DBService(db=db, req_user=user)
    transactions_model = db_service.trx.get_all(
        page=page,
        recordsPerPage=recordsPerPage,
        dateFrom=dateFrom,
        dateTo=dateTo,
        status=status,
        account=account,
        client=client,
        account_id=account_id,
        client_id=client_id,
        document_name=document_name,
    )
    return transactions_model


@router.get("/report.csv", response_class=Response, status_code=status.HTTP_200_OK)
async def export_transaction_report(
    db: db_dependency,
    user: internal_dependency,
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    transaction_status: Optional[str] = Query(None, alias="status"),
    client_id: Optional[int] = Query(None, gt=0),
    account_ids: Optional[list[int]] = Query(None),
):
    filename, csv_content = TransactionReportService(db, user).generate(
        month=month,
        date_from=date_from,
        date_to=date_to,
        transaction_status=transaction_status,
        client_id=client_id,
        account_ids=account_ids,
    )
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/all_by_client", status_code=status.HTTP_200_OK)
async def get_all_transactions_by_client_id(
    db: db_dependency,
    user: client_dependency,
    page: int = Query(0, ge=0),
    recordsPerPage: int = Query(10, gt=0),
    dateFrom: Optional[str] = Query(None),
    dateTo: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    db_service = DBService(db=db, req_user=user)
    transactions_model = db_service.trx.get_all_by_client_id(
        page,
        recordsPerPage,
        dateFrom,
        dateTo,
        status,
    )
    return transactions_model


@router.post("/new", status_code=status.HTTP_201_CREATED)
async def upload_new_document(
    db: db_dependency, document_request: DocumentRequest, user: user_dependency
):
    db_service = DBService(db=db, req_user=user)
    trx_model = db_service.trx.create(document_request, user)
    return trx_model


@router.post("/multiple/new", status_code=status.HTTP_201_CREATED)
async def upload_multiple_new_document(
    db: db_dependency,
    user: user_dependency,
    multiple_trx_request: MultipleDocumentRequest,
):
    db_service = DBService(db=db, req_user=user)
    trx_model = db_service.trx.create_multiple(multiple_trx_request)
    return trx_model


@router.get("/get_movement", status_code=status.HTTP_200_OK)
async def get_movement_from_interbanking(
    db: db_dependency,
    user: internal_dependency,
    account_number: str = Query(...),
    bank_number: str = Query(...),
    date_since: Optional[str] = Query(None),
    date_until: Optional[str] = Query(None),
):
    ib_service = InterBankingService()
    await _require_entity_interbanking_account(
        db, user, ib_service, account_number, bank_number
    )
    movements_model = await ib_service.get_movement(
        account_number, bank_number, date_since=date_since, date_until=date_until
    )
    # bank_number: 015
    # account_number: 09170210248397
    return SuccessService.response(movements_model)


@router.post("/get_movements", status_code=status.HTTP_200_OK)
async def post_movements_from_interbanking(
    db: db_dependency,
    user: internal_dependency,
    movements_request: MovementsRequest,
):
    ib_service = InterBankingService()
    await _require_entity_interbanking_account(
        db,
        user,
        ib_service,
        movements_request.account_number,
        movements_request.bank_number,
    )
    movements_model = await ib_service.get_movement(
        movements_request.account_number,
        movements_request.bank_number,
        date_since=movements_request.date_since,
        date_until=movements_request.date_until,
    )
    # bank_number: 015
    # account_number: 09170210248397
    return SuccessService.response(movements_model)


@router.get("/get_owner_accounts", status_code=status.HTTP_200_OK)
async def get_balances_from_interbanking(db: db_dependency, user: internal_dependency):
    ib_service = InterBankingService()
    balances_model = await ib_service.get_accounts_balances()
    accounts = await ib_service.get_accounts_only()
    allowed_accounts = _filter_entity_accounts(
        accounts,
        _entity_cbus(db, user["entity_id"]),
    )
    allowed_numbers = {
        _normalize_account(account.get("account_number"))
        for account in allowed_accounts
    }
    return SuccessService.response([
        balance
        for balance in balances_model["result"]
        if _normalize_account(balance.get("account_number")) in allowed_numbers
    ])


@router.get("/get_all_movements", status_code=status.HTTP_200_OK)
async def get_all_movements(
    db: db_dependency,
    user: internal_dependency,
    date_since: Optional[str],
    date_until: Optional[str],
):
    ib_service = InterBankingService()
    movements_model = await ib_service.get_movements_for_all_accounts(
        date_since=date_since, date_until=date_until
    )
    return SuccessService.response(
        _filter_entity_accounts(
            movements_model,
            _entity_cbus(db, user["entity_id"]),
        )
    )


@router.get("/get_accounts", status_code=status.HTTP_200_OK)
async def get_accounts(user: internal_dependency):
    ib_service = InterBankingService()
    accounts_model = await ib_service.get_accounts_only()
    return SuccessService.response(accounts_model)
