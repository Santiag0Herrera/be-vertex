from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from db.database import get_db
from starlette import status
from services.auth_service import get_current_user
from models import Users, Permission

router = APIRouter(
  prefix='/clients',
  tags=['Clients']
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_clients(db: db_dependency, user: user_dependency):
  perm_model = db.query(Permission).filter(Permission.level == 'client').first()
  if perm_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error searching for permissions")
  
  clients_model = db.query(Users).filter(Users.perm_id == perm_model.id, Users.entity_id == user.get('entity_id')).all()
  if clients_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error searching for clients")
  
  return clients_model