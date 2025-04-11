from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from models import Users
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user
from passlib.context import CryptContext

router = APIRouter(
  prefix='/users',
  tags=['Users']
)

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close() 

class UserVerification(BaseModel):
  password: str
  new_password: str = Field(min_length=6)


bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


def validate_user(user):
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
  return True


@router.get("/all", status_code=status.HTTP_200_OK)
async def get_users(db: db_dependency, user: Annotated[dict, Depends(get_current_user)]):
  validate_user(user=user)
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  return db.query(Users).filter(Users.entity_id == user_model.entity_id).all()


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_current_user_info(user: user_dependency, db: db_dependency):
  validate_user(user=user)
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  if user_model.entity.status != 'enabled':
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Entity not enabled")
  return {
  'id': user_model.id,
  'first_name': user_model.first_name,
  'last_name': user_model.last_name,
  'email': user_model.email,
  'permission_level': user_model.permission,
  'phone': user_model.phone,
  'entity': {
    'name': user_model.entity.name ,
    'id': user_model.entity.id
  }
}


@router.put("/me/changePassword", status_code=status.HTTP_200_OK)
async def change_password(user: user_dependency, db: db_dependency, user_verification: UserVerification):
  validate_user(user=user)
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  if not bcrypt_context.verify(user_verification.password, user_model.hashed_password):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Incorrect password')
  user_model.hashed_password = bcrypt_context.hash(user_verification.new_password)
  db.add(user_model)
  db.commit()