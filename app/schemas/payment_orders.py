from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class NewPaymentOrderRequest(BaseModel):
    customer_balance_id: int = Field(..., gt=0)
    amount: Decimal = Field(..., gt=0, le=99999999, max_digits=10, decimal_places=2)


class ExecutePaymentOrderRequest(BaseModel):
    order_id: int = Field(..., gt=0)
    amount: Optional[Decimal] = Field(None, gt=0, le=99999999, max_digits=10, decimal_places=2)
    date: datetime = Field(default_factory=datetime.utcnow)
