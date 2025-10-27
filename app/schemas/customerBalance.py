from pydantic import BaseModel

class CustomerBalanceCreateRequest(BaseModel):
    client_id: int
    balance_currency_id:int