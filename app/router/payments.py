from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query
from app.services.DBService import DBService
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.schemas.payments import NewPaymentRequest

router = APIRouter(
  prefix='/payments',
  tags=['Pagos']
) 

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_new_payment(
  db: db_dependency,
  user: user_dependency,
  payment_request: NewPaymentRequest
):
  db_service = DBService(db=db, req_user=user)
  payment_model = db_service.payments.create(payment_request)
  return payment_model
