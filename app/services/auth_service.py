from app.models import Users, Entity
from typing import Annotated
from app.db.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException
from datetime import timedelta, datetime, timezone
from starlette import status
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = 'bf75bf97eb8839552b6d64790c35fdecbe8874bd1791917b650494d3d54c60b5'
ALGORITHM = 'HS256'

bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
db_dependency = Annotated[Session, Depends(get_db)]
oauth2_bearer = OAuth2PasswordBearer(tokenUrl='auth/token')

def authenticate_user(email: str, password: str, db):
  user = db.query(Users).filter(Users.email == email).first()
  if not user:
    return False
  if not bcrypt_context.verify(password, user.hashed_password):
    return False
  return user


def create_token(email: str, user_id: int, permission_level: str, perm_id: int, hierarchy: int, entity_id: int, expires_delta: timedelta, db: db_dependency):
  entity = db.query(Entity).filter(Entity.id == entity_id).first()
  # NO TOKEN WILL BE GENERATED IF ENTIY IS NOT ENABLED
  if entity.status != 'enabled':
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Entity not enabled")
  
  encode = {
      'sub': email,
      'id': user_id,
      'perm': permission_level,
      'perm_id': perm_id,
      'hierarchy': hierarchy,
      'entity_id': entity_id
  }
  expires = datetime.now(timezone.utc) + expires_delta
  encode.update({'exp': expires})
  return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: Annotated[str, Depends(oauth2_bearer)]):
  try:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    email: str = payload.get('sub')
    user_id: int = payload.get('id')
    user_perm: str = payload.get('perm')
    user_perm_id: str = payload.get('perm_id')
    hierarchy: str = payload.get('hierarchy')
    entity_id: str = payload.get('entity_id')
    if email is None or user_id is None:
      raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials') 
    return {
      'email': email, 
      'id': user_id, 
      'user_perm': user_perm, 
      'hierarchy': hierarchy, 
      'entity_id': entity_id, 
      'user_perm_id': user_perm_id
    }
  except JWTError:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid Credentials')
