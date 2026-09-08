from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.payment_orders import NewPaymentOrderRequest, ExecutePaymentOrderRequest
from app.services.auth_service import get_current_user
from app.services.PaymentOrderService import PaymentOrderService

router = APIRouter(prefix="/payment-orders", tags=["Órdenes de pago"])
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


@router.post("/create", status_code=201)
def create(db: db_dependency, user: user_dependency, request: NewPaymentOrderRequest):
    return PaymentOrderService(db, user).create(request)


@router.get("/all")
def get_all(
    db: db_dependency,
    user: user_dependency,
    page: int = Query(0, ge=0),
    recordsPerPage: int = Query(10, gt=0, le=100),
    status: Optional[
        Literal[
            "pendiente_aprobacion",
            "parcialmente_ejecutada",
            "ejecutada",
        ]
    ] = None,
    customer_balance_id: Optional[int] = Query(None, gt=0),
):
    return PaymentOrderService(db, user).get_all(
        page=page,
        records_per_page=recordsPerPage,
        status=status,
        customer_balance_id=customer_balance_id,
    )


@router.get("/detail")
def detail(
    db: db_dependency,
    user: user_dependency,
    order_id: int = Query(..., gt=0),
    page: int = Query(0, ge=0),
    recordsPerPage: int = Query(10, gt=0, le=100),
):
    return PaymentOrderService(db, user).get_detail(
        order_id=order_id,
        page=page,
        records_per_page=recordsPerPage,
    )


@router.post("/execute", status_code=201)
def execute(db: db_dependency, user: user_dependency, request: ExecutePaymentOrderRequest):
    return PaymentOrderService(db, user).execute(request)
