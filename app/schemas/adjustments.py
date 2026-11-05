from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class NewAdjustmentRequest(BaseModel):
    customer_balance_id: int = Field(..., gt=0)
    type: Literal["credito", "debito"]
    amount: Decimal = Field(..., gt=0, le=99999999, max_digits=10, decimal_places=2)
    currency_id: int = Field(..., gt=0)
    reason: str = Field(..., min_length=3, max_length=500)
    reference: Optional[str] = Field(None, max_length=100)
    date: datetime = Field(default_factory=datetime.utcnow)


class AnnulAdjustmentRequest(BaseModel):
    adjustment_id: int = Field(..., gt=0)
    reason: str = Field(..., min_length=3, max_length=500)
