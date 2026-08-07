from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette import status

from app.db.database import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.auth_service import get_current_user
from app.services.DBService import DBService


router = APIRouter(prefix="/dashboard", tags=["Internal Dashboard"])
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


@router.get(
  "/summary",
  response_model=DashboardResponse,
  status_code=status.HTTP_200_OK,
)
async def get_dashboard_summary(
  db: db_dependency,
  user: user_dependency,
) -> DashboardResponse:
  return DBService(db=db, req_user=user).dashboard.get_summary()
