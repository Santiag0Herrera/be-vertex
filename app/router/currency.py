from typing import Annotated
from sqlalchemy.orm import Session
from starlette import status
from fastapi import APIRouter, Depends
from app.db.database import get_db
from app.services.auth_service import get_current_user
from app.services.DBService import DBService 

router = APIRouter(
  prefix='/currency',
  tags=['Currency']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_currencies(db: db_dependency, user: user_dependency):
  db_service = DBService(db=db, req_user=user)
  currency_model = db_service.currency.get_all()
  return currency_model