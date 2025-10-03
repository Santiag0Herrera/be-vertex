from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest, UploadDocumentRequest, MovementsRequest
from app.services.DBService import DBService
from app.services.InterBankingService import InterBankingService

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
    month: int = Query(..., gt=0, lt=13),
    year: int = Query(..., gt=2000),
    day: int = Query(..., gt=0, lt=32)
):
  db_service = DBService(db=db, req_user=user)
  transactions_model = db_service.trx.get_all(day, month, year)
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

@router.post("/get_movements", status_code=status.HTTP_200_OK)
async def get_movements_from_interbanking(user: user_dependency, movements_request: MovementsRequest):
  ib_service = InterBankingService()
  movements_model = await ib_service.get_movement(
    movements_request.account_number, 
    movements_request.bank_number, 
    movements_request.customer_id
  )
  # 015
  # C66408A
  # 09170210248397
  return movements_model