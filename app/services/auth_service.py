import os
import re

from app.models import Users, Entity, Clients, Permission
from typing import Annotated
from app.db.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException
from datetime import timedelta, datetime, timezone
from starlette import status
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
ALGORITHM = 'HS256'

bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
db_dependency = Annotated[Session, Depends(get_db)]
oauth2_bearer = OAuth2PasswordBearer(tokenUrl='auth/token')


def get_secret_key() -> str:
  secret_key = os.getenv('JWT_SECRET_KEY') or os.getenv('SECRET_KEY')
  if not secret_key:
    raise RuntimeError('JWT_SECRET_KEY is required')
  return secret_key


def decode_access_token(token: str) -> dict:
  try:
    return jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
  except (JWTError, RuntimeError) as exc:
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail='Invalid Credentials',
    ) from exc

def authenticate_user(identifier: str, password: str, db):
  normalized_identifier = identifier.strip().lower()
  normalized_cuit = re.sub(r"\D", "", normalized_identifier)
  user = None
  if len(normalized_cuit) == 11:
    user = db.query(Clients).filter(
      Clients.cuit == normalized_cuit,
      Clients.enabled == True
    ).first()
  if not user:
    user = db.query(Users).filter(
      Users.email == normalized_identifier,
      Users.enabled == True
    ).first()
  if not user:
    return False
  if not bcrypt_context.verify(password, user.hashed_password):
    return False
  return user


def create_token(email: str, user_id: int, permission_level: str, perm_id: int, hierarchy: int, entity_id: int, account_type: str, expires_delta: timedelta, db: db_dependency):
  entity = db.query(Entity).filter(Entity.id == entity_id).first()
  if entity is None or entity.status != 'enabled':
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Entity not enabled")
  
  encode = {
      'sub': email,
      'id': user_id,
      'perm': permission_level,
      'perm_id': perm_id,
      'hierarchy': hierarchy,
      'entity_id': entity_id,
      'account_type': account_type
  }
  expires = datetime.now(timezone.utc) + expires_delta
  encode.update({'exp': expires})
  return jwt.encode(encode, get_secret_key(), algorithm=ALGORITHM)


async def get_current_user(
  token: Annotated[str, Depends(oauth2_bearer)],
  db: db_dependency,
):
  payload = decode_access_token(token)
  subject = payload.get('sub')
  user_id = payload.get('id')
  entity_id = payload.get('entity_id')
  account_type = payload.get('account_type')

  if not subject or not isinstance(user_id, int) or account_type not in {'user', 'client'}:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials')

  model = Clients if account_type == 'client' else Users
  actor = db.query(model).filter(
    model.id == user_id,
    model.enabled == True,
  ).first()
  if actor is None or actor.entity_id != entity_id:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials')

  entity = db.query(Entity).filter(
    Entity.id == actor.entity_id,
    Entity.status == 'enabled',
  ).first()
  permission = db.query(Permission).filter(Permission.id == actor.perm_id).first()
  expected_subject = actor.cuit if account_type == 'client' else actor.email

  if (
    entity is None
    or permission is None
    or expected_subject != subject
    or payload.get('perm_id') != permission.id
    or payload.get('perm') != permission.level
    or payload.get('hierarchy') != permission.hierarchy
  ):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials')

  return {
    'email': subject,
    'id': actor.id,
    'user_perm': permission.level,
    'hierarchy': permission.hierarchy,
    'entity_id': actor.entity_id,
    'user_perm_id': permission.id,
    'account_type': account_type,
  }


async def require_internal_user(
  user: Annotated[dict, Depends(get_current_user)],
) -> dict:
  if user.get('account_type') != 'user':
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Internal user required')
  return user


async def require_client(
  user: Annotated[dict, Depends(get_current_user)],
) -> dict:
  if user.get('account_type') != 'client':
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Client account required')
  return user


async def require_admin_user(
  user: Annotated[dict, Depends(require_internal_user)],
) -> dict:
  if user.get('user_perm') not in {'admin', 'super'}:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Administrator required')
  return user
