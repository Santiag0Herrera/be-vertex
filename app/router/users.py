from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from app.models import Users
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user, bcrypt_context
from app.schemas.users import UserVerification, CreateUserRequest

router = APIRouter(
  prefix='/users',
  tags=['Users']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_users(db: db_dependency, user: Annotated[dict, Depends(get_current_user)]):
  users_model = db.query(Users).filter(
      Users.entity_id == user.get('entity_id'),
      Users.perm_id != 3
  ).all()
  return users_model


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_current_user_info(user: user_dependency, db: db_dependency):
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
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
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  if not bcrypt_context.verify(user_verification.password, user_model.hashed_password):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Incorrect password')
  user_model.hashed_password = bcrypt_context.hash(user_verification.new_password)
  db.add(user_model)
  db.commit()


@router.post("/newUser", status_code=status.HTTP_201_CREATED)
async def create_new_user(user: user_dependency, db: db_dependency, new_user_request: CreateUserRequest):

  user_exists_model = db.query(Users).filter(Users.email == new_user_request.email).first()
  if user_exists_model:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Usuario {new_user_request.email} ya existe.")
  
  auto_generated_password = (new_user_request.first_name[:2] + new_user_request.last_name + "123").lower()

  create_user_model = Users(
    first_name=new_user_request.first_name,
    last_name=new_user_request.last_name,
    email=new_user_request.email,
    hashed_password=bcrypt_context.hash(auto_generated_password),
    phone=new_user_request.phone,
    perm_id=2,
    entity_id=user.get('entity_id')
  )
  db.add(create_user_model)
  db.commit()

  return {
    "detail": "Usuario creado correctamente",
    "generated_password": auto_generated_password
  }