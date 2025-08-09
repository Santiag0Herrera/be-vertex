from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.services.DBService import DBService 

router = APIRouter(
  prefix='/clients',
  tags=['Clients']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_clients(db: db_dependency, user: user_dependency):
  db_service = DBService(db=db, req_user=user)
  clients_model = db_service.client.get_all()
  return clients_model