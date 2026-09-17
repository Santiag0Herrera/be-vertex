from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from app.db.database import get_db
from starlette import status
from app.services.auth_service import require_admin_user
from app.services.DBService import DBService

router = APIRouter(
  prefix='/entities',
  tags=['Entities']
)

db_dependency = Annotated[Session, Depends(get_db)]
admin_dependency = Annotated[dict, Depends(require_admin_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_entities(db: db_dependency, user: admin_dependency):
  db_services = DBService(db=db, req_user=user)
  entities_model = db_services.entities.get_all()
  return entities_model


@router.get("/{entity_id}", status_code=status.HTTP_200_OK)
async def get_entity_by_id(db: db_dependency, user: admin_dependency, entity_id: int):
  db_service = DBService(db=db, req_user=user)
  entity_model = db_service.entities.get_by_id(entity_id)
  return entity_model
