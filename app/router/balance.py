from typing import Annotated
from sqlalchemy.orm import Session
from starlette import status
from fastapi import APIRouter, Depends
from app.db.database import get_db
from app.services.auth_service import get_current_user
from app.services.DBService import DBService 
from app.schemas.customerBalance import CustomerBalanceCreateRequest

router = APIRouter(
  prefix='/balance',
  tags=['Customers Balance']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_clients_balance(db: db_dependency, user: user_dependency):
  db_service = DBService(db=db, req_user=user)
  balance_model = db_service.balance.get_all()
  return balance_model


@router.get("/detail")
async def get_balance_by_client_id(db: db_dependency, user: user_dependency, account_id: int):
  db_service = DBService(db=db, req_user=user)
  balance_model = db_service.balance.get_all_movements(account_id=account_id)
  return balance_model


@router.post("/create")
async def create_new_balance_account(
  db: db_dependency, 
  user: user_dependency,
  customer_balance_request: CustomerBalanceCreateRequest
):
  db_service = DBService(db=db, req_user=user)
  new_balance_request = db_service.balance.create(
    customer_balance_request=customer_balance_request
  )
  return new_balance_request
