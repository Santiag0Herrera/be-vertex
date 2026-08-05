from datetime import datetime

from pydantic import BaseModel, Field

class CustomerBalanceCreateRequest(BaseModel):
    client_id: int
    balance_currency_id:int
    fee_percentage: float = Field(default=0.0, ge=0, le=100)


class FeeWithdrawalRequest(BaseModel):
    customer_balance_id: int
    amount: float = Field(..., gt=0, le=99999999)
    date: datetime
