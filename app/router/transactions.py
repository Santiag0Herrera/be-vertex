from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest, UploadDocumentRequest, MovementsRequest, AllMovementsRequest
from app.services.DBService import DBService
from app.services.InterBankingService import InterBankingService
from typing import Optional

router = APIRouter(
  prefix='/trx',
  tags=['Transactions']
) 

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_transactions(
    db: db_dependency,
    user: user_dependency,
    page: int = Query(0, ge=0),
    recordsPerPage: int = Query(10, gt=0),
    dateFrom: Optional[str] = Query(None),
    dateTo: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    account_id: Optional[int] = Query(None),
    client_id: Optional[int] = Query(None)
):
  db_service = DBService(db=db, req_user=user)
  transactions_model = db_service.trx.get_all(
      page,
      recordsPerPage,
      dateFrom,
      dateTo,
      status,
      account_id,
      client_id,
  )
  return transactions_model


@router.post("/new", status_code=status.HTTP_201_CREATED)
async def upload_new_document(db: db_dependency, document_request: DocumentRequest, user: user_dependency):
  db_service = DBService(db=db, req_user=None)
  trx_model = db_service.trx.create(document_request, user)
  return trx_model

@router.post("/multiple/new", status_code=status.HTTP_201_CREATED)
async def upload_multiple_new_document(db: db_dependency, user: user_dependency, multiple_trx_request: MultipleDocumentRequest):
  db_service = DBService(db=db, req_user=user)
  trx_model = db_service.trx.create_multiple(multiple_trx_request)
  return trx_model

@router.post("/upload-file", status_code=status.HTTP_201_CREATED)
async def upload_new_file(db: db_dependency,  user: user_dependency, upload_document_request: UploadDocumentRequest):
  db_service = DBService(db=db, req_user=user)
  uploaded_file = await db_service.trx.upload_file(upload_document_request)
  return uploaded_file

@router.get("/get_movement", status_code=status.HTTP_200_OK)
async def get_movements_from_interbanking(
    user: user_dependency, 
    account_number: str = Query(...), 
    bank_number: str = Query(...), 
    date_since: Optional[str] = Query(None), 
    date_until: Optional[str] = Query(None)
):
  ib_service = InterBankingService()
  movements_model = await ib_service.get_movement(
    account_number, 
    bank_number,
    date_since=date_since,
    date_until=date_until
  )
  # bank_number: 015
  # account_number: 09170210248397
  return movements_model

@router.post("/get_movements", status_code=status.HTTP_200_OK)
async def get_movements_from_interbanking(user: user_dependency, movements_request: MovementsRequest):
  ib_service = InterBankingService()
  movements_model = await ib_service.get_movement(
    movements_request.account_number, 
    movements_request.bank_number,
    date_since=movements_request.date_since,
    date_until=movements_request.date_until
  )
  # bank_number: 015
  # account_number: 09170210248397
  return movements_model

@router.get("/get_owner_accounts", status_code=status.HTTP_200_OK)
async def get_balances_from_interbanking(user: user_dependency):
  ib_service = InterBankingService()
  balances_model = await ib_service.get_accounts_balances()
  return balances_model


@router.get("/get_all_movements", status_code=status.HTTP_200_OK)
async def get_all_movements(user: user_dependency, date_since: Optional[str], date_until: Optional[str]):
  ib_service = InterBankingService()
  movements_model = await ib_service.get_movements_for_all_accounts(date_since=date_since, date_until=date_until)
  return movements_model


@router.get("/get_accounts", status_code=status.HTTP_200_OK)
async def get_accounts(user: user_dependency):
    ib_service = InterBankingService()
    accounts_model = await ib_service.get_accounts_only()
    return accounts_model
