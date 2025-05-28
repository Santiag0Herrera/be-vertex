from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.models import Entity, CBU
from app.schemas.entities import NewEntityRequest

router = APIRouter(
  prefix='/entities',
  tags=['Entities']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("", status_code=status.HTTP_200_OK)
async def get_all_entities(db: db_dependency):
  return db.query(Entity).all()


@router.get("/{entity_id}", status_code=status.HTTP_200_OK)
async def get_entity_by_id(db: db_dependency, entity_id: int):
  entity = db.query(Entity).filter(Entity.id == entity_id).first()
  if entity is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity with ID {entity_id} not found")  
  return entity


@router.post("/new", status_code=status.HTTP_201_CREATED)
async def create_new_entity(db: db_dependency, entity_request: NewEntityRequest):
  entity_exists_model = db.query(Entity).filter(Entity.mail == entity_request.mail).first()
  if entity_exists_model is not None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Entity with mail {entity_request.mail} already exists")

  create_cbu_model = CBU(
    nro=entity_request.cbu_number,
    banco=entity_request.cbu_bank_account,
    alias=entity_request.cbu_alias,
    cuit=entity_request.cbu_cuit
  )
  try:
    db.add(create_cbu_model)
    db.commit()
  except Exception as e:
    db.rollback()
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error trying to create CBU: {str(e)}")
  
  create_entity_model = Entity(
    name=entity_request.name,
    mail=entity_request.mail,
    phone=entity_request.phone,
    products=entity_request.products, 
    status=entity_request.status,
    cbu_id=create_cbu_model.id,
  )
  
  try:
    db.add(create_entity_model)
    db.commit()
    db.refresh(create_entity_model)
  except Exception as e:
    db.rollback()
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error trying to create Entity: {str(e)}")