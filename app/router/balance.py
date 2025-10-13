from typing import Annotated
from sqlalchemy.orm import Session
from starlette import status
from fastapi import APIRouter, Depends
from app.db.database import get_db
from app.services.auth_service import get_current_user
from app.services.DBService import DBService 

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
async def get_balance_by_client_id(db: db_dependency, user: user_dependency, client_id: int):
  db_service = DBService(db=db, req_user=user)
  balance_model = db_service.balance.get_all_movements(client_id=client_id)
  return balance_model
