from pydantic import BaseModel

class Token(BaseModel):
  access_token: str
  token_type: str
  user_level: str

class ReqUser:
  sub: str
  id: int
  perm: str
  perm_id: int
  hierarchy: int
  entity_id: int
  account_type: str
