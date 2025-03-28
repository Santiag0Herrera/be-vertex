from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user
from models import Entity, CBU

router = APIRouter(
  prefix='/entities',
  tags=['Entities']
)

class DocumentRequest(BaseModel):
  base64: str = Field(min_length=10)
  type: str
  bank: str

class NewEntityRequest(BaseModel):
  name: str = Field(..., min_length=1, max_length=255)
  mail: str = Field(..., min_length=5, max_length=255, pattern=r'^\S+@\S+\.\S+$', examples=["email@domain.com"])
  phone: str = Field(..., min_length=10, max_length=25, pattern=r'^\+?\d{10,25}$')
  products: str = Field(..., min_length=1, max_length=255)
  status: str = Field(..., min_length=1, max_length=50)
  cbu_number: str = Field(..., min_length=22, max_length=22, pattern=r'^\d{22}$')
  cbu_bank_account: str = Field(..., min_length=1, max_length=255)
  cbu_alias: str = Field(..., min_length=1, max_length=255)
  cbu_cuit: str = Field(..., min_length=1, max_length=255)

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close() 

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

def validate_user(user):
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  return True

def validate_user_admin(user):
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

  if user.get('user_perm') != 'admin':
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Insufficient permissions.")
  return True


@router.get("", status_code=status.HTTP_200_OK)
async def get_all_entities(db: db_dependency, user: user_dependency):
  validate_user_admin(user=user)
  return db.query(Entity).all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_new_entity(db: db_dependency, user: user_dependency, entity_request: NewEntityRequest):
  validate_user_admin(user=user)
  
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