import datetime
from pydantic import BaseModel, Field

class NewPaymentRequest(BaseModel):
  amount: float = Field(..., gt=0, le=99999999, allow_inf_nan=False)
  date: datetime.datetime = Field(...)
  customer_balance_id: int = Field(...)
  currency_id: int
