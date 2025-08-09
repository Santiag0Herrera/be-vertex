from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.models import Entity, Users, Product
from app.services.DBService import DBService 

router = APIRouter(
  prefix='/products',
  tags=['Products']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_products(db: db_dependency, user: user_dependency):
  db_service = DBService(db=db, req_user=user)
  product_model = db_service.products.get_all()
  return product_model