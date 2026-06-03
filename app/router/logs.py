from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from app.db.database import get_db
from starlette import status
from app.services.DBService import DBService
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/logs", tags=["Logs"])

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_logs(db: db_dependency, user: user_dependency):
    db_service = DBService(db=db, req_user=user)
    logs_model = db_service.logs.get_all()
    return logs_model
