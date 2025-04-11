from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user
from models import Entity, Users, Product
from services.user_perm_validatior import validate_user_minimum_hierarchy

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

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_products(db: db_dependency, user: user_dependency):
  validate_user_minimum_hierarchy(user=user, min_level="users")
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  entity_model = db.query(Entity).filter(Entity.id == user_model.entity_id).first()
  if entity_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User entity not found")
  
  prodcuts_model = db.query(Product).filter(Product.name == entity_model.products).all() ## EN UN FUTURO CAMBIAR ESTO POR MANY TO MANY
  if prodcuts_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Products not found")
  
  return prodcuts_model