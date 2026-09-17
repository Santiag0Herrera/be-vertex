from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from app.db.database import get_db
from starlette import status
from app.schemas.clients import NewClientRequest, UpdateClientRequest
from app.services.auth_service import require_admin_user, require_client, require_internal_user
from app.services.DBService import DBService 

router = APIRouter(
  prefix='/clients',
  tags=['Clients']
)

db_dependency = Annotated[Session, Depends(get_db)]
internal_dependency = Annotated[dict, Depends(require_internal_user)]
admin_dependency = Annotated[dict, Depends(require_admin_user)]
client_dependency = Annotated[dict, Depends(require_client)]

@router.get(
    "/all", 
    status_code=status.HTTP_200_OK
)
async def get_all_clients(db: db_dependency, user: internal_dependency):
  db_service = DBService(db=db, req_user=user)
  clients_model = db_service.client.get_all()
  return clients_model


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_new_client(db: db_dependency, user: admin_dependency, new_client_request: NewClientRequest):
  db_service = DBService(db=db, req_user=user)
  create_client_model = db_service.client.create(new_client_request)
  return create_client_model


@router.put("/update", status_code=status.HTTP_200_OK)
async def update_client(
  db: db_dependency,
  user: admin_dependency,
  client_id: int,
  update_client_request: UpdateClientRequest
):
  db_service = DBService(db=db, req_user=user)
  update_client_model = db_service.client.update(client_id, update_client_request)
  return update_client_model


@router.delete("/delete", status_code=status.HTTP_200_OK)
async def delete_client_by_id(db: db_dependency, user: admin_dependency, client_id: int):
  db_service = DBService(db=db, req_user=user)
  delete_client_model = db_service.client.delete(client_id)
  return delete_client_model


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_client_by_id(db: db_dependency, user: client_dependency):
  db_service = DBService(db=db, req_user=user)
  get_client_model = db_service.client.get_current()
  return get_client_model
