from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status
from pydantic import BaseModel, Field
from db.database import SessionLocal
from models import Users, Entity, Permission
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import timedelta, datetime, timezone

router = APIRouter(
  prefix='/auth',
  tags=['Authentication']
)

SECRET_KEY = 'bf75bf97eb8839552b6d64790c35fdecbe8874bd1791917b650494d3d54c60b5'
ALGORITHM = 'HS256'

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close()

db_dependency = Annotated[Session, Depends(get_db)]
bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_bearer = OAuth2PasswordBearer(tokenUrl='auth/token')


class CreateUserRequest(BaseModel):
  first_name: str
  last_name: str
  email: str
  password: str
  phone: str
  permission_level: str
  entity: str



class Token(BaseModel):
  access_token: str
  token_type: str


def authenticate_user(email: str, password: str, db):
  user = db.query(Users).filter(Users.email == email).first()
  if not user:
    return False
  if not bcrypt_context.verify(password, user.hashed_password):
    return False
  return user


def create_token(email: str, user_id: int, permission: str, expires_delta: timedelta):
  encode = {'sub': email, 'id': user_id, 'perm': permission}
  expires = datetime.now(timezone.utc) + expires_delta
  encode.update({'exp': expires})
  return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: Annotated[str, Depends(oauth2_bearer)]):
  try:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    email: str = payload.get('sub')
    user_id: int = payload.get('id')
    user_perm: str = payload.get('perm')
    if email is None or user_id is None:
      raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials') 
    return {'email': email, 'id': user_id, 'user_perm': user_perm}
  except JWTError:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials')


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
    hashed_password=bcrypt_context.hash(create_user_request.password),
    phone=create_user_request.phone,
    perm_id=permission_model.id,
    entity_id=entity_model.id
  )
  db.add(create_user_model)
  db.commit()


@router.post("/token", response_model=Token)
async def get_login_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency):
  user = authenticate_user(form_data.username, form_data.password, db)
  if not user: 
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Could not validate user.')
  user_permission = db.query(Permission).filter(user.perm_id == Permission.id).first()
  token = create_token(user.email, user.id, user_permission.level, timedelta(minutes=20 ))
  return {'access_token': token, 'token_type': 'bearer'}


@router.get("/users", status_code=status.HTTP_200_OK)
async def get_users(db: db_dependency):
  return db.query(Users).all()

@router.delete("/users", status_code=status.HTTP_202_ACCEPTED)
async def delete_user(db: db_dependency, user_id: int):
  user_model = db.query(Users).filter(Users.id == user_id).first()
  if user_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
  db.query(Users).filter(Users.id == user_id).delete()
  db.commit()