from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user
from models import Entity, CBU, Users, Product

router = APIRouter(
  prefix='/products',
  tags=['Products']
)

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
  validate_user(user=user)
  if user.get('user_perm') != 'admin':
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Insufficient permissions.")
  return True

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_products(db: db_dependency, user: user_dependency):
  validate_user(user=user)
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  entity_model = db.query(Entity).filter(Entity.id == user_model.entity_id).first()
  if entity_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User entity not found")
  
  prodcuts_model = db.query(Product).filter(Product.name == entity_model.products).all() ## EN UN FUTURO CAMBIAR ESTO POR MANY TO MANY
  if prodcuts_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Products not found")
  
  return prodcuts_model