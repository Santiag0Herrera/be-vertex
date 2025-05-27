from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from db.database import get_db
from starlette import status
from .auth import get_current_user
from models import Entity, Users, Product

router = APIRouter(
  prefix='/products',
  tags=['Products']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_products(db: db_dependency, user: user_dependency):
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  entity_model = db.query(Entity).filter(Entity.id == user_model.entity_id).first()
  if entity_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User entity not found")
  
  prodcuts_model = db.query(Product).filter(Product.name == entity_model.products).all() ## EN UN FUTURO CAMBIAR ESTO POR MANY TO MANY
  if prodcuts_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Products not found")
  
  return prodcuts_model