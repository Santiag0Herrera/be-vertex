from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette import status

from app.db.database import get_db
from app.services.auth_service import require_internal_user
from app.services.DBService import DBService
from app.services.SuccessService import SuccessService


router = APIRouter(prefix="/dashboard", tags=["Internal Dashboard"])
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(require_internal_user)]


@router.get(
  "/summary",
  status_code=status.HTTP_200_OK,
)
async def get_dashboard_summary(
  db: db_dependency,
  user: user_dependency,
):
  summary = DBService(db=db, req_user=user).dashboard.get_summary()
  return SuccessService.response(summary)
