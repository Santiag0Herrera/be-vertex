from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from app.models import Users
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user, bcrypt_context
from app.schemas.users import ChangePasswordRequest, CreateUserRequest
from app.services.DBService import DBService

router = APIRouter(
  prefix='/users',
  tags=['Users']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_users(db: db_dependency, user: user_dependency):
  db_service = DBService(db=db, req_user=user)
  users = db_service.users.get_all()
  return users

@router.get("/me", status_code=status.HTTP_200_OK)
async def get_current_user_info(user: user_dependency, db: db_dependency):
  db_service = DBService(db=db, req_user=user)
  current_user = db_service.users.get_current()
  return current_user


@router.put("/me/changePassword", status_code=status.HTTP_200_OK)
async def change_password(user: user_dependency, db: db_dependency, change_password_request: ChangePasswordRequest):
  db_service = DBService(db=db, req_user=user)
  password_change = db_service.users.change_password(change_password_request)
  return password_change


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


@router.delete("/delete", status_code=status.HTTP_200_OK)
async def delete_user(user: user_dependency, db: db_dependency, user_id: int):
  if user.get("id") == user_id:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes eliminar tu usuario")
  
  user_to_remove_model = db.query(Users).filter(Users.id == user_id).first()

  if user_to_remove_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Usuario Nro {user_id} no existe")
  
  if user_to_remove_model.perm_id == 3:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El usuario que intentaste eliminar es un cliente")
  
  db.delete(user_to_remove_model)
  db.commit()
  return {
    "detail": f"Usuario {user_to_remove_model.first_name} {user_to_remove_model.last_name} fue eliminado exitosamente."
  }