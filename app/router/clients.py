from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from app.db.database import get_db
from starlette import status
from app.schemas.clients import ClientResponse, NewClientRequest
from app.services.auth_service import get_current_user
from app.services.DBService import DBService 

router = APIRouter(
  prefix='/clients',
  tags=['Clients']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get(
    "/all", 
    response_model=list[ClientResponse],
    status_code=status.HTTP_200_OK
)
async def get_all_clients(db: db_dependency, user: user_dependency):
  db_service = DBService(db=db, req_user=user)
  clients_model = db_service.client.get_all()
  return clients_model

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_new_client(db: db_dependency, user: user_dependency, new_client_request: NewClientRequest):
  db_service = DBService(db=db, req_user=user)
  create_client_model = db_service.client.create(new_client_request)
  return create_client_model

@router.delete("/delete", status_code=status.HTTP_200_OK)
async def delete_client_by_id(db: db_dependency, user: user_dependency, client_id: int):
  db_service = DBService(db=db, req_user=user)
  delete_client_model = db_service.client.delete(client_id)
  return delete_client_model