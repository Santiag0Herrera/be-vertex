from pydantic import BaseModel, Field

class CreateUserRequest(BaseModel):
  first_name: str
  last_name: str
  email: str
  password: str
  phone: str
  permission_level: str
  entity: str

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