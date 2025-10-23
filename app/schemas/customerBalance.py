from pydantic import BaseModel

class CustomerBalanceCreateRequest(BaseModel):
    balance_amount: int
    balance_currency_id:int