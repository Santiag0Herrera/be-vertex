from fastapi import APIRouter, Depends, HTTPException
from starlette import status
from app.db.database import get_db
from app.models import Clients, Permission
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.schemas.auth import Token
from app.services.auth_service import create_token, authenticate_user

router = APIRouter(
  prefix='/auth',
  tags=['Authentication']
)

@router.post("/token", response_model=Token)
async def get_login_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
  user = authenticate_user(form_data.username, form_data.password, db)
  if not user: 
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail='CUIT, correo electrónico o contraseña incorrectos.',
      headers={'WWW-Authenticate': 'Bearer'}
    )
  
  user_permission = db.query(Permission).filter(user.perm_id == Permission.id).first()
  if user_permission is None:
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail='La cuenta no tiene un permiso válido.',
    )
  token = create_token(
      email=user.cuit if isinstance(user, Clients) else user.email,
      user_id=user.id,
      permission_level=user_permission.level,
      perm_id=user_permission.id,
      hierarchy=user_permission.hierarchy,
      entity_id=user.entity_id,
      account_type='client' if isinstance(user, Clients) else 'user',
      expires_delta=timedelta(hours=8),
      db=db
  )
  return {'access_token': token, 'token_type': 'Bearer', 'user_level': user_permission.level}
