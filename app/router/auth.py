from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from starlette import status
from app.db.database import get_db
from app.models import Users, Entity, Permission
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from datetime import timedelta
from app.schemas.auth import CreateUserRequest, Token
from app.services.auth_service import create_token, authenticate_user, get_current_user
from app.services.auth_service import get_bcrypt_context

db_dependency = Annotated[Session, Depends(get_db)]

router = APIRouter(
  prefix='/auth',
  tags=['Authentication']
)

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_user(db: db_dependency, create_user_request: CreateUserRequest):
  # FIRST WE VALIDATE IF THE ENTITY EXISTS
  entity_model = db.query(Entity).filter(Entity.name == create_user_request.entity).first()
  if entity_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity {create_user_request.entity} not found.")
  
  # IF ENTITY EXISTS, THEN WE VALIDATE IF USER'S PERMISSION EXISTS
  permission_model = db.query(Permission).filter(Permission.level == create_user_request.permission_level).first()
  if permission_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Permission {create_user_request.permission_level} not found.")
  
  # IF ENTITY AND PERMISSION, BOTH EXIST, WE CREATE THE USER WITH BOTH FK
  create_user_model = Users(
    first_name=create_user_request.first_name,
    last_name=create_user_request.last_name,
    email=create_user_request.email,
    hashed_password=get_bcrypt_context.hash(create_user_request.password),
    phone=create_user_request.phone,
    perm_id=permission_model.id,
    entity_id=entity_model.id
  )
  db.add(create_user_model)
  db.commit()


@router.post("/token", response_model=Token)
async def get_login_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
  user = authenticate_user(form_data.username, form_data.password, db)
  if not user: 
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Could not validate user.')
  
  user_permission = db.query(Permission).filter(user.perm_id == Permission.id).first()
  token = create_token(
      email=user.email,
      user_id=user.id,
      permission_level=user_permission.level,
      perm_id=user_permission.id,
      hierarchy=user_permission.hierarchy,
      entity_id=user.entity_id,
      expires_delta=timedelta(minutes=20),
      db=db
  )
  return {'access_token': token, 'token_type': 'Bearer', 'user_level': user_permission.level}


@router.delete("/users", status_code=status.HTTP_202_ACCEPTED)
async def delete_user(db: db_dependency, user_id: int, user: Annotated[dict, Depends(get_current_user)]):
  user_model = db.query(Users).filter(Users.id == user_id).first()
  if user_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
  
  db.query(Users).filter(Users.id == user_id).delete()
  db.commit()