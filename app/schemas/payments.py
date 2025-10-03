import datetime
from pydantic import BaseModel, Field

class NewPaymentRequest(BaseModel):
  amount: float = Field(..., min=1, max=99999999)
  date: datetime.date = Field(...)
  customer_balance_id: int = Field(...)
  currency_id: int