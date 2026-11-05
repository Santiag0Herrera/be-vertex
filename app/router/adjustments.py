from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from starlette import status

from app.db.database import get_db
from app.schemas.adjustments import AnnulAdjustmentRequest, NewAdjustmentRequest
from app.services.DBService import DBService
from app.services.auth_service import require_admin_user, require_internal_user

router = APIRouter(
  prefix='/adjustments',
  tags=['Notas de crédito y débito']
)

db_dependency = Annotated[Session, Depends(get_db)]
internal_dependency = Annotated[dict, Depends(require_internal_user)]
admin_dependency = Annotated[dict, Depends(require_admin_user)]


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_adjustment(db: db_dependency, user: admin_dependency, request: NewAdjustmentRequest):
  return DBService(db=db, req_user=user).adjustments.create(request)


@router.post("/annul", status_code=status.HTTP_200_OK)
async def annul_adjustment(db: db_dependency, user: admin_dependency, request: AnnulAdjustmentRequest):
  return DBService(db=db, req_user=user).adjustments.annul(request)


@router.get("/all", status_code=status.HTTP_200_OK)
async def get_adjustments(db: db_dependency, user: internal_dependency, balance_id: int = Query(..., gt=0)):
  return DBService(db=db, req_user=user).adjustments.get_all(balance_id)


@router.get("/detail", status_code=status.HTTP_200_OK)
async def get_adjustment_detail(db: db_dependency, user: internal_dependency, id: int = Query(..., gt=0)):
  return DBService(db=db, req_user=user).adjustments.get_detail(id)
