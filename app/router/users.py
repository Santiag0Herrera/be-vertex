from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Body
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.schemas.users import ChangePasswordRequest, CreateUserRequest, ChangePermissonRequest
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
async def create_new_user(user: user_dependency, db: db_dependency, create_user_request: CreateUserRequest):
  db_service = DBService(db=db, req_user=user)
  create_user_model = db_service.users.create(create_user_request)
  return create_user_model


@router.delete("/delete", status_code=status.HTTP_200_OK)
async def delete_user(user: user_dependency, db: db_dependency, user_id: int):
  db_service = DBService(db=db, req_user=user)
  delete_user_model = db_service.users.delete(user_id)
  return delete_user_model


@router.put("/changePermisson", status_code=status.HTTP_200_OK)
async def change_permisson(user: user_dependency, db: db_dependency, change_permisson_request: ChangePermissonRequest):
  db_service = DBService(db=db, req_user=user)
  change_perm_model = db_service.users.change_permission(change_permisson_request)
  return change_perm_model